"""Shared error type for the /learn analysis pipeline.

Every failure mode the student can hit — bad URL, private/missing repo, rate
limit, truncated tree, upstream hiccup — is expressed as an
``AnalysisError`` carrying:

* ``code``    — a stable machine string for the JSON contract (e.g.
  ``"invalid_repository_url"``),
* ``message`` — a user-facing sentence safe to show in the UI (never leaks
  tokens, hosts, or upstream bodies), and
* ``status``  — the HTTP status the view should return.

Centralizing this keeps the view a trivial ``try/except`` and guarantees the
status-code map in the spec (400/404/413/422/429/502) is applied consistently.
"""
from __future__ import annotations


class AnalysisError(Exception):
    """A user-facing, status-mapped failure in the analysis pipeline."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self) -> dict[str, dict[str, str]]:
        """Serialize to the Step-1 error contract: ``{"error": {...}}``."""
        return {'error': {'code': self.code, 'message': self.message}}


# Canonical user-facing message reused for every "can't see this repo" case so
# we never disclose whether a repo is missing vs. private vs. unauthorized.
NOT_FOUND_MESSAGE = 'Repository not found or not public.'


def invalid_url_error(message: str | None = None) -> AnalysisError:
    return AnalysisError(
        code='invalid_repository_url',
        message=message or (
            'Enter a public GitHub repository URL like '
            'https://github.com/owner/repo or '
            'https://github.com/python/cpython/tree/main/Lib/idlelib.'
        ),
        status=400,
    )


def not_found_error() -> AnalysisError:
    return AnalysisError(
        code='repository_not_found',
        message=NOT_FOUND_MESSAGE,
        status=404,
    )


def rate_limited_error() -> AnalysisError:
    return AnalysisError(
        code='rate_limited',
        message=(
            'GitHub API rate limit reached. Try again later, or configure a '
            'GITHUB_TOKEN to raise the limit.'
        ),
        status=429,
    )


def tree_truncated_error() -> AnalysisError:
    return AnalysisError(
        code='tree_truncated',
        message=(
            'This repository is too large to analyze reliably right now. '
            'Try a scoped subdirectory URL like '
            'https://github.com/owner/repo/tree/main/path.'
        ),
        status=422,
    )


def limit_exceeded_error(message: str | None = None) -> AnalysisError:
    return AnalysisError(
        code='limit_exceeded',
        message=message or 'The repository or file exceeds the analysis limits.',
        status=413,
    )


def upstream_error() -> AnalysisError:
    return AnalysisError(
        code='upstream_error',
        message='GitHub returned an unexpected error. Please try again.',
        status=502,
    )
