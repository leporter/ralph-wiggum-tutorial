"""Service tests for heuristic scoring, ordering, caching, and edge cases.

Why these matter: the analyzer is the product. These tests pin the *contract*
guarantees students rely on — deterministic ordering (so results are stable and
cacheable), correct prioritization (README before tests), a real cache hit that
avoids re-fetching the tree/files, safe handling of truncated/private/missing
inputs, and a stable payload shape the island can render without transforms.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.models import RepositoryAnalysis, db
from app.services.exceptions import AnalysisError
from app.services.github_repository_client import (
    BranchRef,
    RepositoryMetadata,
    TreeEntry,
    TreeResult,
)
from app.services.repository_analysis import analyze_repository


class StubClient:
    """Programmable in-memory GitHub client that records call counts."""

    def __init__(
        self,
        *,
        entries: list[TreeEntry],
        private: bool = False,
        truncated: bool = False,
        files: dict[str, str | None] | None = None,
        commit_sha: str = 'commit1',
    ) -> None:
        self._entries = entries
        self._private = private
        self._truncated = truncated
        self._files = files or {}
        self._commit_sha = commit_sha
        self.tree_calls = 0
        self.file_calls = 0
        self.metadata_calls = 0

    def get_repository_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        self.metadata_calls += 1
        return RepositoryMetadata(
            owner=owner, repo=repo, private=self._private, default_branch='main',
            html_url=f'https://github.com/{owner}/{repo}',
            description='desc', language='Python',
        )

    def get_branch(self, owner: str, repo: str, branch: str) -> BranchRef:
        return BranchRef(commit_sha=self._commit_sha, tree_sha='tree1')

    def get_tree(self, owner: str, repo: str, tree_sha: str) -> TreeResult:
        self.tree_calls += 1
        return TreeResult(entries=list(self._entries), truncated=self._truncated)

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str | None:
        self.file_calls += 1
        return self._files.get(path)


def _full_tree() -> list[TreeEntry]:
    return [
        TreeEntry('README.md', 'blob', 100),
        TreeEntry('pyproject.toml', 'blob', 100),
        TreeEntry('src', 'tree'),
        TreeEntry('src/app', 'tree'),
        TreeEntry('src/app/__init__.py', 'blob', 100),
        TreeEntry('src/app/views/home.py', 'blob', 100),
        TreeEntry('src/app/models/user.py', 'blob', 100),
        TreeEntry('tests', 'tree'),
        TreeEntry('tests/test_home.py', 'blob', 100),
        TreeEntry('node_modules', 'tree'),
        TreeEntry('node_modules/lib/index.js', 'blob', 100),
        TreeEntry('script/server', 'blob', 100),
    ]


pytestmark = pytest.mark.usefixtures('app')


class TestScoringAndOrdering:
    def test_readme_ranks_first_and_categories_present(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree())
            payload, cached = analyze_repository('https://github.com/o/r', client)
            assert cached is False
            section_ids = [s['id'] for s in payload['sections']]
            # Overview must come before tests; ignored node_modules excluded.
            assert section_ids[0] == 'overview'
            assert 'tests' in section_ids
            all_paths = [
                item['path'] for s in payload['sections'] for item in s['items']
            ]
            assert not any('node_modules' in p for p in all_paths)

    def test_reading_order_is_deterministic(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            c1 = StubClient(entries=_full_tree())
            c2 = StubClient(entries=list(reversed(_full_tree())))
            p1, _ = analyze_repository('https://github.com/o/r', c1)
            db.session.query(RepositoryAnalysis).delete()
            db.session.commit()
            p2, _ = analyze_repository('https://github.com/o/r', c2)
            order1 = [(s['step'], s['title']) for s in p1['readingOrder']]
            order2 = [(s['step'], s['title']) for s in p2['readingOrder']]
            assert order1 == order2

    def test_blob_links_use_commit_sha(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree(), commit_sha='deadbeef')
            payload, _ = analyze_repository('https://github.com/o/r', client)
            url = payload['sections'][0]['items'][0]['url']
            assert '/blob/deadbeef/' in url


class TestCaching:
    def test_cache_hit_skips_tree_and_files(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree())
            _, cached1 = analyze_repository('https://github.com/o/r', client)
            tree_after_first = client.tree_calls
            file_after_first = client.file_calls
            payload2, cached2 = analyze_repository('https://github.com/o/r', client)
            assert cached1 is False
            assert cached2 is True
            # No additional tree/file fetches on the cached path.
            assert client.tree_calls == tree_after_first
            assert client.file_calls == file_after_first

    def test_new_commit_sha_generates_fresh(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            c1 = StubClient(entries=_full_tree(), commit_sha='sha-A')
            c2 = StubClient(entries=_full_tree(), commit_sha='sha-B')
            p1, cached1 = analyze_repository('https://github.com/o/r', c1)
            p2, cached2 = analyze_repository('https://github.com/o/r', c2)
            assert cached1 is False and cached2 is False
            assert p1['id'] != p2['id']

    def test_duplicate_insert_race_serves_existing(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            # Pre-seed a row for the same (normalized_url, commit_sha) so the
            # analyzer's insert collides and must fall back to the existing row.
            existing = RepositoryAnalysis(
                id='existing-id', normalized_repo_url='https://github.com/o/r',
                requested_ref='main', scope_path='', owner='o', repo='r',
                default_branch='main', commit_sha='commit1',
                result_json={'id': 'existing-id', 'marker': True},
            )
            db.session.add(existing)
            db.session.commit()

            client = StubClient(entries=_full_tree(), commit_sha='commit1')
            payload, cached = analyze_repository('https://github.com/o/r', client)
            # The pre-existing row wins and is served as a cache hit.
            assert cached is True
            assert payload['id'] == 'existing-id'


class TestEdgeCases:
    def test_private_repo_rejected(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree(), private=True)
            with pytest.raises(AnalysisError) as exc:
                analyze_repository('https://github.com/o/r', client)
            assert exc.value.status == 404

    def test_truncated_tree_rejected(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree(), truncated=True)
            with pytest.raises(AnalysisError) as exc:
                analyze_repository('https://github.com/o/r', client)
            assert exc.value.status == 422

    def test_missing_scope_path_is_not_found(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree())
            with pytest.raises(AnalysisError) as exc:
                analyze_repository('https://github.com/o/r/tree/main/does/not/exist', client)
            assert exc.value.status == 404

    def test_sparse_repo_without_readme_or_tests(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            entries = [TreeEntry('main.py', 'blob', 100)]
            client = StubClient(entries=entries)
            payload, _ = analyze_repository('https://github.com/o/r', client)
            ids = [s['id'] for s in payload['sections']]
            assert 'overview' not in ids
            assert 'entry-points' in ids
            # Payload shape stays stable even when categories are missing.
            assert payload['reflectionPrompts']
            assert isinstance(payload['keyDirectories'], list)

    def test_payload_schema_stability(self, app: Any) -> None:
        with app.app_context():
            db.create_all()
            client = StubClient(entries=_full_tree())
            payload, _ = analyze_repository('https://github.com/o/r', client)
            for key in (
                'id', 'repository', 'keyDirectories', 'sections',
                'readingOrder', 'reflectionPrompts', 'createdAt',
            ):
                assert key in payload
            repo = payload['repository']
            for key in (
                'owner', 'repo', 'displayName', 'normalizedUrl', 'htmlUrl',
                'defaultBranch', 'requestedRef', 'scopePath', 'commitSha',
                'description', 'language',
            ):
                assert key in repo
