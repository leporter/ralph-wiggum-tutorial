"""Unit tests for GitHub repository URL parsing/normalization.

Why these matter: the parser is the security/robustness gate for the whole
feature. Accepting only well-formed public GitHub root and tree URLs keeps the
downstream client from constructing ambiguous API calls, and the normalization
rules are what make the cache key correct (case-insensitive owner/repo, exact
scope path). Each rejection below maps to a real user paste we must refuse.
"""
from __future__ import annotations

import pytest

from app.services.exceptions import AnalysisError
from app.services.repository_url import parse_repository_url


class TestValidUrls:
    def test_plain_root(self) -> None:
        parsed = parse_repository_url('https://github.com/python/cpython')
        assert parsed.owner == 'python'
        assert parsed.repo == 'cpython'
        assert parsed.requested_ref is None
        assert parsed.scope_path == ''
        assert parsed.normalized_url == 'https://github.com/python/cpython'

    def test_trailing_slash(self) -> None:
        parsed = parse_repository_url('https://github.com/python/cpython/')
        assert parsed.normalized_url == 'https://github.com/python/cpython'

    def test_git_suffix_on_root(self) -> None:
        parsed = parse_repository_url('https://github.com/python/cpython.git')
        assert parsed.repo == 'cpython'
        assert parsed.normalized_url == 'https://github.com/python/cpython'

    def test_case_is_lowercased_in_cache_key(self) -> None:
        parsed = parse_repository_url('https://github.com/Python/CPython')
        assert parsed.normalized_url == 'https://github.com/python/cpython'

    def test_tree_scope(self) -> None:
        parsed = parse_repository_url(
            'https://github.com/python/cpython/tree/main/Lib/idlelib'
        )
        assert parsed.requested_ref == 'main'
        assert parsed.scope_path == 'Lib/idlelib'
        assert parsed.normalized_url == (
            'https://github.com/python/cpython/tree/main/Lib/idlelib'
        )

    def test_tree_scope_trailing_slash(self) -> None:
        parsed = parse_repository_url(
            'https://github.com/python/cpython/tree/main/Lib/idlelib/'
        )
        assert parsed.scope_path == 'Lib/idlelib'


class TestInvalidUrls:
    @pytest.mark.parametrize('url', [
        'http://github.com/python/cpython',          # not https
        'git@github.com:python/cpython.git',         # ssh
        'https://gitlab.com/python/cpython',         # wrong host
        'https://github.enterprise.com/o/r',         # enterprise host
        'https://github.com/python',                 # missing repo
        'https://github.com/',                       # empty
        'https://github.com/python/cpython?tab=x',   # query string
        'https://github.com/python/cpython#frag',    # fragment
        'https://github.com/python/cpython/blob/main/x.py',   # blob
        'https://github.com/python/cpython/issues/1',         # issues
        'https://github.com/python/cpython/pull/1',           # pull
        'https://github.com/python/cpython/compare/a...b',    # compare
        'https://github.com/python/cpython/tree/main',        # tree w/o path
        'https://github.com/python/cpython.git/tree/main/Lib',  # .git on tree
        '',
        'not a url',
    ])
    def test_rejected(self, url: str) -> None:
        with pytest.raises(AnalysisError) as exc:
            parse_repository_url(url)
        assert exc.value.code == 'invalid_repository_url'
        assert exc.value.status == 400
