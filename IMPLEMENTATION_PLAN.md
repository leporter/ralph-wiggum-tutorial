# Implementation Plan — Public GitHub Codebase Learning Path

## Status

> **Overall: COMPLETE — the `/learn` feature is fully implemented, tested, and
> validated (backend 64 tests, frontend 23 tests, e2e 5 tests; mypy/tsc/flake8/
> eslint clean). Space Invaders on `/` remains intact.**

Spec: `specs/20260609-230029-codebase-learning-path-public-github-repos.md`.

## What was delivered (Spec Steps 1–16)

- **Contracts & config (Steps 1–2):** Locked JSON request/response + error
  shapes and status map (400/404/413/422/429/502). Added `requests>=2.32.0`,
  optional `GITHUB_TOKEN`, and all `GITHUB_*` / `REPOSITORY_ANALYSIS_*` /
  `USE_FAKE_GITHUB_CLIENT` config. `TestingConfig` forces the fake client.
- **Vite asset fix (Step 3):** `src/app/vite_manifest.py` resolves `src/main.ts`
  → hashed JS/CSS from the build manifest; `base.html` uses it (dev branch
  preserved). Falls back to legacy names when no manifest. Covered by
  `tests/test_vite_assets.py`.
- **Persistence (Step 4):** `models/repository_analysis.py` (`repository_analyses`,
  UUID PK, unique `(normalized_repo_url, commit_sha)`, URL index, JSON payload).
  Migration `a1b2c3d4e5f6` chained after `f1a2b3c4d5e6`; applied to Postgres.
  Duplicate-insert race handled (catch `IntegrityError` → re-query → cache hit).
- **URL parser (Step 5):** `services/repository_url.py` — strict https/github.com
  root + `/tree/<branch>/<path>` only, single-segment branch, `.git` on root
  only, normalization lowercases owner/repo. `tests/test_repository_url.py`.
- **GitHub client (Step 6):** `services/github_repository_client.py` — budgeted
  `requests` client with timeouts, correct headers, private→not-found, rate-limit
  detection, binary/oversized skipping, no secret logging. Plus the deterministic
  `FakeGitHubRepositoryClient` (CPython/IDLE fixture). `tests/test_github_repository_client.py`.
- **Orchestration + heuristics (Steps 7–8):** `services/repository_analysis.py` —
  8 ordered categories, deterministic tie-break (score↓, category↑, depth↑,
  path↑), ignored dirs, scope filtering, bounded entry-point content fetch for
  sharper reasons, cache lookup before tree/file fetch, blob links with commit
  SHA. Budgets enforced. `tests/test_repository_analysis_service.py`.
- **Routes/templates/schemas (Steps 9–10):** `views/learn.py` (`GET /learn`,
  `POST /learn/analyze` JSON-only, `GET /learn/<id>`), `templates/learn.html`,
  nav in `base.html`, `schemas/repository_analysis.py` (single serialization
  seam + TypedDicts). `tests/test_learn_view.py`.
- **React island (Step 11):** `islands/learn/{LearnCodebaseIsland.tsx,index.tsx,
  types.ts}`, registered in `main.ts`. Form/loading/error/result states, renders
  `initialAnalysis` without refetch, prominent reading order, text-only render
  (no `dangerouslySetInnerHTML`). `frontend/tests/learn/LearnCodebaseIsland.test.tsx`.
- **Fake data + tests + e2e (Steps 12–15):** Fake client wired into Playwright
  via `webServer.env.USE_FAKE_GITHUB_CLIENT`. `e2e/learn.spec.ts` covers submit →
  result → saved URL; game e2e still green.
- **Validation (Step 16):** All suites pass; types and lint clean.

## Notes / follow-ups (out of scope per spec)

- LLM providers, private-repo support, async/background analysis, conversational
  tutoring remain documented follow-ups after this synchronous MVP.
- The analyzer fetches content only for entry-point candidates (to refine
  rationale); excerpts are intentionally not surfaced in the payload, matching
  the locked contract. Revisit if a future step adds excerpt display.
