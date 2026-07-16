---
phase: 04-immediate-cancellation
plan: 02
subsystem: api
tags: [fastapi, httpx, tts-service, cancellation]

# Dependency graph
requires:
  - phase: 04-immediate-cancellation
    provides: "_cancel_event, _CancelStoppingCriteria, GenerationCancelled, request_cancel() in tts_service/model.py (04-01), hardware-verified to abort the talker's decode loop within ~46ms"
provides:
  - "POST /cancel on tts_service (202, calls request_cancel(); 503 if model not loaded)"
  - "GenerationCancelled handling in /synthesize — returns 499, ordered before the broad except Exception"
  - "tts_client.cancel() — best-effort, mock/http-aware, never raises"
affects: [04-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy-import GenerationCancelled from tts_service.model inside the request handler (not at module top level), matching the file's existing _model_module lazy-load discipline so test collection never triggers a real model load"
    - "Short, dedicated httpx.Timeout for the cancel POST (2s all-phases) distinct from synthesize's 300s read timeout — cancel must never itself become the slow path"

key-files:
  created:
    - backend/tests/test_tts_client_cancel.py
  modified:
    - backend/tts_service/server.py
    - backend/app/tts_client.py

key-decisions:
  - "Chose HTTP 499 (Client Closed Request, the nginx/gateway convention for 'request aborted by caller') for a cancelled /synthesize response — non-standard in FastAPI's own vocabulary but a well-understood non-500 signal that keeps the /synthesize response shape a plain status code, no new response body schema needed."
  - "cancel() uses a dedicated 2s httpx.Timeout on every phase (connect/read/write/pool) rather than reusing synthesize()'s 300s read timeout — the cancel path must never itself become the thing blocking lock release."

patterns-established:
  - "Best-effort HTTP call pattern: catch httpx.HTTPError broadly (covers both raise_for_status()'s HTTPStatusError and connection-level TransportError), log a warning, and always return normally — never propagate into a caller that has cleanup work (lock release) it must still do."

requirements-completed: [GEN-06, GEN-07, GEN-08]

coverage:
  - id: D1
    description: "POST /cancel on tts_service calls request_cancel() and returns 202, interrupting the in-flight /synthesize decode loop"
    requirement: "GEN-06"
    verification:
      - kind: other
        ref: "grep -n '\"/cancel\"' backend/tts_service/server.py"
        status: pass
      - kind: unit
        ref: "backend/tts_service/model.py's request_cancel()/_cancel_event contract, hardware-verified in 04-01 (spike_cancel_hw.py); this plan only adds the HTTP call site on top of an already-verified mechanism"
        status: pass
    human_judgment: false
  - id: D2
    description: "tts_client.cancel() POSTs to tts_service /cancel and is best-effort: a 5xx/timeout on the cancel call itself does not raise into the caller"
    requirement: "GEN-07"
    verification:
      - kind: unit
        ref: "backend/tests/test_tts_client_cancel.py#test_cancel_noops_on_mock_backend"
        status: pass
      - kind: unit
        ref: "backend/tests/test_tts_client_cancel.py#test_cancel_swallows_httpx_error_on_http_backend"
        status: pass
      - kind: unit
        ref: "backend/tests/test_tts_client_cancel.py#test_cancel_posts_to_cancel_endpoint_on_http_backend"
        status: pass
    human_judgment: false
  - id: D3
    description: "A cancelled /synthesize surfaces GenerationCancelled cleanly (not a 500 stack leak, not a silent partial WAV) — mapped to a distinct 499 status ordered before the broad except Exception"
    requirement: "GEN-08"
    verification:
      - kind: other
        ref: "grep -n 'except GenerationCancelled' backend/tts_service/server.py (arm precedes 'except Exception')"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-07-13
status: complete
---

# Phase 4 Plan 2: HTTP Cancel Surface (tts_service /cancel + backend tts_client.cancel()) Summary

**Exposed 04-01's proven `_cancel_event`/`request_cancel()` machinery across the backend↔tts_service HTTP boundary: a `POST /cancel` (202) on `tts_service/server.py`, a `GenerationCancelled → 499` arm in `/synthesize`, and a best-effort `tts_client.cancel()` on the backend side that never raises into its caller.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-13 (Task 1 commit `2892b3e`)
- **Completed:** 2026-07-13 (Task 2 commit `94097a9`)
- **Tasks:** 2/2
- **Files modified:** 3 (2 modified, 1 test file created)

## Accomplishments

- `tts_service/server.py` gained `POST /cancel` — calls `request_cancel()` and returns 202 without blocking on the in-flight call; returns 503 if `_model_module` isn't loaded yet, matching `/synthesize`'s existing not-ready guard shape.
- `/synthesize` now catches `GenerationCancelled` (lazily imported from `tts_service.model`, same lazy-load discipline as `_model_module` itself) before the broad `except Exception`, returning 499 instead of a 500 — a cancelled run is now distinguishable from a crash at the HTTP layer, closing T-04-06.
- `backend/app/tts_client.py` gained `cancel()`: a mock no-op (nothing to interrupt) / http POST-to-`/cancel` switch mirroring `tts_health()`'s existing backend dispatch, with a dedicated 2s timeout and a broad `except httpx.HTTPError` that logs and swallows — the caller (04-03's lock-release path) is guaranteed to proceed even if the cancel POST itself fails, closing T-04-05.
- Added `backend/tests/test_tts_client_cancel.py` (3 tests) proving the mock no-op, the http POST target (`{TTS_SERVICE_URL}/cancel`), and that a raised `httpx.ConnectError` is swallowed rather than propagated.

## Task Commits

Each task was committed atomically:

1. **Task 1: POST /cancel endpoint + GenerationCancelled handling in tts_service/server.py** - `2892b3e` (feat)
2. **Task 2: Best-effort cancel() in backend tts_client.py** - `94097a9` (feat)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified

- `backend/tts_service/server.py` - `POST /cancel` route (202/503); `except GenerationCancelled` arm in `/synthesize` returning 499, ordered before the broad `except Exception`
- `backend/app/tts_client.py` - `cancel() -> None`, mock/http-aware, best-effort (never raises)
- `backend/tests/test_tts_client_cancel.py` - unit tests for `cancel()`'s mock no-op, http POST target, and swallowed-httpx-error behavior

## Decisions Made

- **499 for a cancelled /synthesize response** (not 200-with-empty-body): keeps the response a plain status-code signal with no new body schema, and 499 is a widely-recognized (if non-RFC) "client aborted the request" convention across gateways — documented inline in the handler's comment per the plan's instruction to "pick one and note it in a comment."
- **`GenerationCancelled` imported inside the request handler, not at module top level**: mirrors the file's existing pattern of keeping `tts_service.model`'s heavy (real GPU model) import lazy so importing `tts_service.server` for test collection never triggers a real model load. By the time `/synthesize` runs, `tts_service.model` is already resident in `sys.modules` (loaded once at `lifespan` startup), so this is a zero-cost re-binding, not a second import.
- **`cancel()`'s httpx timeout (2s, all phases) is deliberately much shorter than `synthesize()`'s (300s read)**: the cancel path exists specifically to unblock the caller quickly; a slow cancel POST would defeat its own purpose.

## Deviations from Plan

None — plan executed exactly as written. The plan's acceptance criteria specified both files' shapes precisely enough (existing `tts_health()`/`synthesize()` backend-switch pattern to mirror, existing not-loaded 503 guard shape to match) that no gaps or ambiguities required a Rule 1-4 deviation.

## Issues Encountered

- **Pre-existing, out-of-scope test failure discovered during full-suite verification**: `backend/tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined` asserts the upload endpoint returns `200` with a WAV body directly — stale from Phase 1 (`01-03`, commit `d4b874e`), predating Phase 2's async analyze/review-wizard flow that changed the upload contract to `201 {"id", "status": "analyzing"}`. Unrelated to this plan's files; logged to `.planning/phases/04-immediate-cancellation/deferred-items.md` per the executor's scope-boundary rule rather than fixed here.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The full HTTP cancel surface is landed and ruff-clean: `POST /cancel` on `tts_service`, `GenerationCancelled → 499` in `/synthesize`, and `tts_client.cancel()` on the backend side.
- **04-03 can now build the user-facing cancel endpoints and task/lock orchestration** (per-segment generate becoming a background task with a cancel registry, the batch cancel endpoint calling the new `tts_client.cancel()`, and the "stopping…" transient UI state per D-03/D-05) directly on top of this plumbing — no further tts_service or tts_client changes should be needed for the mechanism itself.
- **04-03 should remember the vocoder-tail latency documented in 04-01's summary**: cancel-to-stop is not always sub-second (talker decode loop stops in ~46ms, but the non-interruptible vocoder decode after it scales with how much was already generated) — the "stopping…" state may need to persist for several seconds to tens of seconds in the worst case, not flip back to idle instantly.
- No blockers for 04-03.

---
*Phase: 04-immediate-cancellation*
*Completed: 2026-07-13*

## Self-Check: PASSED

All created/modified files confirmed present on disk; all task/docs commit hashes (`2892b3e`, `94097a9`, `9069fc9`) confirmed present in `git log`.
