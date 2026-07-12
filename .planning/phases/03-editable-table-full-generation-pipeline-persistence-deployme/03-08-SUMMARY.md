---
phase: 03-editable-table-full-generation-pipeline-persistence-deployme
plan: 08
subsystem: api
tags: [fastapi, asyncio, generation-lifecycle, sqlmodel]

# Dependency graph
requires:
  - phase: 03-editable-table-full-generation-pipeline-persistence-deployme
    provides: patch_segment, generate_project, generate_segment, run_batch_generation, _generate_preview (plans 03-01/03-02/03-03)
provides:
  - "patch_segment invalidate-only edit semantics (GEN-03/D-06 reversed)"
  - "per-project in-flight generation registry (_running_generations) with guard + cancel"
  - "POST /projects/{id}/generate/cancel"
  - "POST /characters/{id}/preview on-demand trigger"
affects: [03-09-frontend-generation-controls]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-project in-flight task registry (dict[str, asyncio.Task] + is_x_running/get_x_task helpers), same discipline as the existing progress-queue registry"
    - "asyncio.CancelledError is a BaseException — cancellation naturally skips `except Exception` cleanup blocks without special-casing"

key-files:
  created: []
  modified:
    - backend/app/main.py
    - backend/app/generation_worker.py
    - backend/tests/test_generation.py
    - backend/tests/test_wizard_endpoints.py
    - .planning/REQUIREMENTS.md
    - .planning/phases/03-editable-table-full-generation-pipeline-persistence-deployme/03-CONTEXT.md

key-decisions:
  - "D-06/GEN-03 reversed per user-confirmed requirement change: edits invalidate (clear audio, mark pending) but never auto-fire a background regeneration; regeneration is always user-triggered"
  - "generate_project responds {\"status\": \"already_running\"} (still 202) rather than 409 for a rejected second batch — frontend only needs the string to distinguish started vs. not-started"
  - "Cancel settles the SSE stream by reusing the existing 'done' event type with {\"status\": \"cancelled\"} (useGenerationStream already treats any non-'ready' done payload as settling to idle) instead of adding a new client event type"
  - "Cancellation ceiling is real, not hidden: tts_client.synthesize() runs in a threadpool thread that cannot be forcibly interrupted, so a segment already mid-synth finishes its HTTP call before cancel takes effect — documented with a `# ponytail:` comment naming the upgrade path"

requirements-completed: [GEN-02, GEN-03, GEN-05, CFG-03]

coverage:
  - id: D1
    description: "PATCH /segments/{id} invalidates only (clears audio_path, sets status=pending, unlinks stale file) — no auto-regeneration fires"
    requirement: "GEN-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_patch_invalidates_without_regenerating"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_patch_bumps_generation_version"
        status: pass
    human_judgment: false
  - id: D2
    description: "A second Generate All while one is running is rejected without spawning a second batch task"
    requirement: "GEN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_second_generate_all_while_running_is_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "A per-row generate on an already-generating segment is rejected with 409"
    requirement: "GEN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_per_row_generate_rejects_duplicate_while_generating"
        status: pass
    human_judgment: false
  - id: D4
    description: "A running batch can be cancelled: stops before the next segment, resets in-flight rows to pending, settles the SSE stream"
    requirement: "GEN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_cancel_running_batch_resets_generating_rows"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_cancel_when_nothing_running_is_noop"
        status: pass
    human_judgment: false
  - id: D5
    description: "POST /characters/{id}/preview generates a character preview on demand and 404s for a missing character"
    requirement: "CFG-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_trigger_preview_generates_on_demand"
        status: pass
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_trigger_preview_missing_character_404s"
        status: pass
    human_judgment: false

duration: ~15min
completed: 2026-07-12
status: complete
---

# Phase 3 Plan 08: Generation Lifecycle Safety (invalidate-only edits, in-flight guard, cancel, preview trigger) Summary

**Reversed GEN-03/D-06 to invalidate-only edits, added a per-project in-flight generation registry guarding both batch and per-row generate, a cancel endpoint for a running batch, and an on-demand character-preview trigger endpoint.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- `PATCH /segments/{id}` now clears the row's stale audio and marks it `pending` on any field change, but never fires a background regeneration — the user must trigger regeneration manually via the per-row `generate` button or Generate All
- Added `_running_generations` per-project task registry in `generation_worker.py`; `POST /projects/{id}/generate` now rejects a concurrent second call (`{"status": "already_running"}`) instead of racing a second `run_batch_generation` pass, which also makes the worker's crash-leftover stale-'generating' reset correct again
- `POST /segments/{id}/generate` rejects a duplicate call on an already-'generating' row with 409
- Added `POST /projects/{id}/generate/cancel`: cancels the live batch task, resets any rows still `generating` back to `pending`, and pushes a `done`/`{"status": "cancelled"}` event so the SSE stream settles without a new client event type; the threadpool cancellation ceiling (a mid-synth segment finishes its HTTP call before cancel takes effect) is documented in code with a `# ponytail:` comment
- Added `POST /characters/{id}/preview`: on-demand preview generation for a character whose voice was never (re)saved via PATCH, reusing the existing race-safe `_generate_preview`

## Task Commits

Each task was committed atomically:

1. **Task 1: patch_segment invalidates only — no auto-regeneration (reverse D-06/GEN-03)** - `78a84e8` (fix)
2. **Task 2: Per-project in-flight generation guard (batch + per-row)** - `dc176fe` (feat)
3. **Task 3: Cancel a running batch + on-demand character-preview endpoint** - `f9a6585` (feat)

_No TDD tasks in this plan — all three were type="auto"._

## Files Created/Modified
- `backend/app/main.py` - `patch_segment` invalidate-only rewrite; `generate_project` in-flight guard + `already_running` response; `generate_segment` 409-on-duplicate guard; new `POST /projects/{id}/generate/cancel`; new `POST /characters/{id}/preview`
- `backend/app/generation_worker.py` - `_running_generations` registry, `is_generation_running`/`get_generation_task`/`push_generation_event` helpers, documented `run_batch_generation`'s existing CancelledError-clean behavior
- `backend/tests/test_generation.py` - updated 3 existing tests to invalidate-only semantics, added `test_patch_invalidates_without_regenerating`, `test_second_generate_all_while_running_is_rejected`, `test_per_row_generate_rejects_duplicate_while_generating`, `test_cancel_running_batch_resets_generating_rows`, `test_cancel_when_nothing_running_is_noop`
- `backend/tests/test_wizard_endpoints.py` - added `test_trigger_preview_generates_on_demand`, `test_trigger_preview_missing_character_404s`
- `.planning/REQUIREMENTS.md` - reworded GEN-03 to invalidate-then-manual semantics
- `.planning/phases/03-editable-table-full-generation-pipeline-persistence-deployme/03-CONTEXT.md` - annotated D-06 as REVERSED during 03 UAT

## Decisions Made
- Reversed D-06/GEN-03 per the user-confirmed requirement change captured in the plan: edits invalidate only, regeneration is always manual — see REQUIREMENTS.md and 03-CONTEXT.md D-06 annotation
- `generate_project`'s "already running" response stays 202 (not 409) — it's a request that was validly accepted, just not started as a new run; the frontend only needs the status string to distinguish the two outcomes
- Cancel's terminal event reuses the existing `"done"` SSE event type with `{"status": "cancelled"}` rather than introducing a new client-side event type, since `useGenerationStream` already treats any non-`"ready"` `done` payload as settling to `"idle"`
- No functional change was needed in `run_batch_generation` for CancelledError handling — `asyncio.CancelledError` is a `BaseException` in Python 3.8+, so it already propagates untouched past the existing `except Exception` blocks; only documentation (a docstring note + `push_generation_event` helper) was added

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Backend generation lifecycle is now safe and user-controlled: invalidate-only edits, a per-project in-flight guard on both batch and per-row generation, a cancel path, and an on-demand preview trigger. Plan 03-09 (frontend) can now build the Config Panel controls (Generate All / Cancel / per-row generate buttons, preview trigger) against these endpoints without racing backend state. No blockers identified.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployme*
*Completed: 2026-07-12*
