"""Unit tests for the real GitHub client, mocked at the HTTP layer.

Why mock the transport instead of the network: these tests pin the client's
*translation* of GitHub responses into our user-facing error contract — private
→ not-found, 403 with no remaining quota → rate-limited, timeout → upstream,
truncated handling lives in the analyzer but binary/oversized skipping lives
here. They must be hermetic and fast, so we inject a fake ``requests.Session``.
"""
from __future__ import annotations

import base64
from typing import Any

import pytest
import requests

from app.services.exceptions import AnalysisError
from app.services.github_repository_client import GitHubRepositoryClient


class FakeResponse:
    def __init__(self, status_code: int, json_data: Any = None, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json


class FakeSession:
    """Returns queued responses (or raises queued exceptions) per GET call."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, **_: Any) -> Any:
        self.calls.append(url)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(session: FakeSession, **overrides: Any) -> GitHubRepositoryClient:
    kwargs: dict[str, Any] = dict(
        api_url='https://api.github.com',
        api_version='2022-11-28',
        token=None,
        timeout=5,
        max_requests=35,
        max_file_bytes=100_000,
        session=session,
    )
    kwargs.update(overrides)
    return GitHubRepositoryClient(**kwargs)


def test_metadata_success() -> None:
    session = FakeSession([
        FakeResponse(200, {
            'owner': {'login': 'python'}, 'name': 'cpython', 'private': False,
            'default_branch': 'main', 'html_url': 'https://github.com/python/cpython',
            'description': 'The Python programming language', 'language': 'Python',
        }),
    ])
    meta = make_client(session).get_repository_metadata('python', 'cpython')
    assert meta.private is False
    assert meta.default_branch == 'main'
    assert meta.language == 'Python'


def test_metadata_missing_is_not_found() -> None:
    session = FakeSession([FakeResponse(404, {})])
    with pytest.raises(AnalysisError) as exc:
        make_client(session).get_repository_metadata('python', 'nope')
    assert exc.value.status == 404
    assert exc.value.message == 'Repository not found or not public.'


def test_private_repo_reported_via_metadata_flag() -> None:
    session = FakeSession([
        FakeResponse(200, {
            'owner': {'login': 'acme'}, 'name': 'secret', 'private': True,
            'default_branch': 'main',
        }),
    ])
    meta = make_client(session).get_repository_metadata('acme', 'secret')
    # The client surfaces the flag; the analyzer is responsible for rejecting.
    assert meta.private is True


def test_rate_limit_403_zero_remaining() -> None:
    session = FakeSession([
        FakeResponse(403, {}, headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1'}),
    ])
    with pytest.raises(AnalysisError) as exc:
        make_client(session).get_repository_metadata('python', 'cpython')
    assert exc.value.status == 429


def test_rate_limit_429() -> None:
    session = FakeSession([FakeResponse(429, {})])
    with pytest.raises(AnalysisError) as exc:
        make_client(session).get_repository_metadata('python', 'cpython')
    assert exc.value.status == 429


def test_timeout_is_upstream_error() -> None:
    session = FakeSession([requests.exceptions.Timeout('slow')])
    with pytest.raises(AnalysisError) as exc:
        make_client(session).get_repository_metadata('python', 'cpython')
    assert exc.value.status == 502


def test_branch_resolves_shas() -> None:
    session = FakeSession([
        FakeResponse(200, {'commit': {'sha': 'abc', 'commit': {'tree': {'sha': 'tree1'}}}}),
    ])
    ref = make_client(session).get_branch('python', 'cpython', 'main')
    assert ref.commit_sha == 'abc'
    assert ref.tree_sha == 'tree1'


def test_tree_reports_truncated() -> None:
    session = FakeSession([
        FakeResponse(200, {
            'truncated': True,
            'tree': [{'path': 'a.py', 'type': 'blob', 'size': 1}],
        }),
    ])
    result = make_client(session).get_tree('python', 'cpython', 'tree1')
    assert result.truncated is True
    assert result.entries[0].path == 'a.py'


def test_file_content_decodes_text() -> None:
    content = base64.b64encode(b'print("hi")\n').decode()
    session = FakeSession([
        FakeResponse(200, {'encoding': 'base64', 'content': content, 'size': 12}),
    ])
    text = make_client(session).get_file_content('python', 'cpython', 'a.py', 'abc')
    assert text == 'print("hi")\n'


def test_file_content_skips_binary() -> None:
    content = base64.b64encode(b'\x00\x01\x02binary').decode()
    session = FakeSession([
        FakeResponse(200, {'encoding': 'base64', 'content': content, 'size': 8}),
    ])
    text = make_client(session).get_file_content('python', 'cpython', 'a.bin', 'abc')
    assert text is None


def test_file_content_skips_oversized() -> None:
    session = FakeSession([
        FakeResponse(200, {'encoding': 'base64', 'content': 'x', 'size': 999_999}),
    ])
    text = make_client(session, max_file_bytes=100).get_file_content(
        'python', 'cpython', 'big.py', 'abc',
    )
    assert text is None


def test_request_budget_enforced() -> None:
    session = FakeSession([FakeResponse(200, {}) for _ in range(5)])
    client = make_client(session, max_requests=1)
    client.get_repository_metadata('python', 'cpython')  # consumes the 1 allowed
    with pytest.raises(AnalysisError) as exc:
        client.get_branch('python', 'cpython', 'main')
    assert exc.value.status == 413


def test_no_auth_header_without_token() -> None:
    session = FakeSession([FakeResponse(200, {
        'owner': {'login': 'python'}, 'name': 'cpython', 'private': False,
        'default_branch': 'main',
    })])
    client = make_client(session)
    client.get_repository_metadata('python', 'cpython')
    # Sanity: headers builder omits Authorization when no token configured.
    assert 'Authorization' not in client._headers()  # noqa: SLF001
    client_with_token = make_client(FakeSession([]), token='secret')
    assert client_with_token._headers()['Authorization'] == 'Bearer secret'  # noqa: SLF001
