"""Backend route tests for the /learn feature.

Why these matter: they lock the HTTP contract the island depends on — the page
mounts the right island, the analyze endpoint returns the documented success
and error shapes with the correct status codes, caching is observable to the
client, saved-result pages render from stored props, and — critically — adding
/learn did not disturb the existing Space Invaders homepage.

The testing config forces the deterministic fake GitHub client, so these tests
never touch the network. The fake recognizes only python/cpython/Lib/idlelib;
any other repo behaves as "not found", which we use to exercise the 404 path.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from flask.testing import FlaskClient

from app.services.exceptions import rate_limited_error

FIXTURE_URL = 'https://github.com/python/cpython/tree/main/Lib/idlelib'


class TestLearnPage:
    def test_get_learn_mounts_island(self, client: FlaskClient[Any]) -> None:
        response = client.get('/learn')
        assert response.status_code == 200
        assert b'data-island="learn"' in response.data

    def test_home_still_serves_game(self, client: FlaskClient[Any]) -> None:
        response = client.get('/')
        assert response.status_code == 200
        assert b'data-island="game"' in response.data


class TestAnalyzeEndpoint:
    def test_valid_url_returns_analysis(self, client: FlaskClient[Any]) -> None:
        response = client.post('/learn/analyze', json={'repositoryUrl': FIXTURE_URL})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['cached'] is False
        assert data['analysis']['repository']['displayName'] == 'python/cpython/Lib/idlelib'
        assert data['analysis']['sections']

    def test_second_call_is_cached(self, client: FlaskClient[Any]) -> None:
        client.post('/learn/analyze', json={'repositoryUrl': FIXTURE_URL})
        response = client.post('/learn/analyze', json={'repositoryUrl': FIXTURE_URL})
        data = json.loads(response.data)
        assert data['cached'] is True

    def test_malformed_json_rejected(self, client: FlaskClient[Any]) -> None:
        response = client.post(
            '/learn/analyze', data='not json',
            content_type='application/json',
        )
        assert response.status_code == 400
        assert json.loads(response.data)['error']['code'] == 'invalid_repository_url'

    def test_missing_field_rejected(self, client: FlaskClient[Any]) -> None:
        response = client.post('/learn/analyze', json={'wrong': 'x'})
        assert response.status_code == 400

    def test_invalid_url_returns_400(self, client: FlaskClient[Any]) -> None:
        response = client.post('/learn/analyze', json={'repositoryUrl': 'http://x'})
        assert response.status_code == 400
        assert json.loads(response.data)['error']['code'] == 'invalid_repository_url'

    def test_missing_or_private_repo_returns_404(self, client: FlaskClient[Any]) -> None:
        response = client.post(
            '/learn/analyze', json={'repositoryUrl': 'https://github.com/o/private-repo'},
        )
        assert response.status_code == 404
        body = json.loads(response.data)
        assert body['error']['message'] == 'Repository not found or not public.'

    def test_rate_limit_returns_429(
        self, client: FlaskClient[Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class RaisingClient:
            def get_repository_metadata(self, *_: Any) -> Any:
                raise rate_limited_error()

        monkeypatch.setattr(
            'app.views.learn.build_github_client', lambda _config: RaisingClient(),
        )
        response = client.post('/learn/analyze', json={'repositoryUrl': FIXTURE_URL})
        assert response.status_code == 429
        assert json.loads(response.data)['error']['code'] == 'rate_limited'


class TestSavedResults:
    def test_saved_result_renders_initial_analysis(self, client: FlaskClient[Any]) -> None:
        created = client.post('/learn/analyze', json={'repositoryUrl': FIXTURE_URL})
        analysis_id = json.loads(created.data)['analysis']['id']

        response = client.get(f'/learn/{analysis_id}')
        assert response.status_code == 200
        assert b'data-island="learn"' in response.data
        # The saved payload is embedded as island boot props.
        assert b'initialAnalysis' in response.data
        assert b'python/cpython/Lib/idlelib' in response.data

    def test_missing_uuid_returns_404(self, client: FlaskClient[Any]) -> None:
        response = client.get('/learn/00000000-0000-0000-0000-000000000000')
        assert response.status_code == 404
