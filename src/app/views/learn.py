"""Learning-path views: the /learn page, JSON analyze endpoint, saved results.

These routes are deliberately thin. All business logic lives in
``services/`` so it can be unit-tested without a request context; the view's
only jobs are HTTP concerns: parse JSON, build the client from app config, run
the analyzer, and map :class:`AnalysisError` onto the status-code contract.

Routes:
* ``GET  /learn``               — render the form page (island boot props only).
* ``POST /learn/analyze``       — JSON-only; returns the Step-1 response/error.
* ``GET  /learn/<analysis_id>`` — render a saved result via ``initialAnalysis``.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from ..models import RepositoryAnalysis
from ..services.exceptions import AnalysisError, invalid_url_error
from ..services.github_repository_client import build_github_client
from ..services.repository_analysis import analyze_repository
from ..schemas.repository_analysis import serialize_analysis_response

learn_bp = Blueprint('learn', __name__)

ANALYZE_ENDPOINT = '/learn/analyze'


@learn_bp.route('/learn')
def index():  # type: ignore[no-untyped-def]
    """Render the learning-path form page.

    Boot props carry only the analyze endpoint; the island fetches results
    itself so the page stays cacheable and JS-optional up to submission.
    """
    return render_template('learn.html', learn_props={'analyzeEndpoint': ANALYZE_ENDPOINT})


@learn_bp.route('/learn/analyze', methods=['POST'])
def analyze():  # type: ignore[no-untyped-def]
    """JSON-only analysis endpoint returning the Step-1 contract."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'repositoryUrl' not in data:
        err = invalid_url_error('Send JSON like {"repositoryUrl": "https://github.com/owner/repo"}.')
        return jsonify(err.to_dict()), err.status

    repository_url = data.get('repositoryUrl')
    if not isinstance(repository_url, str):
        err = invalid_url_error()
        return jsonify(err.to_dict()), err.status

    client = build_github_client(current_app.config)
    try:
        payload, cached = analyze_repository(
            repository_url,
            client,
            max_files=current_app.config.get('REPOSITORY_ANALYSIS_MAX_FILES', 25),
        )
    except AnalysisError as exc:
        return jsonify(exc.to_dict()), exc.status

    return jsonify(serialize_analysis_response(payload, cached=cached)), 200


@learn_bp.route('/learn/<analysis_id>')
def saved(analysis_id: str):  # type: ignore[no-untyped-def]
    """Render a previously saved analysis from its UUID, or 404."""
    row = RepositoryAnalysis.query.filter_by(id=analysis_id).first()
    if row is None:
        # Let the shared 404 handler do content negotiation.
        raise _not_found()
    props = {
        'analyzeEndpoint': ANALYZE_ENDPOINT,
        'initialAnalysis': row.result_json,
    }
    return render_template('learn.html', learn_props=props)


def _not_found() -> HTTPException:
    from werkzeug.exceptions import NotFound
    return NotFound()
