"""Persisted repository analysis results.

A ``RepositoryAnalysis`` row stores the *derived* learning-path payload for a
single (normalized repository URL, resolved commit SHA) pair. We key on the
commit SHA — not the URL alone — so that:

* re-analyzing the same target after a new commit produces a fresh result
  instead of serving stale guidance, and
* both root-repository and scoped ``/tree/<branch>/<path>`` targets get their
  own stable, cacheable entry.

Only the rendered analysis payload (``result_json``) is stored — never raw
source file contents. The MVP persists *successful* analyses only; failures are
not cached so a transient upstream error never poisons the cache.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class RepositoryAnalysis(db.Model):  # type: ignore[name-defined,misc]
    """A cached, successful learning-path analysis for one repo commit."""

    __tablename__ = 'repository_analyses'
    __table_args__ = (
        # The cache key: a given target at a given commit yields one row.
        UniqueConstraint(
            'normalized_repo_url', 'commit_sha',
            name='uq_repository_analyses_url_commit',
        ),
        # Lookups happen by normalized URL (then narrowed by commit SHA).
        Index('ix_repository_analyses_normalized_repo_url', 'normalized_repo_url'),
    )

    # Unguessable UUID primary key so saved-result URLs are non-sequential.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)

    normalized_repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    requested_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_path: Mapped[str] = mapped_column(String(2048), nullable=False, default='')
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    repo: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)

    # The full serialized learning-path payload returned to the island.
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return (
            f'<RepositoryAnalysis {self.owner}/{self.repo} '
            f'@{self.commit_sha[:8]} id={self.id}>'
        )
