"""Parse and normalize public GitHub repository URLs for the /learn feature.

We accept exactly two human-pasteable shapes and nothing else:

* a repository root:    ``https://github.com/{owner}/{repo}`` (optional ``.git``)
* a scoped tree URL:    ``https://github.com/{owner}/{repo}/tree/{branch}/{path}``

Everything else — ``http://``, SSH, other hosts, ``/blob``, ``/issues``,
``/pull``, ``/compare``, query strings, fragments, slash-containing branches —
is rejected with a single actionable message. Being strict here keeps the
downstream GitHub client and analyzer simple and prevents us from constructing
ambiguous API calls.

``parse_repository_url`` returns a :class:`ParsedRepositoryUrl`. The cache key
(``normalized_url``) lowercases owner/repo (GitHub treats them
case-insensitively) but preserves the scope path verbatim, while ``owner`` and
``repo`` keep the user-provided casing as a starting point — the analyzer later
overrides display casing with canonical values from GitHub metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .exceptions import invalid_url_error

# Owner/repo: letters, digits, hyphen, underscore, dot. (GitHub is stricter than
# this in places, but this safely excludes slashes and path traversal.)
_SEGMENT_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


@dataclass(frozen=True)
class ParsedRepositoryUrl:
    """A validated GitHub target.

    Attributes:
        owner: Owner segment as parsed (display casing refined later).
        repo: Repo segment as parsed, ``.git`` stripped.
        requested_ref: Branch from a ``/tree/`` URL, or ``None`` for root URLs
            (the analyzer falls back to the repo's default branch).
        scope_path: Subdirectory path from a tree URL, or ``""`` for root URLs.
        normalized_url: Canonical cache-key URL.
    """

    owner: str
    repo: str
    requested_ref: str | None
    scope_path: str

    @property
    def normalized_url(self) -> str:
        owner = self.owner.lower()
        repo = self.repo.lower()
        base = f'https://github.com/{owner}/{repo}'
        if self.requested_ref and self.scope_path:
            return f'{base}/tree/{self.requested_ref}/{self.scope_path}'
        return base


def _reject() -> None:
    raise invalid_url_error()


def parse_repository_url(raw_url: str) -> ParsedRepositoryUrl:
    """Validate ``raw_url`` and return a :class:`ParsedRepositoryUrl`.

    Raises:
        AnalysisError: (code ``invalid_repository_url``, status 400) for any
            URL that is not a supported public GitHub root or tree URL.
    """
    if not isinstance(raw_url, str):
        _reject()
    url = raw_url.strip()
    if not url:
        _reject()

    parts = urlsplit(url)

    # Only https://github.com, no credentials, query, or fragment.
    if parts.scheme != 'https':
        _reject()
    if parts.netloc.lower() != 'github.com':
        _reject()
    if parts.query or parts.fragment or parts.username or parts.password:
        _reject()

    # Split path, dropping the leading slash and any trailing slash.
    segments = [s for s in parts.path.split('/') if s != '']
    if len(segments) < 2:
        _reject()

    owner, repo = segments[0], segments[1]
    if repo.endswith('.git'):
        repo = repo[:-len('.git')]

    if not _SEGMENT_RE.match(owner) or not _SEGMENT_RE.match(repo):
        _reject()

    rest = segments[2:]

    if not rest:
        # Plain root repository URL.
        return ParsedRepositoryUrl(owner=owner, repo=repo, requested_ref=None, scope_path='')

    # The only supported extra path is /tree/{branch}/{path...}. ``.git`` is
    # only valid on a bare root URL, never on a tree URL.
    if rest[0] != 'tree':
        _reject()
    if segments[1].endswith('.git'):
        # .git suffix is only allowed for root URLs.
        _reject()

    tree_rest = rest[1:]
    # Need a branch AND at least one path segment.
    if len(tree_rest) < 2:
        _reject()

    branch = tree_rest[0]
    path_segments = tree_rest[1:]

    # MVP: single-segment branch only; slashes in branches are ambiguous.
    if not _SEGMENT_RE.match(branch):
        _reject()

    for seg in path_segments:
        # Path segments may contain dots/dashes/underscores; reject traversal
        # and empty pieces (already filtered) for safety.
        if seg in ('.', '..') or not seg:
            _reject()

    scope_path = '/'.join(path_segments)
    return ParsedRepositoryUrl(
        owner=owner, repo=repo, requested_ref=branch, scope_path=scope_path,
    )
