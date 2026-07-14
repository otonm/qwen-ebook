---
phase: 05-on-demand-model-swap
plan: 02
subsystem: api
tags: [fastapi, sqlmodel, cache-key, tts, model-swap]

# Dependency graph
requires:
  - phase: 04-immediate-cancellation
    provides: try_claim_generation/release_generation single-flight lock and label-keyed generation task registry
provides:
  - "Project.tts_model column (per-project source of truth for the chosen TTS checkpoint)"
  - "compute_cache_key(..., model_id) — model identity is now part of the content-hash cache key"
  - "tts_client.load_model(model_id) — HTTP helper that propagates swap failures"
  - "POST /projects/{project_id}/model — lock-gated swap orchestration endpoint with D-02 failure safety"
  - "_serialize_project exposes tts_model"
affects: [05-03-model-swap-frontend, tts_service-model-swap-plan]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Project-wide invalidation loop reusing GEN-03's per-row pattern (clear audio_path/cache_key, bump generation_version, status->pending), extended to also clear Character.preview_audio_path (RESEARCH Pitfall 4)"
    - "Synchronous lock-claim orchestration endpoint (claim -> await threadpool call -> on-exception release+502 -> on-success mutate+release) rather than the fire-and-forget _spawn_claimed_generation pattern other generation routes use, since the swap itself is the whole unit of work"

key-files:
  created:
    - backend/tests/test_tts_client_load_model.py
    - backend/tests/test_model_swap.py
  modified:
    - backend/app/models.py
    - backend/app/cache_key.py
    - backend/app/tts_client.py
    - backend/app/main.py

key-decisions:
  - "No cache-key version bump needed beyond the model_id parameter itself — since compute_cache_key's payload now includes a field it never had, every pre-migration key changes automatically, force-invalidating pre-migration cached audio for free"
  - "Character preview invalidation folded into the same swap handler as segment invalidation (RESEARCH Open Question 1 resolved toward inclusion) — a swap clears every character's preview_audio_path too, consistent with D-05's 'obvious, not silent' rationale"
  - "No _invalidate_segment helper extracted — the invalidation loop is inlined directly in the handler (single call site), matching the codebase's existing patch_segment/patch_character inline style rather than adding an unrequested abstraction"

patterns-established:
  - "tts_client.load_model raises (does not swallow) on failure — the deliberate inverse of cancel()'s best-effort swallow, because the caller needs the exception to apply D-02"

requirements-completed: [CFG-04]

coverage:
  - id: D1
    description: "Project.tts_model column threads into compute_cache_key so cross-model cache hits are impossible"
    requirement: "CFG-04"
    verification:
      - kind: unit
        ref: "backend/app/cache_key.py __main__ self-check (differing model_id -> differing digest)"
        status: pass
      - kind: unit
        ref: "backend/tests -k 'model or swap or serialize' (5 passed)"
        status: pass
    human_judgment: false
  - id: D2
    description: "tts_client.load_model(model_id) HTTP helper with mock no-op / http POST+raise / unknown-backend raise three-way switch"
    requirement: "CFG-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_tts_client_load_model.py (5 tests: mock no-op, http URL shape, connect-error propagation, status-error propagation, unknown-backend raise)"
        status: pass
    human_judgment: false
  - id: D3
    description: "POST /projects/{project_id}/model handler: 422 invalid model_id, 409 lock conflict, 502+untouched-state on load failure (D-02), success invalidates segments+previews and exposes tts_model"
    requirement: "CFG-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_model_swap.py (4 tests: 422 rejection, successful invalidation of segments+previews+files, D-02 untouched-on-failure, 409 lock-conflict)"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-07-14
status: complete
---

# Phase 5 Plan 02: Backend Model Swap Orchestration Summary

**Per-project `tts_model` column threaded into the content-hash cache key, a `tts_client.load_model` helper that propagates failures, and a lock-gated `POST /projects/{id}/model` endpoint that invalidates every segment and character preview on success while leaving everything untouched on failure (D-02).**

## Performance

- **Duration:** ~45 min
- **Tasks:** 3 completed (Task 1 followed full RED/GREEN TDD per its `tdd="true"` marker)
- **Files modified:** 4 (`models.py`, `cache_key.py`, `tts_client.py`, `main.py`)
- **Test files created:** 2 (`test_tts_client_load_model.py`, `test_model_swap.py`)

## Accomplishments

- `Project.tts_model: str = "1.7b"` — new SQLModel column, the per-project source of truth `compute_cache_key` reads live on every generate-check (never ambient global config).
- `compute_cache_key` now requires `model_id`; the hardcoded `TTS_MODEL_VERSION` constant is gone. Differing `model_id` produces a differing digest — cross-model stale cache hits are now structurally impossible. This signature change also force-invalidates every pre-migration cached segment for free (the payload now contains a field it never had), so no separate cache-key version bump was needed.
- `tts_client.load_model(model_id)` — mock backend no-ops, http backend POSTs to `/model/{model_id}/load` with the 300s read timeout and lets failures propagate (the deliberate inverse of `cancel()`'s best-effort swallow, since the caller needs the exception to apply D-02).
- `POST /projects/{project_id}/model` — validates `model_id` against `MODEL_CHOICES` (422), claims `model-load:{id}` via the existing single-flight lock (409 on conflict), drives the swap through `tts_client.load_model` in a threadpool. On success: sets `Project.tts_model`, invalidates every segment (GEN-03's clear-audio/cache_key/pending mechanism, reused project-wide) **and** every character's `preview_audio_path` (RESEARCH Pitfall 4 — previews have no cache key of their own and were not covered by D-05/D-06's segment-scoped wording; folded in per the research's recommendation), unlinks old files after commit, releases the lock. On failure: releases the lock and raises 502 with the project row, cached audio, and previews all left untouched.
- `_serialize_project` now exposes `tts_model` for the Config Panel (Plan 03) to drive the dropdown and the 0.6B disabled-cell state.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Project.tts_model column and thread model_id through compute_cache_key** (`tdd="true"`)
   - `2fe74d0` — `test(05-02): add failing self-check for model_id in cache key` (RED)
   - `9d13b2a` — `feat(05-02): thread model_id through compute_cache_key + Project.tts_model column` (GREEN)
2. **Task 2: Add tts_client.load_model(model_id) HTTP helper** — `7993941`
3. **Task 3: Add POST /projects/{id}/model handler with lock, invalidation, and D-02 safety** — `edf45fa`

## TDD Gate Compliance

Task 1 was the only `tdd="true"` task in this plan. Gate sequence verified in git log:
- RED: `2fe74d0` (`test(05-02): ...`) — extended `cache_key.py`'s `__main__` self-check with a `model_id`-differs-implies-digest-differs assertion; confirmed it failed (`TypeError: unexpected keyword argument 'model_id'`) before implementing the signature change.
- GREEN: `9d13b2a` (`feat(05-02): ...`) — implemented the signature change, `Project.tts_model`, and the `regenerate_segment` call-site update; confirmed the self-check passes.
- No REFACTOR commit — the GREEN implementation matched the plan's Pattern 2 shape with no cleanup pass needed.

## Files Created/Modified

- `backend/app/models.py` — `Project.tts_model: str = "1.7b"` column with a versioned-field-style comment.
- `backend/app/cache_key.py` — `compute_cache_key` gains a required `model_id` param; `TTS_MODEL_VERSION` constant removed; module docstring and `__main__` self-check updated.
- `backend/app/tts_client.py` — `load_model(model_id)` helper (mock/http/unknown three-way switch, raises on failure).
- `backend/app/main.py` — `regenerate_segment` now loads the project and passes `project.tts_model` into `compute_cache_key`; new `MODEL_CHOICES` constant, `SetModelRequest` body model, `POST /projects/{project_id}/model` handler; `_serialize_project` exposes `tts_model`.
- `backend/tests/test_tts_client_load_model.py` — mirrors `test_tts_client_cancel.py`'s structure: mock no-op, http URL/timeout shape, propagation of both connect and status errors, unknown-backend raise.
- `backend/tests/test_model_swap.py` — 422 validation, successful invalidation (segments + previews + file unlink + `cache_key`/`generation_version` state), D-02 untouched-on-failure, 409 lock-conflict.

## Decisions Made

- **No cache-key version bump beyond the `model_id` param itself.** Because `compute_cache_key`'s payload now includes a field it never had, every pre-migration key changes automatically — this force-invalidates pre-migration cached audio for free, resolving RESEARCH's "Claude's Discretion" question without a separate version-bump mechanism.
- **Character preview invalidation included in the swap handler** (RESEARCH Open Question 1, resolved toward option (a)). D-05/D-06 explicitly scoped invalidation to segments, but character previews have no cache key and were not covered — leaving them stale would contradict D-05's own "obvious, not silent" rationale, so the swap handler clears every character's `preview_audio_path` too, in the same loop.
- **No `_invalidate_segment` helper extracted.** RESEARCH's code example referenced a hypothetical extracted helper, but no such helper exists in the codebase and there's only one call site — the invalidation loop is inlined directly in the handler, matching `patch_segment`/`patch_character`'s existing inline style rather than adding an unrequested abstraction for a single use.

## Deviations from Plan

None — plan executed exactly as written, including both scope-resolution notes the plan explicitly flagged (cache-key version bump: not needed; character preview invalidation: included).

## Issues Encountered

None specific to this plan's scope. `tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined` fails on this worktree both before and after this plan's changes (confirmed via `git stash`) — a pre-existing 201-vs-200 status code assertion unrelated to model swap, out of scope per the deviation rules' scope boundary (not touched by any file this plan modifies). Not fixed; not introduced by this work.

## User Setup Required

None — no external service configuration required. No migration file needed either: this codebase uses SQLModel `create_all` with no migrations directory, so the new `tts_model` column is picked up automatically for fresh databases; for a pre-existing dev SQLite file, the column read defaults to `"1.7b"` and the cache-key signature change already force-invalidates any pre-migration cached audio, so a stale-DB row simply regenerates on next use.

## Next Phase Readiness

- `_serialize_project`'s `tts_model` field and the `POST /projects/{id}/model` endpoint are ready for Plan 03 (frontend Config Panel dropdown, D-01/D-02/D-03/D-04 UI wiring per `05-UI-SPEC.md`).
- `tts_service`'s own `/model/{model_id}/load` route (the other end of `tts_client.load_model`'s HTTP call) is Plan 01's responsibility, executed in parallel in a sibling worktree — not built by this plan.
- No blockers for downstream plans.

---
*Phase: 05-on-demand-model-swap*
*Completed: 2026-07-14*

## Self-Check: PASSED

All created/modified files verified present on disk; all 5 task/summary commit hashes (`2fe74d0`, `9d13b2a`, `7993941`, `edf45fa`, `8c0bdb3`) verified present in git log.
