# Feature: Public GitHub Codebase Learning Path

## Feature Description
Build a web-based learning tool that helps students become familiar with an existing codebase by turning any public GitHub repository URL, including a scoped GitHub tree subdirectory URL, into a guided, multi-step learning path. The first version should analyze repository structure, identify likely entry points and architectural layers, surface key files, and recommend a reading order that teaches students how to orient themselves in an unfamiliar project.

The experience should feel like a structured walkthrough rather than a raw repository summary. Students should visit `/learn`, submit a public GitHub repository URL such as `https://github.com/python/cpython/tree/main/Lib/idlelib`, wait for a bounded synchronous analysis to complete, and then move through sections such as repository overview, architecture clues, important files, test strategy clues, and a suggested sequence for reading the code.

The MVP is deterministic and heuristic-driven. It does **not** require an LLM provider, does **not** analyze private repositories, and does **not** introduce background workers.

## User Story
As a student exploring an unfamiliar repository
I want a generated learning path that explains where to start and what to read next
So that I can build the skill of understanding an existing codebase without feeling lost

## Problem Statement
Students often know how to write new code but struggle to navigate and understand an existing repository. They do not know which files matter most, which entry points define the application flow, or how to read the code in an order that reveals the architecture. The current application offers a Space Invaders demo, but it does not teach repository-orientation skills or analyze external codebases.

## Solution Statement
Add a new `/learn` experience inside the existing Flask + React Islands application. The feature should:

- Validate and normalize public `https://github.com/{owner}/{repo}` repository URLs and scoped `https://github.com/{owner}/{repo}/tree/{branch}/{path}` tree URLs.
- Fetch repository metadata, the requested branch or default-branch commit SHA, recursive tree data, and a small set of selected text files from the GitHub API.
- Reject private repositories even if an optional token can access them.
- Generate a deterministic learning path using clear heuristics for README files, configuration, entry points, routes/views/controllers, domain models, frontend roots, scripts, and tests.
- Persist successful generated analyses by normalized analysis target URL plus branch commit SHA so students can revisit root-repository or subdirectory-scoped results and repeated analyses can use the cache.
- Render the learning path with a React island mounted by the existing island registry.

Use a JSON-first API contract for the React island. Server-rendered pages should mount the island and pass boot props through `data-props`; the island should fetch `/learn/analyze` for new analyses and should render initial analysis data for saved result pages.

## Relevant Files
Use these files to implement the feature:

- `README.md` — Documents the project workflow, tech stack, and `specs/`-driven planning process.
- `AGENTS.md` — Defines validation commands, operational notes, and the Flask + React Islands conventions to follow.
- `.env.example` — Add an optional `GITHUB_TOKEN=` entry and document that it is only used to increase public GitHub API limits.
- `requirements.txt` — Add the backend HTTP client dependency required by the GitHub API client.
- `src/app/config.py` — Add GitHub-related config values such as `GITHUB_TOKEN`, request timeouts, and analysis limits.
- `src/app/__init__.py` — Existing app factory initializes Flask, SQLAlchemy, migrations, errors, and blueprints.
- `src/app/views/__init__.py` — Register the new learning blueprint alongside the existing game blueprint.
- `src/app/views/game.py` — Owns `/`; keep it intact and avoid route conflicts by placing the new experience on `/learn`.
- `src/app/templates/base.html` — Shared shell for navigation and Vite asset loading; it currently uses fixed production asset paths despite hashed Vite output and needs correction.
- `src/app/templates/game.html` — Existing page should keep working after shared layout/navigation changes.
- `src/app/models/base.py` — Existing SQLAlchemy base used for new persisted analysis models.
- `src/app/models/__init__.py` — Export/import new models so `db.create_all()` and Alembic can see them.
- `migrations/versions/*.py` — Existing Alembic migration chain; add a new migration instead of editing previous migrations.
- `frontend/src/main.ts` — Island registry; register the new `learn` island here.
- `frontend/src/islands/game/index.tsx` — Existing island mount pattern to reuse for the learning-path island.
- `frontend/src/types/index.ts` — Shared frontend type location if the learning payload types should be reused outside the island.
- `frontend/tests/setup.ts` — Existing Vitest setup; new component tests should live under `frontend/tests`, not `frontend/src/tests`.
- `e2e/game.spec.ts` — Existing browser tests that must keep passing after adding the new feature.
- `playwright.config.ts` — Defines browser test execution and web server startup for the new end-to-end flow.
- `tests/conftest.py` — Provides Flask test app/client fixtures for backend route and service tests.

### New Files
- `src/app/views/learn.py` — Blueprint for the learning-path form page, analysis JSON endpoint, and saved result page.
- `src/app/templates/learn.html` — Page template that mounts the learning-path React island.
- `src/app/models/repository_analysis.py` — Persisted successful analysis result model keyed by normalized analysis target URL and commit SHA.
- `src/app/services/github_repository_client.py` — GitHub API client for metadata, branch/tree, and file-content fetching with explicit errors and timeouts.
- `src/app/services/repository_analysis.py` — Heuristic analyzer that converts repository data into a structured learning path payload.
- `src/app/services/repository_url.py` — URL parsing and normalization helpers for public GitHub repository URLs.
- `src/app/schemas/repository_analysis.py` — Serialization helpers and response-shape definitions for the learning-path payload.
- `frontend/src/islands/learn/index.tsx` — Island entry for mounting the learning-path experience.
- `frontend/src/islands/learn/LearnCodebaseIsland.tsx` — React UI for URL entry, loading, error states, and multi-step learning-path rendering.
- `frontend/src/islands/learn/types.ts` — Frontend-specific types for analysis requests, responses, and rendered learning-path sections.
- `frontend/tests/learn/LearnCodebaseIsland.test.tsx` — Vitest coverage for URL submission, loading, errors, and rendered steps.
- `tests/test_learn_view.py` — Backend route tests for `/learn`, `/learn/analyze`, validation errors, cached results, and saved results.
- `tests/test_repository_url.py` — Unit tests for repository URL parsing/normalization edge cases.
- `tests/test_github_repository_client.py` — Unit tests with mocked GitHub responses for metadata, tree, file, timeout, private repo, and rate-limit behavior.
- `tests/test_repository_analysis_service.py` — Service tests for heuristic file selection, deterministic ordering, and learning-path generation.
- `e2e/learn.spec.ts` — End-to-end test covering the student flow using deterministic fake GitHub responses, not live GitHub.
- `migrations/versions/<revision>_add_repository_analyses_table.py` — Alembic migration for persisted analysis results.

## Implementation Plan
### Phase 1: Foundation
Add the new `/learn` route, GitHub configuration, production asset fix, repository URL normalization, persistence model, and Alembic migration. Define the API contract and analysis budgets before implementing the analyzer so every downstream component has a stable shape.

Use these MVP budgets unless implementation reveals they are too tight:

- Maximum GitHub API requests per analysis: 35
- Maximum selected files fetched for content inspection: 25
- Maximum fetched file size: 100 KB before base64 decode
- Maximum stored/displayed excerpt length per file: 1,000 characters
- Per-request GitHub timeout: 5 seconds
- Total synchronous analysis target: under 20 seconds

### Phase 2: Core Implementation
Implement the GitHub client, URL parser, cache lookup flow, and heuristic analyzer. The analyzer should transform repository metadata, tree entries, and selected file snippets into a student-oriented learning path with deterministic ordering and explicit reasons for each recommendation.

### Phase 3: Integration
Wire backend routes, templates, React island, fake test-mode GitHub client, and saved result rendering together. Ensure `/` still serves Space Invaders, `/learn` is discoverable, `/learn/analyze` is JSON-only, and `/learn/<analysis_id>` renders a saved result through initial island props.

## Step by Step Tasks
IMPORTANT: Execute every step in order, top to bottom.

### Step 1: Lock the route, API, and MVP contracts
- Keep the existing Space Invaders page on `/`.
- Reserve `/learn` for the learning tool page and `/learn/<analysis_id>` for saved results.
- Use `POST /learn/analyze` as a JSON-only endpoint.
- Do not add custom decorators; follow the existing Flask blueprint route pattern already used in `src/app/views/game.py`.
- Add a separate E2E file early: `e2e/learn.spec.ts`.
- Define the exact request/response contracts:

```json
POST /learn/analyze
Content-Type: application/json

{ "repositoryUrl": "https://github.com/python/cpython/tree/main/Lib/idlelib" }
```

Successful response, HTTP `200`:

```json
{
  "analysis": {
    "id": "uuid-string",
    "repository": {
      "owner": "python",
      "repo": "cpython",
      "displayName": "python/cpython/Lib/idlelib",
      "normalizedUrl": "https://github.com/python/cpython/tree/main/Lib/idlelib",
      "htmlUrl": "https://github.com/python/cpython",
      "defaultBranch": "main",
      "requestedRef": "main",
      "scopePath": "Lib/idlelib",
      "commitSha": "abc123",
      "description": "The Python programming language",
      "language": "Python"
    },
    "sections": [
      {
        "id": "entry-points",
        "title": "Start with the entry points",
        "summary": "Why this step matters.",
        "items": [
          {
            "path": "Lib/idlelib/idle.py",
            "reason": "Likely IDLE startup entry point within the selected scope.",
            "url": "https://github.com/python/cpython/blob/abc123/Lib/idlelib/idle.py"
          }
        ]
      }
    ],
    "readingOrder": [
      {
        "step": 1,
        "title": "Read the README",
        "paths": ["Lib/idlelib/README.txt"],
        "goal": "Understand the selected package purpose and how IDLE is organized."
      }
    ],
    "reflectionPrompts": ["What file starts IDLE inside this package?"],
    "createdAt": "2026-06-09T23:15:44Z"
  },
  "cached": false
}
```

Error response:

```json
{
  "error": {
    "code": "invalid_repository_url",
    "message": "Enter a public GitHub repository URL like https://github.com/owner/repo or https://github.com/python/cpython/tree/main/Lib/idlelib."
  }
}
```

- Use these status codes:
  - `400` for invalid URL or malformed JSON.
  - `404` for missing, private, or inaccessible repositories with the message “Repository not found or not public.”
  - `413` for files or repositories beyond configured limits.
  - `422` for truncated Git trees that cannot be analyzed reliably.
  - `429` for GitHub API rate limits.
  - `502` for other upstream GitHub failures.

### Step 2: Add dependencies and configuration
- Add `requests>=2.32.0` to `requirements.txt` for GitHub API calls.
- Add `GITHUB_TOKEN=` to `.env.example` with a comment that it is optional and only increases public API rate limits.
- Add config values in `src/app/config.py`:
  - `GITHUB_TOKEN`
  - `GITHUB_API_URL = "https://api.github.com"`
  - `GITHUB_API_VERSION = "2022-11-28"`
  - `GITHUB_REQUEST_TIMEOUT_SECONDS = 5`
  - `REPOSITORY_ANALYSIS_MAX_API_REQUESTS = 35`
  - `REPOSITORY_ANALYSIS_MAX_FILES = 25`
  - `REPOSITORY_ANALYSIS_MAX_FILE_BYTES = 100_000`
  - `REPOSITORY_ANALYSIS_MAX_EXCERPT_CHARS = 1_000`
  - `USE_FAKE_GITHUB_CLIENT = False`
- In testing config, allow dependency injection or a config flag so tests and Playwright can use fake GitHub responses without live network calls.

### Step 3: Fix production Vite asset loading
- `frontend/vite.config.ts` emits hashed assets and `manifest.json`, but `src/app/templates/base.html` currently loads fixed `assets/main.css` and `assets/main.js`.
- Implement a Flask helper or template helper that reads the Vite manifest in production/static mode and resolves `src/main.ts` to the hashed JS and CSS files.
- Update `base.html` to use that helper while preserving Vite dev server loading when `VITE_DEV_MODE` is true.
- Add a backend test that production/static mode renders the manifest-resolved asset paths.

### Step 4: Add persistence for successful repository analyses
- Create `src/app/models/repository_analysis.py`.
- Use table name `repository_analyses`.
- Use a UUID string primary key for stable, non-sequential result URLs.
- Store:
  - `id`
  - `normalized_repo_url`
  - `requested_ref`
  - `scope_path`
  - `owner`
  - `repo`
  - `default_branch`
  - `commit_sha`
  - `result_json` as SQLAlchemy `JSON`
  - `created_at`
  - `updated_at`
- Add a unique constraint on `(normalized_repo_url, commit_sha)`.
- Add an index on `normalized_repo_url`.
- Store only derived analysis output, not raw full source file contents.
- Persist only successful completed analyses for MVP.
- Export/import the model from `src/app/models/__init__.py`.
- Create a new Alembic migration that adds the table and constraints.
- Handle concurrent duplicate submissions by catching the unique constraint violation, re-querying the existing row, and returning it as a cache hit.

### Step 5: Implement repository URL parsing and validation
- Create `src/app/services/repository_url.py`.
- Accept only HTTPS GitHub.com repository root URLs and scoped tree URLs:
  - `https://github.com/{owner}/{repo}`
  - `https://github.com/{owner}/{repo}/tree/{branch}/{path}`
  - optional trailing slash
  - optional `.git` suffix on repo for root URLs only
- Owner and repo may contain GitHub-supported path characters: letters, numbers, hyphen, underscore, and dot where applicable.
- Normalize cache keys by lowercasing owner and repo, preserving the requested tree path with normalized slash handling.
- Preserve display owner/repo from GitHub metadata for UI labels.
- For MVP, support tree URLs where `{branch}` is a single path segment, such as `main`; reject branch names with slashes to avoid ambiguous parsing.
- Reject:
  - `http://`
  - SSH URLs
  - GitHub Enterprise or other hosts
  - query strings and fragments
  - unsupported paths such as `/blob/...`, `/issues/...`, `/pull/...`, `/compare/...`, or malformed `/tree/...` URLs without both branch and path
  - empty owner/repo segments
- Add unit tests in `tests/test_repository_url.py` for valid and invalid URL shapes.

### Step 6: Implement the GitHub repository client
- Create `src/app/services/github_repository_client.py`.
- Use `requests` with explicit timeouts.
- Send headers:
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
  - `User-Agent: ralph-wiggum-tutorial-codebase-learning`
  - `Authorization: Bearer <token>` only when `GITHUB_TOKEN` is configured.
- Implement the exact API flow:
  1. `GET /repos/{owner}/{repo}` for metadata.
  2. Reject immediately if `private` is true, even when a token can access it.
  3. Read `default_branch`.
  4. Resolve the requested tree branch from the URL when present; otherwise use `default_branch`.
  5. `GET /repos/{owner}/{repo}/branches/{branch}` and use `commit.commit.tree.sha` plus branch `commit.sha`.
  6. `GET /repos/{owner}/{repo}/git/trees/{tree_sha}?recursive=1`.
  7. Reject if the tree response has `truncated: true`.
  8. If the URL includes a scope path such as `Lib/idlelib`, filter tree entries to files and directories under that scope and reject with `404` if the scope path does not exist.
  9. Fetch selected file contents through the Contents API or Git Blob API after the analyzer chooses candidates.
- Detect rate limits from HTTP `403`/`429`, `X-RateLimit-Remaining: 0`, and `X-RateLimit-Reset`.
- Detect private/missing repositories as “not found or not public.”
- Decode only text files, skip binary/generated files, and enforce byte limits before storing excerpts.
- Do not log tokens, authorization headers, or full response bodies.
- Add tests with mocked responses for success, private repo rejection, rate limit, timeout, upstream error, truncated tree, binary file, and oversized file.

### Step 7: Implement the cache and analysis orchestration flow
- Implement the analysis service flow in `src/app/services/repository_analysis.py`:
  1. Normalize URL.
  2. Fetch metadata.
  3. Reject private repositories.
  4. Fetch requested-branch or default-branch commit SHA and tree SHA.
  5. Query `repository_analyses` by `(normalized_repo_url, commit_sha)`, where the normalized URL includes the scoped tree path when present.
  6. If found, return the stored payload with `cached: true`.
  7. If not found, score tree entries, fetch selected files within budget, generate the learning path, persist it, and return `cached: false`.
- Keep orchestration separate from the Flask route so it is easy to unit test.
- Use typed/domain objects or Pydantic models where helpful, but do not add a new validation package because Pydantic is already present in `requirements.txt`.

### Step 8: Implement deterministic repository heuristics
- Score files using explicit category priority:
  1. overview docs: `README*`, `docs/**`, `CONTRIBUTING*`
  2. setup/config: `package.json`, `pyproject.toml`, `requirements*.txt`, `Gemfile`, `go.mod`, `Cargo.toml`, `Dockerfile`, CI configs
  3. entry points: `main.*`, `app.*`, `server.*`, `manage.py`, `index.ts`, `index.tsx`, `src/app/__init__.py`
  4. routes/controllers/views: `routes/**`, `views/**`, `controllers/**`, Flask/FastAPI/Django route-looking files
  5. domain/data: `models/**`, `schemas/**`, `db/**`, `repositories/**`, migration folders
  6. frontend roots: `frontend/src/main.*`, `src/main.*`, `components/**`, `pages/**`, `app/**`
  7. tests: `tests/**`, `e2e/**`, `*.test.*`, `test_*.py`, `*.spec.*`
  8. scripts/tooling: `script/**`, `scripts/**`, `Makefile`, task runners
- Apply deterministic tie-breaking: score descending, category priority ascending, path depth ascending, path lexicographic ascending.
- Ignore directories such as `.git`, `node_modules`, `dist`, `build`, `coverage`, `.venv`, `vendor`, and generated cache folders.
- Treat lockfiles as setup clues but do not fetch their contents unless needed for language detection.
- Limit output to:
  - 8 key directories
  - 12 key files
  - 8 reading-order steps
  - 6 reflection prompts
- Generate GitHub file links using the exact commit SHA and full repository-relative path: `https://github.com/{owner}/{repo}/blob/{commit_sha}/{encoded_path}`.
- Render arbitrary repository-provided strings as text only; never use `dangerouslySetInnerHTML`.

### Step 9: Add backend routes and templates
- Create `src/app/views/learn.py` with:
  - `GET /learn` — render `learn.html` with props `{ "analyzeEndpoint": "/learn/analyze" }`.
  - `POST /learn/analyze` — JSON-only endpoint that validates input, runs the analysis service, and returns the response contract from Step 1.
  - `GET /learn/<analysis_id>` — look up a saved analysis by UUID and render `learn.html` with `initialAnalysis` in props; return 404 if missing.
- Register the blueprint from `src/app/views/__init__.py`.
- Create `src/app/templates/learn.html` with:

```html
<div
  data-island="learn"
  data-props='{{ learn_props | tojson }}'
></div>
```

- Add a small navigation affordance in `base.html` or the page shell so users can discover `/learn`.
- Keep `game.html` and the existing `game` island behavior unchanged.

### Step 10: Add schemas and frontend types
- Create `src/app/schemas/repository_analysis.py` for response serialization and payload shape documentation.
- Add `frontend/src/islands/learn/types.ts` with:
  - `LearnIslandProps`
  - `RepositoryAnalysisPayload`
  - `RepositorySummary`
  - `LearningPathSection`
  - `LearningPathItem`
  - `ReadingOrderStep`
  - `AnalyzeRepositoryResponse`
  - `AnalyzeRepositoryError`
- Define `LearnIslandProps` as:

```ts
type LearnIslandProps = {
  analyzeEndpoint: string
  initialAnalysis?: RepositoryAnalysisPayload
}
```

- Keep backend and frontend field names aligned so the island can render without ad hoc transformations.

### Step 11: Build the learning-path React island
- Create `frontend/src/islands/learn/LearnCodebaseIsland.tsx`.
- Implement:
  - repository URL form
  - client submission through native `fetch`
  - loading state
  - invalid-input and backend-error states
  - rendering of `initialAnalysis` for saved result pages
  - step-by-step walkthrough sections
  - file links opening GitHub blob URLs
  - visible cached indicator when `cached: true` is returned
- Render the learning path as clear sections optimized for students, not as a single wall of text.
- Make the reading order prominent and include short reasons/goals for each recommended step.
- Use React text rendering only; do not use `dangerouslySetInnerHTML`.
- Register the island in `frontend/src/islands/learn/index.tsx` and `frontend/src/main.ts`.

### Step 12: Add deterministic test-mode GitHub data for E2E
- Do not let Playwright depend on live GitHub or unauthenticated API rate limits.
- Add a fake GitHub client or service fixture that is enabled under testing/E2E config.
- The fake client should recognize the stable public URL `https://github.com/python/cpython/tree/main/Lib/idlelib` and return representative CPython IDLE metadata, tree entries, and file contents without calling live GitHub.
- Configure the app used by Playwright to use the fake client via environment variable or Flask config.
- Keep unit tests for the real GitHub client mocked at the HTTP layer.

### Step 13: Create frontend component tests
- Add `frontend/tests/learn/LearnCodebaseIsland.test.tsx`.
- Verify:
  - valid URL submission posts to the configured endpoint
  - invalid/backend URL errors show an actionable message
  - loading state appears during submission
  - returned sections render in order
  - `initialAnalysis` renders without making a POST
  - file links and reading-order labels are visible
  - no raw HTML from repository-provided strings is executed/rendered as markup

### Step 14: Create backend tests
- Add `tests/test_learn_view.py` covering:
  - `GET /learn` returns 200 and mounts the `learn` island
  - `POST /learn/analyze` rejects malformed JSON
  - invalid repository URLs return `400`
  - GitHub rate-limit errors return `429`
  - public but missing/private repos return `404` with “not found or not public”
  - cached analyses return `cached: true`
  - `GET /learn/<analysis_id>` renders saved analysis props
  - `GET /learn/<missing_uuid>` returns 404
  - `/` still returns the Space Invaders page and `data-island="game"`
- Add `tests/test_repository_analysis_service.py` for:
  - file scoring and prioritization
  - deterministic tie-breaking
  - cache hit avoids tree/file fetching after commit SHA match
  - duplicate insert/race handling
  - oversized/truncated repo behavior
  - missing README/config/test directories
  - result payload schema stability

### Step 15: Create the end-to-end test
- Create `e2e/learn.spec.ts`.
- Use the fake GitHub client/fixture from Step 12.
- Cover the smallest high-value student journey:
  - open `/learn`
  - enter the fixture public GitHub repository URL `https://github.com/python/cpython/tree/main/Lib/idlelib`
  - submit the form
  - verify the page shows the repository overview
  - verify the learning path includes architecture clues, key files, and a reading order
  - verify at least one GitHub file link is present
  - navigate to the saved result URL and verify the same analysis renders from `initialAnalysis`
- Keep the existing `e2e/game.spec.ts` passing.

### Step 16: Run the full validation suite
- Run `script/setup` after dependency/config/migration changes.
- Run `script/test` to validate backend tests and Vitest coverage.
- Run `script/typecheck` to validate Python and TypeScript typing.
- Run `script/lint` to validate style and static checks.
- Run `npx playwright install chromium` if the browser is not already installed in the environment.
- Run `script/test-e2e --reporter=list` or `script/test-e2e` to validate the browser flow and ensure the existing game flow still works.

## Testing Strategy
### Unit Tests
- URL normalization tests for accepted and rejected GitHub URL forms.
- GitHub client tests with mocked responses for repository metadata, branch/tree fetches, file fetches, private repo rejection, rate limits, timeouts, and upstream failures.
- Repository analysis service tests for deterministic scoring, ignored directories, binary/generated files, cache hits, duplicate insert handling, and payload shape.
- Flask route tests for `/learn`, `/learn/analyze`, saved-analysis retrieval, error status codes, and continued `/` game behavior.
- React island tests for form submission, loading state, successful rendering, saved initial analysis rendering, user-visible errors, and HTML injection safety.

### Edge Cases
- Repository URL includes trailing slash or `.git` suffix.
- Repository URL includes query strings, fragments, unsupported subpaths, SSH syntax, or non-GitHub hosts.
- Repository URL targets a supported GitHub tree subdirectory such as `https://github.com/python/cpython/tree/main/Lib/idlelib`.
- Repository URL targets a malformed or missing tree subdirectory.
- Repository does not exist, is private, or is not publicly accessible.
- Optional `GITHUB_TOKEN` has private scopes; app must still reject `private: true`.
- GitHub API rate limit is exceeded.
- GitHub request times out or returns an unexpected upstream error.
- Repository tree is truncated because the repo is too large.
- Repository lacks a README, obvious entry point, or tests.
- Repository is mostly binary/generated files.
- Repository uses nested apps or monorepo-style folder layout.
- Same repository is analyzed twice without a new commit SHA.
- A new commit SHA exists and the app must generate a fresh analysis.
- Two requests concurrently analyze the same repo and commit SHA.
- Saved analysis UUID does not exist.

## Acceptance Criteria
- Students can visit `/learn`, submit a public GitHub repository URL, and receive a generated learning path in the web UI.
- The generated path includes, at minimum, repository overview, architecture clues, key files, and a recommended reading order.
- The tool accepts only supported public GitHub repository URLs and shows explicit errors for invalid or unsupported inputs.
- Private repositories are rejected even if the configured token can access them.
- The app does not replace or break the existing Space Invaders homepage on `/`.
- Analyses are persisted under unguessable UUID result URLs and can be revisited.
- The app reuses a stored analysis when the normalized analysis target URL and resolved branch commit SHA have not changed.
- The MVP does not require an LLM provider or private-repository authentication.
- E2E tests use deterministic fake GitHub data and do not depend on live GitHub availability.
- Backend, frontend, and E2E tests cover the new flow and existing tests continue to pass.

## Validation Commands
Execute every command to validate the feature works correctly with zero regressions.

```bash
script/setup
script/test
script/typecheck
script/lint
npx playwright install chromium
script/test-e2e --reporter=list
```

## Notes
- Prefer deterministic heuristics over an LLM for the first version so the feature is testable, reproducible, and free from provider setup.
- Store analyses by normalized analysis target URL plus commit SHA instead of URL alone to avoid stale results for both root repositories and scoped tree paths.
- Use GitHub Trees API recursion to keep network usage bounded and predictable.
- Return a user-facing message such as “Repository not found or not public” rather than exposing implementation details.
- Async/background analysis, private-repo support, and conversational tutoring are sensible follow-on iterations after the synchronous MVP is stable.
- If the synchronous analysis regularly exceeds the target budget during implementation, do not add Celery/Redis in this feature; reduce file-fetch budgets first and document async processing as a follow-up.
