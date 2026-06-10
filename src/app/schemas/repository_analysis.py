"""Response shape for the /learn analysis API.

The analyzer (``services/repository_analysis``) already emits a payload in the
exact field shape the React island consumes, so this module's job is *not* to
re-validate or transform — that would invite drift between two definitions.
Instead it (a) documents the contract in one place and (b) provides the single
helper that wraps an analysis payload into the top-level
``{"analysis": ..., "cached": ...}`` envelope from Step 1 of the spec.

Keeping this as the one serialization seam means backend and frontend field
names stay aligned with no ad-hoc transforms on either side.
"""
from __future__ import annotations

from typing import Any, TypedDict


class RepositorySummary(TypedDict):
    owner: str
    repo: str
    displayName: str
    normalizedUrl: str
    htmlUrl: str
    defaultBranch: str
    requestedRef: str
    scopePath: str
    commitSha: str
    description: str | None
    language: str | None


class LearningPathItem(TypedDict):
    path: str
    reason: str
    url: str


class LearningPathSection(TypedDict):
    id: str
    title: str
    summary: str
    items: list[LearningPathItem]


class ReadingOrderStep(TypedDict):
    step: int
    title: str
    paths: list[str]
    goal: str


class RepositoryAnalysisPayload(TypedDict):
    id: str
    repository: RepositorySummary
    keyDirectories: list[str]
    sections: list[LearningPathSection]
    readingOrder: list[ReadingOrderStep]
    reflectionPrompts: list[str]
    createdAt: str


def serialize_analysis_response(
    payload: dict[str, Any], *, cached: bool,
) -> dict[str, Any]:
    """Wrap an analysis ``payload`` in the top-level response envelope."""
    return {'analysis': payload, 'cached': cached}
