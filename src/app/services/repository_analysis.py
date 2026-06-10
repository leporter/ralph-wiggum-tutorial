"""Deterministic heuristic analyzer + cache orchestration for /learn.

Given a GitHub URL, :func:`analyze_repository` produces a student-oriented
learning path: which files matter, *why*, and in what order to read them. The
output is intentionally **deterministic** — no LLM, no randomness — so results
are reproducible, cacheable, and testable.

Pipeline (orchestration):

1. Parse + normalize the URL.
2. Fetch repo metadata; reject private repos (even if a token could see them).
3. Resolve the requested branch (or default) to a commit + tree SHA.
4. Look up ``(normalized_url, commit_sha)`` in the cache. **Hit ⇒ return it
   without fetching the tree or any files** (the expensive part).
5. Miss ⇒ fetch the recursive tree (reject if truncated), scope-filter, score
   entries, fetch a bounded set of entry-point files to sharpen their
   rationale, assemble the payload, persist, and return ``cached: False``.

Heuristics (scoring): every blob is classified into one of eight ordered
categories (overview → setup → entry points → routes → domain → frontend →
tests → scripts). Selection and ordering use a fully deterministic tie-break:
score desc, category priority asc, depth asc, path asc.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy.exc import IntegrityError

from ..models import RepositoryAnalysis, db
from .exceptions import not_found_error, tree_truncated_error
from .github_repository_client import (
    BranchRef,
    RepositoryMetadata,
    TreeEntry,
    TreeResult,
)
from .repository_url import ParsedRepositoryUrl, parse_repository_url

logger = logging.getLogger(__name__)


class GitHubClient(Protocol):
    """Structural type for the GitHub access surface the analyzer needs."""

    def get_repository_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        ...

    def get_branch(self, owner: str, repo: str, branch: str) -> BranchRef:
        ...

    def get_tree(self, owner: str, repo: str, tree_sha: str) -> TreeResult:
        ...

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: str,
    ) -> str | None:
        ...


# --- Heuristic configuration ------------------------------------------------

# Directories whose contents never teach architecture; skipped entirely.
IGNORED_DIRS = frozenset({
    '.git', 'node_modules', 'dist', 'build', 'coverage', '.venv', 'venv',
    'vendor', '__pycache__', '.mypy_cache', '.pytest_cache', '.tox', '.cache',
    '.next', '.nuxt', 'out', 'target',
})

# Lockfiles are *setup clues* but we never fetch their (huge, low-signal) bodies.
LOCKFILES = frozenset({
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock',
    'Pipfile.lock', 'Cargo.lock', 'composer.lock', 'go.sum',
})

# Output budgets (counts), per spec.
MAX_KEY_DIRS = 8
MAX_KEY_FILES = 12
MAX_READING_STEPS = 8
MAX_REFLECTION_PROMPTS = 6


@dataclass(frozen=True)
class Category:
    id: str
    priority: int
    title: str
    summary: str
    reason: str


# Ordered by priority (index). Lower priority value = read earlier / rank higher.
CATEGORIES: list[Category] = [
    Category(
        'overview', 0, 'Get the lay of the land',
        'Start here: prose docs explain the purpose and shape of the project '
        'before you read any code.',
        'Project overview documentation — read this first for context.',
    ),
    Category(
        'setup', 1, 'Understand how it is built and run',
        'Configuration and dependency manifests reveal the language, '
        'frameworks, and how the project is installed and run.',
        'Build/dependency configuration — shows the stack and how to run it.',
    ),
    Category(
        'entry-points', 2, 'Start with the entry points',
        'Entry points define where execution begins and how the pieces are '
        'wired together.',
        'Likely program entry point — execution starts around here.',
    ),
    Category(
        'routes', 3, 'Follow the request/flow layer',
        'Routes, views, and controllers map external requests to behavior — a '
        'fast way to see what the app actually does.',
        'Routing/controller layer — maps inputs to behavior.',
    ),
    Category(
        'domain', 4, 'Learn the domain and data',
        'Models, schemas, and migrations describe the core data the system is '
        'built around.',
        'Domain/data definition — the nouns the system manipulates.',
    ),
    Category(
        'frontend', 5, 'Explore the frontend roots',
        'Frontend entry modules and components show how the UI is assembled '
        'and hydrated.',
        'Frontend root/component — where the UI is composed.',
    ),
    Category(
        'tests', 6, 'Read tests as executable documentation',
        'Tests demonstrate intended behavior and edge cases more concretely '
        'than prose.',
        'Test coverage — shows intended behavior by example.',
    ),
    Category(
        'scripts', 7, 'Skim the tooling and scripts',
        'Scripts and task runners capture the common developer workflows '
        '(setup, test, deploy).',
        'Developer tooling/script — common project workflows.',
    ),
]

_CATEGORY_BY_ID = {c.id: c for c in CATEGORIES}


def _basename(path: str) -> str:
    return path.rsplit('/', 1)[-1]


def _classify(path: str) -> str | None:
    """Return the category id for a blob ``path``, or ``None`` to ignore it."""
    name = _basename(path)
    lower = path.lower()
    segments = path.split('/')

    # Overview docs.
    if name.lower().startswith('readme') or name.lower().startswith('contributing'):
        return 'overview'
    if 'docs' in segments or 'doc' in segments:
        if name.lower().endswith(('.md', '.rst', '.txt')):
            return 'overview'

    # Tests (checked early so e.g. test_*.py never reads as an entry point).
    if (
        'tests' in segments or 'test' in segments or 'e2e' in segments
        or '__tests__' in segments or name.startswith('test_')
        or name.endswith(('_test.py',))
        or '.test.' in name or '.spec.' in name
        or 'idle_test' in segments
    ):
        return 'tests'

    # Setup / config / dependency manifests.
    setup_names = {
        'package.json', 'pyproject.toml', 'setup.py', 'setup.cfg', 'gemfile',
        'go.mod', 'cargo.toml', 'dockerfile', 'makefile', 'tsconfig.json',
        'vite.config.ts', 'pytest.ini', '.flake8', 'tox.ini', 'composer.json',
    }
    if name.lower() in setup_names or name in LOCKFILES:
        return 'setup'
    if name.lower().startswith('requirements') and name.lower().endswith('.txt'):
        return 'setup'
    if '.github' in segments and 'workflows' in segments:
        return 'setup'
    if name.lower() in ('.env.example', 'procfile'):
        return 'setup'

    # Routes / controllers / views.
    if {'routes', 'controllers', 'views'} & set(segments):
        return 'routes'

    # Domain / data.
    if {'models', 'schemas', 'db', 'repositories', 'migrations', 'entities'} & set(segments):
        return 'domain'

    # Frontend roots / components / pages.
    if name in ('main.ts', 'main.tsx', 'main.js', 'index.ts', 'index.tsx', 'index.jsx'):
        if 'src' in segments or 'frontend' in segments or len(segments) <= 2:
            return 'frontend'
    if {'components', 'pages', 'islands'} & set(segments):
        return 'frontend'

    # Scripts / tooling.
    if {'script', 'scripts', 'bin'} & set(segments):
        return 'scripts'

    # Entry points (after the more specific buckets above).
    entry_basenames = {
        'main.py', 'main.go', 'main.rs', 'app.py', 'server.py', 'server.js',
        'server.ts', 'manage.py', 'index.js', 'wsgi.py', 'asgi.py', '__main__.py',
        'idle.py', 'cli.py',
    }
    if name.lower() in entry_basenames:
        return 'entry-points'
    if name == '__init__.py' and segments[:2] == ['src', 'app']:
        return 'entry-points'
    if lower.endswith('/app.py') or lower.endswith('/server.ts'):
        return 'entry-points'

    return None


@dataclass(frozen=True)
class ScoredFile:
    path: str
    category: str
    score: int
    depth: int

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        priority = _CATEGORY_BY_ID[self.category].priority
        # score desc, category priority asc, depth asc, path asc.
        return (-self.score, priority, self.depth, self.path)


def _is_ignored(path: str) -> bool:
    return bool(IGNORED_DIRS & set(path.split('/')))


def _scope_filter(entries: list[TreeEntry], scope_path: str) -> list[TreeEntry]:
    if not scope_path:
        return entries
    prefix = scope_path + '/'
    return [
        e for e in entries
        if e.path == scope_path or e.path.startswith(prefix)
    ]


def _score_entries(entries: list[TreeEntry], scope_path: str) -> list[ScoredFile]:
    scored: list[ScoredFile] = []
    scope_depth = scope_path.count('/') + 1 if scope_path else 0
    for entry in entries:
        if entry.type != 'blob':
            continue
        if _is_ignored(entry.path):
            continue
        category = _classify(entry.path)
        if category is None:
            continue
        priority = _CATEGORY_BY_ID[category].priority
        # Base score by category importance; shallower files get a small bump.
        depth = max(entry.path.count('/') - scope_depth, 0)
        score = (len(CATEGORIES) - priority) * 100 - depth
        scored.append(ScoredFile(entry.path, category, score, depth))
    scored.sort(key=lambda s: s.sort_key)
    return scored


def _blob_url(owner: str, repo: str, commit_sha: str, path: str) -> str:
    encoded = '/'.join(_quote(seg) for seg in path.split('/'))
    return f'https://github.com/{owner}/{repo}/blob/{commit_sha}/{encoded}'


def _quote(segment: str) -> str:
    # Minimal path-segment encoding; tree paths are already URL-safe-ish but
    # spaces and a few characters must be escaped for valid blob links.
    from urllib.parse import quote
    return quote(segment, safe='')


def _refine_entry_reason(content: str | None, default_reason: str) -> str:
    """Sharpen an entry-point rationale using cheap content signals."""
    if not content:
        return default_reason
    if "__name__ == '__main__'" in content or '__name__ == "__main__"' in content:
        return 'Runnable entry point: executes when run as a script.'
    if 'def main(' in content or 'func main(' in content:
        return 'Defines a main() function — a primary entry point.'
    if 'create_app' in content or 'Flask(' in content:
        return 'Application factory / framework bootstrap.'
    return default_reason


def _build_sections(
    scored: list[ScoredFile],
    key_files: list[ScoredFile],
    owner: str,
    repo: str,
    commit_sha: str,
    entry_reasons: dict[str, str],
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for category in CATEGORIES:
        members = [f for f in key_files if f.category == category.id]
        if not members:
            continue
        items = [
            {
                'path': f.path,
                'reason': entry_reasons.get(f.path, category.reason),
                'url': _blob_url(owner, repo, commit_sha, f.path),
            }
            for f in members
        ]
        sections.append({
            'id': category.id,
            'title': category.title,
            'summary': category.summary,
            'items': items,
        })
    return sections


def _build_reading_order(key_files: list[ScoredFile]) -> list[dict[str, Any]]:
    goals = {
        'overview': 'Understand the project purpose and how it is organized.',
        'setup': 'Identify the language, frameworks, and how to run it.',
        'entry-points': 'Find where execution begins and trace the wiring.',
        'routes': 'See how inputs map to behavior across the app.',
        'domain': 'Learn the core data structures the system revolves around.',
        'frontend': 'Understand how the UI is composed and hydrated.',
        'tests': 'Confirm intended behavior and discover edge cases.',
        'scripts': 'Learn the common developer workflows.',
    }
    steps: list[dict[str, Any]] = []
    for category in CATEGORIES:
        members = [f.path for f in key_files if f.category == category.id]
        if not members:
            continue
        steps.append({
            'step': len(steps) + 1,
            'title': category.title,
            'paths': members[:3],
            'goal': goals.get(category.id, ''),
        })
        if len(steps) >= MAX_READING_STEPS:
            break
    return steps


def _build_reflection_prompts(
    present_categories: set[str], display_name: str,
) -> list[str]:
    candidates: list[tuple[str, str]] = [
        ('overview', f'In one sentence, what problem does {display_name} solve?'),
        ('entry-points', 'Which file starts execution, and what does it set up first?'),
        ('routes', 'How does an external request travel through the code to a response?'),
        ('domain', 'What are the core data types, and how do they relate?'),
        ('frontend', 'How is the UI mounted, and where does its data come from?'),
        ('tests', 'Which behaviors are tested, and which look risky or untested?'),
        ('setup', 'What would you run first to get this project working locally?'),
    ]
    prompts = [text for cat, text in candidates if cat in present_categories]
    if not prompts:
        prompts = ['What is the smallest change you could make and verify here?']
    return prompts[:MAX_REFLECTION_PROMPTS]


def _build_key_directories(scored: list[ScoredFile]) -> list[str]:
    """Top directories ranked by aggregate file importance, then path."""
    totals: dict[str, int] = {}
    for f in scored:
        if '/' not in f.path:
            continue
        directory = f.path.rsplit('/', 1)[0]
        totals[directory] = totals.get(directory, 0) + f.score
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return [d for d, _ in ranked[:MAX_KEY_DIRS]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class RepositoryAnalyzer:
    """Orchestrates URL parsing, GitHub access, heuristics, and caching."""

    def __init__(self, client: GitHubClient, *, max_files: int) -> None:
        self._client = client
        self._max_files = max_files

    def analyze(self, repository_url: str) -> tuple[dict[str, Any], bool]:
        """Return ``(payload, cached)`` for ``repository_url``."""
        parsed = parse_repository_url(repository_url)

        metadata = self._client.get_repository_metadata(parsed.owner, parsed.repo)
        if metadata.private:
            # Never analyze private repos, even if a token could read them.
            raise not_found_error()

        requested_ref = parsed.requested_ref or metadata.default_branch
        branch = self._client.get_branch(metadata.owner, metadata.repo, requested_ref)

        normalized_url = parsed.normalized_url

        cached_row = (
            db.session.query(RepositoryAnalysis)
            .filter_by(normalized_repo_url=normalized_url, commit_sha=branch.commit_sha)
            .first()
        )
        if cached_row is not None:
            return dict(cached_row.result_json), True

        payload = self._generate(parsed, metadata, branch)
        row, created = self._persist(parsed, metadata, branch, normalized_url, payload)
        # ``created`` is False on a duplicate-insert race: another request won;
        # serve their row as a cache hit.
        return dict(row.result_json), (not created)

    # -- generation -------------------------------------------------------

    def _generate(
        self,
        parsed: ParsedRepositoryUrl,
        metadata: RepositoryMetadata,
        branch: BranchRef,
    ) -> dict[str, Any]:
        tree = self._client.get_tree(metadata.owner, metadata.repo, branch.tree_sha)
        if tree.truncated:
            raise tree_truncated_error()

        scoped = _scope_filter(tree.entries, parsed.scope_path)
        if parsed.scope_path and not scoped:
            # The requested subdirectory does not exist in this tree.
            raise not_found_error()

        scored = _score_entries(scoped, parsed.scope_path)
        key_files = scored[:MAX_KEY_FILES]

        # Fetch a bounded set of entry-point files to sharpen their rationale.
        entry_reasons: dict[str, str] = {}
        entry_candidates = [f for f in key_files if f.category == 'entry-points']
        for f in entry_candidates[: self._max_files]:
            content = self._client.get_file_content(
                metadata.owner, metadata.repo, f.path, branch.commit_sha,
            )
            entry_reasons[f.path] = _refine_entry_reason(
                content, _CATEGORY_BY_ID['entry-points'].reason,
            )

        present = {f.category for f in key_files}
        display_name = self._display_name(parsed, metadata)

        analysis_id = str(uuid.uuid4())
        return {
            'id': analysis_id,
            'repository': {
                'owner': metadata.owner,
                'repo': metadata.repo,
                'displayName': display_name,
                'normalizedUrl': parsed.normalized_url,
                'htmlUrl': metadata.html_url,
                'defaultBranch': metadata.default_branch,
                'requestedRef': parsed.requested_ref or metadata.default_branch,
                'scopePath': parsed.scope_path,
                'commitSha': branch.commit_sha,
                'description': metadata.description,
                'language': metadata.language,
            },
            'keyDirectories': _build_key_directories(scored),
            'sections': _build_sections(
                scored, key_files, metadata.owner, metadata.repo,
                branch.commit_sha, entry_reasons,
            ),
            'readingOrder': _build_reading_order(key_files),
            'reflectionPrompts': _build_reflection_prompts(present, display_name),
            'createdAt': _now_iso(),
        }

    @staticmethod
    def _display_name(
        parsed: ParsedRepositoryUrl, metadata: RepositoryMetadata,
    ) -> str:
        base = f'{metadata.owner}/{metadata.repo}'
        if parsed.scope_path:
            return f'{base}/{parsed.scope_path}'
        return base

    # -- persistence ------------------------------------------------------

    def _persist(
        self,
        parsed: ParsedRepositoryUrl,
        metadata: RepositoryMetadata,
        branch: BranchRef,
        normalized_url: str,
        payload: dict[str, Any],
    ) -> tuple[RepositoryAnalysis, bool]:
        row = RepositoryAnalysis(
            id=str(payload['id']),
            normalized_repo_url=normalized_url,
            requested_ref=parsed.requested_ref or metadata.default_branch,
            scope_path=parsed.scope_path,
            owner=metadata.owner,
            repo=metadata.repo,
            default_branch=metadata.default_branch,
            commit_sha=branch.commit_sha,
            result_json=payload,
        )
        db.session.add(row)
        try:
            db.session.commit()
            return row, True
        except IntegrityError:
            # Concurrent duplicate submission: another request inserted the same
            # (normalized_url, commit_sha) first. Roll back and serve theirs.
            db.session.rollback()
            existing = (
                db.session.query(RepositoryAnalysis)
                .filter_by(normalized_repo_url=normalized_url, commit_sha=branch.commit_sha)
                .first()
            )
            if existing is None:  # pragma: no cover - extremely unlikely
                raise
            return existing, False


def analyze_repository(
    repository_url: str, client: GitHubClient, *, max_files: int = 25,
) -> tuple[dict[str, Any], bool]:
    """Convenience wrapper: build an analyzer and run one analysis."""
    return RepositoryAnalyzer(client, max_files=max_files).analyze(repository_url)
