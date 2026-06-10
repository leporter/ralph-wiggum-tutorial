"""GitHub REST client for the /learn analyzer, plus a deterministic fake.

The analyzer talks to GitHub through the small :class:`GitHubRepositoryClient`
surface (metadata → branch → tree → file content). Each method maps upstream
failures onto the user-facing :class:`AnalysisError` codes so the orchestrator
and view never have to interpret raw HTTP.

Design choices worth calling out:

* **Explicit timeouts** on every request (a hung GitHub call must not hang a
  student's request).
* **Private repos are rejected even with a token** — we check ``private`` on
  metadata and refuse, satisfying the "no private repos" guarantee regardless
  of token scopes.
* **No secret leakage** — tokens, the ``Authorization`` header, and full
  response bodies are never logged. We log only method + sanitized path +
  status.
* **Request budget** — the client counts requests and refuses to exceed
  ``REPOSITORY_ANALYSIS_MAX_API_REQUESTS`` so a pathological repo can't fan out
  into unbounded calls.

:class:`FakeGitHubRepositoryClient` implements the same surface from a baked-in
CPython/IDLE fixture so tests and Playwright never touch the network.
"""
from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests

from .exceptions import (
    AnalysisError,
    limit_exceeded_error,
    not_found_error,
    rate_limited_error,
    upstream_error,
)

logger = logging.getLogger(__name__)

_USER_AGENT = 'ralph-wiggum-tutorial-codebase-learning'


@dataclass(frozen=True)
class RepositoryMetadata:
    owner: str
    repo: str
    private: bool
    default_branch: str
    html_url: str
    description: str | None
    language: str | None


@dataclass(frozen=True)
class BranchRef:
    commit_sha: str
    tree_sha: str


@dataclass(frozen=True)
class TreeEntry:
    """One entry from a recursive Git tree.

    ``path`` is repo-root-relative. ``type`` is ``"blob"`` or ``"tree"``.
    ``size`` is the blob byte size (``None`` for trees).
    """

    path: str
    type: str
    size: int | None = None


@dataclass
class TreeResult:
    entries: list[TreeEntry] = field(default_factory=list)
    truncated: bool = False


class GitHubRepositoryClient:
    """Thin, budgeted GitHub REST client used by the analyzer."""

    def __init__(
        self,
        *,
        api_url: str,
        api_version: str,
        token: str | None,
        timeout: int,
        max_requests: int,
        max_file_bytes: int,
        session: requests.Session | None = None,
    ) -> None:
        self._api_url = api_url.rstrip('/')
        self._api_version = api_version
        self._token = token
        self._timeout = timeout
        self._max_requests = max_requests
        self._max_file_bytes = max_file_bytes
        self._session = session or requests.Session()
        self._request_count = 0

    # -- internal helpers -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': self._api_version,
            'User-Agent': _USER_AGENT,
        }
        if self._token:
            headers['Authorization'] = f'Bearer {self._token}'
        return headers

    def _check_budget(self) -> None:
        if self._request_count >= self._max_requests:
            raise limit_exceeded_error(
                'This repository needs more GitHub requests than allowed for a '
                'single analysis. Try a scoped subdirectory URL.'
            )

    def _get(self, path: str) -> requests.Response:
        """Perform a budgeted GET against the GitHub API.

        ``path`` is appended to the API base. Network failures and timeouts are
        translated to upstream errors; rate limits and not-found are detected
        by callers via the returned response where the meaning differs.
        """
        self._check_budget()
        self._request_count += 1
        url = f'{self._api_url}/{path.lstrip("/")}'
        try:
            response = self._session.get(
                url, headers=self._headers(), timeout=self._timeout,
            )
        except requests.exceptions.RequestException as exc:
            # Never include the exception's repr in user output; log sanitized.
            logger.warning('GitHub request failed: GET %s (%s)', path, type(exc).__name__)
            raise upstream_error() from exc

        logger.info('GitHub GET %s -> %s', path, response.status_code)
        self._raise_for_rate_limit(response)
        return response

    @staticmethod
    def _raise_for_rate_limit(response: requests.Response) -> None:
        remaining = response.headers.get('X-RateLimit-Remaining')
        if response.status_code == 429:
            raise rate_limited_error()
        if response.status_code == 403 and remaining == '0':
            raise rate_limited_error()

    # -- public surface ---------------------------------------------------

    def get_repository_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        response = self._get(f'/repos/{owner}/{repo}')
        if response.status_code == 404:
            raise not_found_error()
        if response.status_code != 200:
            raise upstream_error()
        data = response.json()
        return RepositoryMetadata(
            owner=str(data.get('owner', {}).get('login') or owner),
            repo=str(data.get('name') or repo),
            private=bool(data.get('private', False)),
            default_branch=str(data.get('default_branch') or 'main'),
            html_url=str(data.get('html_url') or f'https://github.com/{owner}/{repo}'),
            description=data.get('description'),
            language=data.get('language'),
        )

    def get_branch(self, owner: str, repo: str, branch: str) -> BranchRef:
        response = self._get(f'/repos/{owner}/{repo}/branches/{branch}')
        if response.status_code == 404:
            raise not_found_error()
        if response.status_code != 200:
            raise upstream_error()
        data = response.json()
        commit = data.get('commit', {})
        commit_sha = commit.get('sha')
        tree_sha = commit.get('commit', {}).get('tree', {}).get('sha')
        if not commit_sha or not tree_sha:
            raise upstream_error()
        return BranchRef(commit_sha=str(commit_sha), tree_sha=str(tree_sha))

    def get_tree(self, owner: str, repo: str, tree_sha: str) -> TreeResult:
        response = self._get(
            f'/repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1'
        )
        if response.status_code == 404:
            raise not_found_error()
        if response.status_code != 200:
            raise upstream_error()
        data = response.json()
        entries = [
            TreeEntry(
                path=str(item.get('path', '')),
                type=str(item.get('type', '')),
                size=item.get('size'),
            )
            for item in data.get('tree', [])
            if item.get('path')
        ]
        return TreeResult(entries=entries, truncated=bool(data.get('truncated', False)))

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: str,
    ) -> str | None:
        """Return decoded text for ``path`` at ``ref``, or ``None``.

        Returns ``None`` (rather than raising) when the file is binary,
        undecodable, or exceeds the byte budget — those are "skip this file"
        signals for the analyzer, not request failures.
        """
        encoded_path = '/'.join(
            quote(seg, safe='') for seg in path.split('/')
        )
        response = self._get(
            f'/repos/{owner}/{repo}/contents/{encoded_path}?ref={ref}'
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise upstream_error()
        data = response.json()
        if isinstance(data, list):
            # A directory, not a file.
            return None
        size = data.get('size')
        if isinstance(size, int) and size > self._max_file_bytes:
            return None
        if data.get('encoding') != 'base64' or not data.get('content'):
            return None
        try:
            raw = base64.b64decode(data['content'])
        except (binascii.Error, ValueError):
            return None
        if b'\x00' in raw:
            # Binary file; skip.
            return None
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError:
            return None


# ---------------------------------------------------------------------------
# Fake client for tests and Playwright
# ---------------------------------------------------------------------------

_FIXTURE_OWNER = 'python'
_FIXTURE_REPO = 'cpython'
_FIXTURE_DEFAULT_BRANCH = 'main'
_FIXTURE_COMMIT_SHA = 'fixturecommitsha000000000000000000000001'
_FIXTURE_TREE_SHA = 'fixturetreesha0000000000000000000000000001'

# A representative slice of CPython's IDLE package, enough to exercise every
# heuristic category (overview docs, config, entry points, domain, tests).
_FIXTURE_TREE: list[TreeEntry] = [
    TreeEntry('README.md', 'blob', 1200),
    TreeEntry('setup.py', 'blob', 800),
    TreeEntry('Lib', 'tree'),
    TreeEntry('Lib/idlelib', 'tree'),
    TreeEntry('Lib/idlelib/README.txt', 'blob', 900),
    TreeEntry('Lib/idlelib/idle.py', 'blob', 200),
    TreeEntry('Lib/idlelib/__main__.py', 'blob', 150),
    TreeEntry('Lib/idlelib/pyshell.py', 'blob', 40000),
    TreeEntry('Lib/idlelib/editor.py', 'blob', 50000),
    TreeEntry('Lib/idlelib/config.py', 'blob', 30000),
    TreeEntry('Lib/idlelib/run.py', 'blob', 20000),
    TreeEntry('Lib/idlelib/mainmenu.py', 'blob', 8000),
    TreeEntry('Lib/idlelib/idle_test', 'tree'),
    TreeEntry('Lib/idlelib/idle_test/__init__.py', 'blob', 100),
    TreeEntry('Lib/idlelib/idle_test/test_editor.py', 'blob', 5000),
    TreeEntry('Lib/idlelib/idle_test/test_config.py', 'blob', 6000),
    TreeEntry('Lib/idlelib/icons', 'tree'),
    TreeEntry('Lib/idlelib/icons/idle.ico', 'blob', 4000),
]

_FIXTURE_FILES: dict[str, str | None] = {
    'Lib/idlelib/README.txt': (
        'IDLE is the Python IDE built with the tkinter GUI toolkit.\n'
        'idle.py starts IDLE; editor.py and pyshell.py provide the windows.\n'
    ),
    'Lib/idlelib/idle.py': (
        'import idlelib.pyshell\n'
        "if __name__ == '__main__':\n"
        '    idlelib.pyshell.main()\n'
    ),
    'Lib/idlelib/__main__.py': (
        'import idlelib.pyshell\n'
        'idlelib.pyshell.main()\n'
    ),
    'Lib/idlelib/config.py': '# IdleConf manages IDLE configuration\n',
    'Lib/idlelib/icons/idle.ico': None,  # binary -> skipped
}


class FakeGitHubRepositoryClient:
    """Deterministic in-process client backed by the IDLE fixture.

    Recognizes only the fixture target (``python/cpython`` /
    ``Lib/idlelib``); any other owner/repo behaves like a missing repository so
    tests can also exercise the not-found path without the network.
    """

    def __init__(self, **_: object) -> None:
        self._request_count = 0

    def _is_fixture(self, owner: str, repo: str) -> bool:
        return owner.lower() == _FIXTURE_OWNER and repo.lower() == _FIXTURE_REPO

    def get_repository_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        self._request_count += 1
        if not self._is_fixture(owner, repo):
            raise not_found_error()
        return RepositoryMetadata(
            owner=_FIXTURE_OWNER,
            repo=_FIXTURE_REPO,
            private=False,
            default_branch=_FIXTURE_DEFAULT_BRANCH,
            html_url=f'https://github.com/{_FIXTURE_OWNER}/{_FIXTURE_REPO}',
            description='The Python programming language',
            language='Python',
        )

    def get_branch(self, owner: str, repo: str, branch: str) -> BranchRef:
        self._request_count += 1
        if not self._is_fixture(owner, repo):
            raise not_found_error()
        return BranchRef(commit_sha=_FIXTURE_COMMIT_SHA, tree_sha=_FIXTURE_TREE_SHA)

    def get_tree(self, owner: str, repo: str, tree_sha: str) -> TreeResult:
        self._request_count += 1
        if not self._is_fixture(owner, repo):
            raise not_found_error()
        return TreeResult(entries=list(_FIXTURE_TREE), truncated=False)

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: str,
    ) -> str | None:
        self._request_count += 1
        if not self._is_fixture(owner, repo):
            raise not_found_error()
        return _FIXTURE_FILES.get(path)


def build_github_client(config: object) -> GitHubRepositoryClient | FakeGitHubRepositoryClient:
    """Construct the client implied by Flask ``config``.

    Returns the fake when ``USE_FAKE_GITHUB_CLIENT`` is truthy (tests, E2E),
    otherwise a live :class:`GitHubRepositoryClient`. Accepts any object that
    exposes the config attributes (a Flask ``app.config`` mapping or a plain
    object/namespace).
    """
    def cfg(name: str, default: Any) -> Any:
        if isinstance(config, dict):
            return config.get(name, default)
        return getattr(config, name, default)

    if cfg('USE_FAKE_GITHUB_CLIENT', False):
        return FakeGitHubRepositoryClient()

    token = cfg('GITHUB_TOKEN', None)
    return GitHubRepositoryClient(
        api_url=str(cfg('GITHUB_API_URL', 'https://api.github.com')),
        api_version=str(cfg('GITHUB_API_VERSION', '2022-11-28')),
        token=str(token) if token else None,
        timeout=int(cfg('GITHUB_REQUEST_TIMEOUT_SECONDS', 5)),
        max_requests=int(cfg('REPOSITORY_ANALYSIS_MAX_API_REQUESTS', 35)),
        max_file_bytes=int(cfg('REPOSITORY_ANALYSIS_MAX_FILE_BYTES', 100_000)),
    )


__all__ = [
    'AnalysisError',
    'BranchRef',
    'FakeGitHubRepositoryClient',
    'GitHubRepositoryClient',
    'RepositoryMetadata',
    'TreeEntry',
    'TreeResult',
    'build_github_client',
]
