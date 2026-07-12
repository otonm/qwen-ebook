---
phase: 03-editable-table-full-generation-pipeline-persistence-deployment
plan: 03
subsystem: api
tags: [fastapi, sqlmodel, sqlite, asyncio, sse, react, tanstack-table]

requires:
  - phase: 03-01
    provides: Segment generation_status/generation_error/audio_path/cache_key/generation_version columns, compute_cache_key(), regenerate_segment last-request-wins guard, SegmentTable
  - phase: 03-02
    provides: Checkbox row selection + bulk-reassign toolbar (generation_version bump only, no auto-regen)
provides:
  - "run_batch_generation() resumable batch state machine (generation_worker.py) — stale-\"generating\" reset, in-order walk, per-segment reuse of main.py's regenerate_segment, continue-past-error"
  - POST /projects/{id}/generate, GET /projects/{id}/generation-stream (SSE)
  - Blocking batch join (audio_join.join_wavs over complete segments' audio_paths in order), Project.output_path
  - Project payload gains output_path/output_format (previously unexposed)
  - useGenerationStream hook (per-segment live status + overall n/total)
  - ConfigPanel (CFG-01/02/03): input/model/output summary, character preview list, Generate All/Resume Generation CTA + progress bar + join-blocked error copy
  - ProjectScreen renders SegmentTable (70%) + ConfigPanel (30%) side-by-side, live status merged into table rows
affects: [03-04, 03-05]

tech-stack:
  added: []
  patterns:
    - "Batch loop reuses the per-row regenerate_segment helper (lazy in-function import to avoid a main.py<->generation_worker.py circular import) instead of duplicating the cache-check/version-guard logic — one implementation for both call sites"
    - "SSE progress queue registry duplicated per-domain (generation_progress_queues separate from analysis's _progress_queues), same drain-until-terminal shape"

key-files:
  created:
    - backend/app/generation_worker.py
    - frontend/src/hooks/useGenerationStream.ts
    - frontend/src/components/ConfigPanel.tsx
  modified:
    - backend/app/main.py
    - backend/tests/test_generation.py
    - frontend/src/api/client.ts
    - frontend/src/components/ProjectScreen.tsx

key-decisions:
  - "Batch loop does not duplicate the content-hash cache check — it calls main.py's regenerate_segment (the same function per-row auto-regen and TBL-04's on-demand generate use), so cache-hit-skip, live cache-key recompute (Pitfall 3), and generation_version last-request-wins (Pitfall 2) all come from one code path instead of two implementations drifting apart."
  - "The join runs as the final step inside run_batch_generation itself (not a separate POST /projects/{id}/join endpoint) — one fewer endpoint, matches the plan's 'either at batch end inside the worker or a join endpoint' discretion."
  - "Task 4's real-GPU checkpoint was executed by the orchestrator session directly on the production tts VM (pod rebuilt with 03-03's commits, TTS_BACKEND=http), automated via seeded throwaway projects + polling /projects/{id} + podman restart to simulate a crash + TTS-container synth-call-count log inspection — same automated-substitution pattern as 03-01's Task 4, not a scope deviation."
  - "Deviation (Rule 2): _serialize_project exposed neither output_path nor output_format, so ConfigPanel's CFG-01 output-file/output-format fields had nothing to render — added both to the existing project payload, no schema change."

patterns-established:
  - "Resumable batch state machine (Pattern 5): reset stale \"generating\" to \"pending\" before the loop, persist status after every segment (not just at the end), continue past a per-segment failure instead of aborting, block the join with a surfaced error if any segment lacks a valid audio_path."

requirements-completed: [GEN-05, CFG-01, CFG-02, CFG-03]

coverage:
  - id: D1
    description: "Generate All synthesizes the whole project's pending segments in order with live per-segment/overall progress, then joins into a single output file"
    requirement: "GEN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_batch_generates_all_pending"
        status: pass
      - kind: manual_procedural
        ref: "Task 4 step 1 (orchestrator, tts VM): 3-segment real-GPU batch, in-order pending->generating->complete transitions, joined WAV duration (10.88s) exactly equals sum of the 3 segment durations"
        status: pass
    human_judgment: false
  - id: D2
    description: "An interrupted batch (crash mid-run) resumes correctly: completed rows skipped, stale generating row reset and regenerated, one failure doesn't abort the rest"
    requirement: "GEN-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_batch_resets_stale_generating"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_batch_skips_complete_rows"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_batch_continues_past_error"
        status: pass
      - kind: manual_procedural
        ref: "Task 4 step 2 (orchestrator, tts VM): podman restart mid-batch to simulate a crash; resumed run left the 2 already-complete rows byte-identical (unchanged mtime), reset+regenerated the stale row, completed the still-pending row; TTS container logs showed exactly 2 /synthesize calls during resume"
        status: pass
    human_judgment: false
  - id: D3
    description: "A per-row edit made mid-batch wins over the stale batch write for that same row (last-request-wins generation_version guard)"
    requirement: "GEN-05"
    verification:
      - kind: manual_procedural
        ref: "Task 4 step 3 (orchestrator, tts VM): PATCHed a segment's text while the batch's regenerate_segment for that same row was in flight; final text/cache_key matched the edit, not the stale batch write; audio confirmed playable/non-silent"
        status: pass
    human_judgment: false
    rationale: "This exact real-GPU concurrent-edit race (CONTEXT.md D-02/D-06) has no equivalent mock-backend unit test in this plan (test_patch_bumps_generation_version from 03-01 covers the guard logic itself, but not batch-vs-per-row concurrency) — the real-hardware checkpoint is the only proof for this specific interaction."
  - id: D4
    description: "Config panel shows input file, model, output format/file (CFG-01), character list with preview controls (CFG-02), and live per-segment/overall progress (CFG-03)"
    requirement: "CFG-01"
    verification:
      - kind: automated_ui
        ref: "frontend build (tsc -b && vite build) + grep confirms ConfigPanel renders ConfigField rows, CharacterPreviewRow list, and the Progress component"
        status: pass
    human_judgment: true
    rationale: "Build success and grep confirm the panel compiles and renders the right sub-components, but visual/interactive appearance (spacing, the Generate All -> Resume Generation relabel, the join-blocked error banner) was not exercised in a live browser this session — no UI checkpoint was reached for Task 3 (autonomous task, no checkpoint gate)."

duration: ~4min (Tasks 1-3) + real-hardware checkpoint (orchestrator session, production tts VM)
completed: 2026-07-12
status: complete
---

# Phase 3 Plan 3: Resumable Batch Generation + Config Panel Summary

**Resumable per-segment batch generation (stale-reset, cache-skip, continue-past-error, blocking join) driving live SSE progress into a new ConfigPanel with a Generate All/Resume Generation CTA — verified against both `TTS_BACKEND=mock` (11 tests) and real gfx1201 GPU synthesis including a simulated mid-batch crash and a concurrent per-row-edit race.**

## Performance

- **Duration:** ~4 min (Tasks 1-3) + real-hardware checkpoint (orchestrator session)
- **Tasks:** 4 (3 auto + 1 human-verify checkpoint)
- **Files modified:** 7 (3 new: `generation_worker.py`, `useGenerationStream.ts`, `ConfigPanel.tsx`)

## Accomplishments
- `generation_worker.py`: `run_batch_generation()` resets stale `"generating"` rows to `"pending"` before its loop (crash-safety), walks segments in table order, and reuses `main.py`'s `regenerate_segment` for the actual synth call — so batch generation and per-row auto-regen/on-demand generate share one cache-check/version-guard implementation instead of two.
- `POST /projects/{id}/generate` (202, fire-and-forget background task) and `GET /projects/{id}/generation-stream` (SSE, mirrors `analysis_stream`'s shape) with a `{segment_id, n, total, status}` event schema.
- Batch join is a blocking final step: any segment missing a valid `audio_path` surfaces an error over SSE instead of silently skipping it (Open Question 1's resolution, no "last good" fallback in v1).
- `useGenerationStream` (frontend hook) accumulates live per-segment status + overall n/total from the SSE stream, mirroring `useAnalysisStream`'s lifecycle.
- `ConfigPanel` (CFG-01/02/03): input file/model/output format/output file, the character list with reused play/pause preview controls, and the Generate All/Resume Generation CTA with a live progress bar and the batch-join-blocked error copy from the UI-SPEC.
- `ProjectScreen` now renders the 70% `SegmentTable` / 30% `ConfigPanel` split, merging live per-segment status into the table's rows without `SegmentTable` needing SSE awareness.
- Task 4's real-GPU checkpoint (run by the orchestrator directly on the production `tts` VM) verified full batch generate, crash-interrupt-resume with zero double-synthesis, and the concurrent per-row-edit-wins race — the exact interaction CONTEXT.md D-02/D-06 flagged as never tested against real GPU inference.

## Task Commits

1. **Task 1: Failing tests for resumable batch state machine** - `9be1ae2` (test, RED)
2. **Task 2: generation_worker.py batch loop + batch/stream endpoints + join-on-complete** - `7c52381` (feat, GREEN)
3. **Task 3: ConfigPanel + useGenerationStream frontend, wired into ProjectScreen** - `77fa850` (feat)
4. **Task 4: Real-GPU resumable batch + concurrent per-row-edit smoke** - verified by the orchestrator session directly against the production `tts` VM pod (rebuilt with the above commits, `TTS_BACKEND=http`); no code changes, no commit (checkpoint gate only)

## Files Created/Modified
- `backend/app/generation_worker.py` - resumable batch loop, progress-queue registry, blocking join
- `backend/app/main.py` - `POST /projects/{id}/generate`, `GET /projects/{id}/generation-stream`, `output_path`/`output_format` added to `_serialize_project`
- `backend/tests/test_generation.py` - four batch tests (all-pending, skip-complete, stale-reset, continue-past-error)
- `frontend/src/hooks/useGenerationStream.ts` - SSE hook, per-segment live status + overall n/total
- `frontend/src/components/ConfigPanel.tsx` - CFG-01/02/03 right-side panel
- `frontend/src/components/ProjectScreen.tsx` - 70/30 SegmentTable+ConfigPanel layout, live status merge
- `frontend/src/api/client.ts` - `runBatchGeneration()`, `GenerationProgress` type, `Project.output_path`/`output_format`

## Decisions Made
- Batch loop reuses `main.py`'s `regenerate_segment` via a lazy in-function import (avoids a `main.py` <-> `generation_worker.py` circular import at module-load time) rather than duplicating the cache-check/version-guard logic — see `key-decisions` above.
- Join runs as the final step inside `run_batch_generation` itself, not a separate endpoint.
- Task 4 was executed by the orchestrator session directly on the production `tts` VM (throwaway seeded projects, `podman restart` to simulate a crash, TTS-container log inspection for synth-call counts) — same automated-substitution pattern 03-01's Task 4 used.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `_serialize_project` didn't expose `output_path`/`output_format`**
- **Found during:** Task 3 (ConfigPanel implementation)
- **Issue:** CFG-01 requires showing "output format" and "output file" in the config panel, but the existing `GET /projects/{id}` payload had no way to surface either — `Project.output_path` (added in 03-01's schema front-load) and `settings.OUTPUT_FORMAT` were both server-side-only.
- **Fix:** Added `output_path` and `output_format` keys to `_serialize_project`'s existing return dict — no schema change, no new endpoint.
- **Files modified:** `backend/app/main.py`
- **Verification:** `uv run pytest tests/test_generation.py` still passes; `npm run build` succeeds with `Project.output_path`/`output_format` consumed by `ConfigPanel`.
- **Committed in:** `77fa850` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Necessary for CFG-01 to actually render — no scope creep, same requirement, no new endpoint or table.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
GEN-05/CFG-01/02/03 are proven end-to-end against real GPU hardware, including the crash-resume and concurrent-edit-race interactions CONTEXT.md flagged as the phase's biggest real-hardware risk. Plans 03-04/03-05 (project list/persistence, deployment) can build on `generation_worker.py`/`ConfigPanel` without further schema or endpoint changes to this slice.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployment*
*Completed: 2026-07-12*

## Self-Check: PASSED

All created/modified files verified present on disk; all three task commits (`9be1ae2`, `7c52381`, `77fa850`) verified present in git log.
