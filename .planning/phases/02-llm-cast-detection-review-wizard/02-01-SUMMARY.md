---
phase: 02-llm-cast-detection-review-wizard
plan: 01
subsystem: api
tags: [sqlmodel, sqlite, fastapi-sse, asyncio, pydantic, xai-sdk]

# Dependency graph
requires:
  - phase: 01-upload-to-audio-spike-tts-rocm-de-risk
    provides: FastAPI app skeleton, config.py Settings pattern, mock/real backend-switch pattern (tts_client.py), bounded-upload helper
provides:
  - SQLModel persistence (Project/Character/Segment tables, SQLite)
  - Shared CastAnalysisResult/CharacterSuggestion/SegmentSuggestion Pydantic contract
  - Background asyncio analysis task (analysis_worker.run_analysis) + in-process SSE progress registry
  - Mock-backed analysis_client.analyze() mirroring tts_client's backend-switch pattern
  - Rewritten POST /projects (201, non-blocking), GET /projects/{id}, GET /projects/{id}/analysis-stream (SSE)
affects: [02-02-epub-ingestion, 02-03-real-grok-analysis, 02-04-wizard-backend, 02-05-frontend-wizard]

# Tech tracking
tech-stack:
  added: [sqlmodel==0.0.39, xai-sdk==1.17.0]
  patterns:
    - "analysis_client.py mirrors tts_client.py's mock/real backend-switch shape (LLM_BACKEND vs TTS_BACKEND)"
    - "Per-project asyncio.Queue registry (analysis_worker._progress_queues) for SSE progress, popped on terminal event"
    - "Per-operation SQLModel Session(engine) — never a shared long-lived session (Pitfall 4)"
    - "FastAPI lifespan context manager (not deprecated on_event) calls init_db() at startup"

key-files:
  created:
    - backend/app/db.py
    - backend/app/models.py
    - backend/app/schemas.py
    - backend/app/analysis_client.py
    - backend/app/token_estimate.py
    - backend/app/analysis_worker.py
    - backend/tests/test_analysis_pipeline.py
  modified:
    - backend/app/config.py
    - backend/app/main.py
    - backend/pyproject.toml
    - backend/uv.lock
    - backend/.gitignore
    - backend/tests/test_e2e.py

key-decisions:
  - "POST /projects fully retires its Phase 1 synchronous chunk->synthesize->join->download shape in favor of the async analysis-first flow — the full per-segment generation pipeline returns in Phase 3 on a (likely different) endpoint, per ROADMAP.md's phase split."
  - "test_e2e.py trimmed to only the upload-validation tests (oversized/non-utf8/empty) that still apply to the new contract; the audio-bytes/chunk-cleanup/tts-4xx/join-failure tests were deleted since they asserted on the now-retired behavior, not a regression."
  - "GET /projects/{id} returns a hand-built dict (not a new Pydantic response model) — CastAnalysisResult's shape (character_name-keyed) doesn't match the persisted ID-keyed shape 1:1, so the API layer resolves character_id -> character_name for the client instead of introducing a second schema this plan doesn't need yet."

requirements-completed: [CAST-01, CAST-03, WIZ-01]

coverage:
  - id: D1
    description: "POST /projects returns 201 with {id, status:'analyzing'} immediately, without blocking on analysis"
    requirement: "CAST-01"
    verification:
      - kind: integration
        ref: "backend/tests/test_analysis_pipeline.py#test_upload_returns_201_analyzing_without_blocking"
        status: pass
    human_judgment: false
  - id: D2
    description: "Background asyncio task persists Character + Segment rows to SQLite; GET /projects/{id} returns ready status with >=1 character and ordered segments"
    requirement: "CAST-03"
    verification:
      - kind: integration
        ref: "backend/tests/test_analysis_pipeline.py#test_analysis_completes_and_is_retrievable_with_ordered_segments"
        status: pass
    human_judgment: false
  - id: D3
    description: "GET /projects/{id}/analysis-stream emits SSE progress then a terminal done event"
    requirement: "WIZ-01"
    verification:
      - kind: integration
        ref: "backend/tests/test_analysis_pipeline.py#test_analysis_stream_emits_progress_then_done"
        status: pass
    human_judgment: false
  - id: D4
    description: "LLM_BACKEND=mock never imports xai_sdk"
    verification:
      - kind: integration
        ref: "backend/tests/test_analysis_pipeline.py#test_mock_backend_never_imports_xai_sdk"
        status: pass
    human_judgment: false
  - id: D5
    description: "Each created Character's voice_instructions is pre-filled from its description (D-16 editable default)"
    verification:
      - kind: integration
        ref: "backend/tests/test_analysis_pipeline.py#test_new_characters_default_voice_instructions_from_description"
        status: pass
    human_judgment: false

duration: ~10min (active work; excludes time paused at the Task 1 package-legitimacy checkpoint)
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 01: Persistence + Mock Analysis Pipeline Summary

**SQLModel/SQLite persistence and an async-worker + native SSE analysis pipeline: upload a .txt, get back a persisted narrator+character cast and ordered voice-tagged segments, streamed live, all against a mock LLM backend with zero xai_sdk import.**

## Performance

- **Duration:** ~10 min active work (plus a human-verify pause at Task 1 for `sqlmodel`/`xai-sdk` package legitimacy)
- **Tasks:** 3 (1 checkpoint + 2 auto/TDD)
- **Files modified:** 12 (7 created, 5 modified)

## Accomplishments
- SQLite persistence via SQLModel (`Project`/`Character`/`Segment`), with `check_same_thread=False` + per-operation `Session` to survive the background-task/request-handler thread boundary (RESEARCH.md Pitfall 4)
- One shared `CastAnalysisResult` Pydantic contract reused as the (future) Grok response shape, the SQLModel persistence shape, and the API response shape
- `POST /projects` now returns 201 immediately and spawns `asyncio.create_task(run_analysis(...))` — no blocking on analysis, no Celery/Redis (CLAUDE.md constraint)
- `analysis_client.analyze()` mirrors `tts_client.py`'s exact mock/real backend-switch shape; the real `xai_sdk` import is lazy and only reached on the non-mock branch, proven never-imported under `LLM_BACKEND=mock` by a dedicated test
- `GET /projects/{id}/analysis-stream` uses FastAPI's native `fastapi.sse.EventSourceResponse`/`ServerSentEvent` (no `sse-starlette` dependency) draining a per-project `asyncio.Queue`, yielding `progress` events then a terminal `done`
- Each persisted `Character.voice_instructions` defaults to its `description` (D-16 editable default)

## Task Commits

1. **Task 1: Confirm SUS-flagged PyPI packages before install** — checkpoint, human approved "sqlmodel and xai-sdk look legitimate" (no commit; gate only)
2. **Task 2: Persistence layer, shared schema, and config extension** — `3bf67e6` (feat)
3. **Task 3: Mock-backed background analysis pipeline + SSE, end-to-end** — `7df937a` (feat)

**Plan metadata:** committed separately by the orchestrator after wave merge (parallel-worktree execution — this agent does not touch STATE.md/ROADMAP.md).

## Files Created/Modified
- `backend/app/db.py` - SQLModel engine (`check_same_thread=False`), `init_db()`, per-call `get_session()`
- `backend/app/models.py` - `Project`/`Character`/`Segment` SQLModel tables, no Phase 3 fields (D-02)
- `backend/app/schemas.py` - `CharacterSuggestion`/`SegmentSuggestion`/`CastAnalysisResult` shared Pydantic contract
- `backend/app/analysis_client.py` - mock-backed `analyze()`, lazy-gated real `xai_sdk` import
- `backend/app/token_estimate.py` - `estimate_tokens()` chars/4 heuristic
- `backend/app/analysis_worker.py` - `run_analysis()` background task + SSE progress queue registry
- `backend/app/main.py` - rewritten `POST /projects` (201, non-blocking), new `GET /projects/{id}`, new `GET /projects/{id}/analysis-stream`, FastAPI `lifespan` calling `init_db()`
- `backend/app/config.py` - `LLM_BACKEND`/`XAI_API_KEY`/`GROK_MODEL`/`DATABASE_URL`/`ANALYSIS_TOKEN_LIMIT` settings
- `backend/pyproject.toml`, `backend/uv.lock` - `sqlmodel`, `xai-sdk` dependencies
- `backend/.gitignore` - excludes `*.db` (SQLite runtime data)
- `backend/tests/test_analysis_pipeline.py` - new end-to-end pipeline test (RED before Task 3's implementation, GREEN after)
- `backend/tests/test_e2e.py` - trimmed to upload-validation tests still valid under the new contract

## Decisions Made
- `uv` was not installed in this worktree's environment; installed it via astral's official installer (`astral.sh/uv/install.sh`) rather than substituting any other tool — this is provisioning the sanctioned project tool, not a package-legitimacy question (that gate was already cleared in Task 1).
- Containerfile.backend required no textual edit: it already runs `uv sync --frozen` against `pyproject.toml`/`uv.lock` generically, so the two new dependencies flow through automatically.
- See `key-decisions` in frontmatter for the POST /projects retirement and response-shape decisions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `test_e2e.py` conflicted with the plan's own "full suite still passes" verification requirement**
- **Found during:** Task 3 (rewriting POST /projects)
- **Issue:** The plan's `<action>` text for Task 3 explicitly replaces POST /projects' synchronous chunk→synthesize→join→download behavior with the new 201-immediately/background-analysis shape, but `backend/tests/test_e2e.py` (not listed in the plan's `files_modified`) asserted on the old shape (200 + WAV bytes, chunk-file cleanup, TTS 4xx passthrough via `main_module.synthesize`, join-failure via `main_module.join_wavs`). Since those code paths no longer exist in the rewritten `main.py`, 4 of 7 tests failed — not a regression, but a direct, predictable consequence of the plan's own required rewrite that the plan's file list didn't account for.
- **Fix:** Trimmed `test_e2e.py` to the 3 tests that still validate current behavior (oversized/non-utf8/empty-body upload rejection, now against the 201 response). Deleted the 4 tests asserting on retired synchronous-generation behavior; documented the retirement in the file's new docstring.
- **Files modified:** `backend/tests/test_e2e.py`
- **Verification:** `uv run pytest` (full suite): 15 passed, 2 skipped (integration tests requiring the real pod), 0 failed.
- **Committed in:** `7df937a` (Task 3 commit)

**2. [Rule 3 - Blocking] `uv` was not installed in this worktree**
- **Found during:** Task 2 (`uv add sqlmodel xai-sdk`)
- **Issue:** `uv: command not found` — the worktree's environment had no `uv` binary or `pip`, so the plan's mandated `uv add` step could not run.
- **Fix:** Installed `uv` via `curl -LsSf https://astral.sh/uv/install.sh | sh` (astral's own official installer, the same tool the project already standardizes on per CLAUDE.md) into `~/.local/bin`, then ran `uv add sqlmodel xai-sdk` as planned.
- **Files modified:** None (tooling install, not a package substitution — Task 1's package-legitimacy approval already covered `sqlmodel`/`xai-sdk` themselves).
- **Verification:** `uv --version` succeeded; `uv add` installed and pinned both packages in `pyproject.toml`/`uv.lock`.
- **Committed in:** `3bf67e6` (Task 2 commit)

**3. [Rule 2 - Missing Critical] `backend/.gitignore` did not exclude the new SQLite database file**
- **Found during:** Task 2 (adding `db.py`)
- **Issue:** `projects.db` is runtime data generated by `init_db()`; without a `.gitignore` entry it would be committed on the first `git add` sweep of a working directory.
- **Fix:** Added `*.db` to `backend/.gitignore`.
- **Files modified:** `backend/.gitignore`
- **Verification:** `git status --short` shows `projects.db` untracked/ignored after running the test suite.
- **Committed in:** `3bf67e6` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 Rule 3 blocking, 1 Rule 2 missing-critical)
**Impact on plan:** All three were necessary to satisfy the plan's own verification requirements ("full suite passes", `uv add` succeeding) and to avoid committing runtime data. No scope creep — no functionality was added beyond what Task 2/3 already specified.

## Issues Encountered
- `TestClient(app)` constructed without a `with` block skips FastAPI's `lifespan` context, so `init_db()` (wired into `lifespan`) never ran in `test_analysis_pipeline.py`/`test_e2e.py`, causing `sqlite3.OperationalError: no such table: project`. Fixed by calling `init_db()` explicitly at test-module import time (idempotent — `SQLModel.metadata.create_all` is a no-op if tables already exist), which mirrors what a real deployed process's lifespan already does.
- `backend/app/audio_join.py` (ffmpeg join) is no longer imported anywhere in `app/` after this rewrite — it's not orphaned/dead code, it's Phase 3's per-segment-regeneration join step waiting for its endpoint. Left untouched.
- `backend/tests/test_integration.py` (marked `pytest.mark.integration`, skipped without a live pod) still asserts the old synchronous `/projects` contract. It's currently a no-op in CI/dev (always skipped here), but will need a rewrite once Phase 3 reintroduces real per-segment generation against the reviewed cast — flagging for that phase rather than expanding this plan's scope to a test file with zero current runtime signal.

## User Setup Required
None - no external service configuration required (LLM_BACKEND defaults to "mock"; real XAI_API_KEY wiring is Plan 03).

## Next Phase Readiness
- Wave 2 (02-02 EPUB ingestion, 02-03 real Grok analysis) can build directly on `db.py`/`models.py`/`schemas.py`/`analysis_client.py`'s mock/real switch point.
- `analysis_client.analyze()`'s non-mock branch is currently a `NotImplementedError` stub gated behind the lazy `xai_sdk` import — Plan 03 fills in the real `chat.parse(CastAnalysisResult)` call per RESEARCH.md Pattern 1.
- `backend/tests/test_integration.py` needs a rewrite once Phase 3's real generation endpoint exists (see Issues Encountered above) — not a blocker for Wave 2/3, since it's already skipped in all current environments.

---
*Phase: 02-llm-cast-detection-review-wizard*
*Completed: 2026-07-10*
