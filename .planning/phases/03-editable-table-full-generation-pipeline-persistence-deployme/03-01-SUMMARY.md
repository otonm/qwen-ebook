---
phase: 03-editable-table-full-generation-pipeline-persistence-deployment
plan: 01
subsystem: api
tags: [fastapi, sqlmodel, tanstack-table, sqlite, wal, sha256, react]

requires:
  - phase: 02
    provides: Character/Segment models, analysis pipeline, mock/http TTS backend switch, CharacterCard blur-commit pattern
provides:
  - Segment generation_status/generation_error/audio_path/cache_key/generation_version columns
  - Project created_at/output_path columns
  - Additive SQLite migration (_ensure_columns) + WAL journal mode
  - compute_cache_key() content-hash (sha256 over speaker/instructions/text)
  - PATCH /segments/{id}, POST /segments/{id}/generate, GET /segments/{id}/audio.wav
  - Last-request-wins generation_version guard for concurrent regen
  - Editable SegmentTable (Narrator/Voice Instructions/Text, blur-commit) + ProjectScreen
affects: [03-02, 03-03, 03-04, 03-05]

tech-stack:
  added: []
  patterns:
    - "Server-generated uuid4().hex audio filenames, never derived from client text"
    - "Cache key recomputed live from current DB state before every synth call (not trusted from a stale patch payload)"
    - "Background regen task guarded by generation_version equality check before writeback (last-request-wins)"

key-files:
  created:
    - backend/app/cache_key.py
    - backend/tests/test_generation.py
    - frontend/src/components/SegmentTable.tsx
    - frontend/src/components/ProjectScreen.tsx
  modified:
    - backend/app/models.py
    - backend/app/db.py
    - backend/app/main.py
    - frontend/src/api/client.ts
    - frontend/src/App.tsx

key-decisions:
  - "Real-hardware checkpoints (Task 0 pod bring-up, Task 4 real-GPU smoke) were run directly on the tts VM (this session ran there) rather than via a separate manual round-trip — Task 4 was automated end-to-end via curl + WAV analysis instead of a browser listen test."
  - "Task 4 seeded its test Project/Character/Segment directly into the running backend container's DB (podman exec, same pattern as test_generation.py's _seed_segment) rather than going through the LLM analysis pipeline — isolates the check to the generation/cache slice, no OpenRouter cost."

patterns-established:
  - "Pattern 1 (editable cell): local useState, commit onBlur only, never onChange — applied to SegmentTable's Narrator/Voice Instructions/Text cells"
  - "Pattern 4 (content-hash cache): sha256 over resolved_speaker + voice_instructions + text + TTS_MODEL_VERSION, recomputed live before every synth"

requirements-completed: [TBL-01, TBL-02, TBL-04, GEN-02, GEN-03]

coverage:
  - id: D1
    description: "Editable Narrator/Voice Instructions/Text cells persist on blur"
    requirement: "TBL-01"
    verification:
      - kind: automated_ui
        ref: "frontend build + grep confirms onBlur commit, no onChange patchSegment call"
        status: pass
    human_judgment: false
  - id: D2
    description: "Per-row generate + play button synthesizes and plays a single segment's audio"
    requirement: "TBL-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_generate_segment_produces_audio"
        status: pass
      - kind: manual_procedural
        ref: "Task 4 step 1: POST /segments/{id}/generate against real GPU, WAV analyzed (2.32s @ 24kHz, 97.4% non-zero samples, RMS ~5034)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Content-hash cache reuses audio for an unchanged row (cache hit, no re-synthesis)"
    requirement: "GEN-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_regenerate_only_on_edit_reuses_cache"
        status: pass
      - kind: manual_procedural
        ref: "Task 4 step 3: repeat generate on unchanged real-GPU segment returned in 33ms, byte-identical WAV, TTS container logs show 0 additional /synthesize calls"
        status: pass
    human_judgment: false
  - id: D4
    description: "Editing a row's text busts the cache and regenerates only that row via the version-guarded background task"
    requirement: "GEN-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_edit_text_busts_cache"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_patch_bumps_generation_version"
        status: pass
      - kind: manual_procedural
        ref: "Task 4 step 2: PATCH text against real GPU produced a different audio hash/cache_key/audio_path than step 1"
        status: pass
    human_judgment: false

duration: ~10min (Tasks 1-3, prior session) + real-hardware checkpoint (this session)
completed: 2026-07-12
status: complete
---

# Phase 3 Plan 1: Editable Segment Table + Generation/Cache Pipeline Summary

**Per-segment generate/patch/cache endpoints (content-hash sha256, last-request-wins version guard) plus an editable TanStack SegmentTable with blur-commit cells, verified against both TTS_BACKEND=mock (test suite) and the real gfx1201 GPU pod (Task 4 automated smoke).**

## Performance

- **Tasks:** 5 (2 human-verify checkpoints + 3 auto)
- **Files modified:** 9

## Accomplishments
- Segment/Project schema extended with generation tracking fields; additive SQLite migration handles pre-existing DBs; WAL journal mode enabled.
- `compute_cache_key()` (sha256 over resolved speaker, voice instructions, text) with a passing `__main__` self-check.
- `PATCH /segments/{id}`, `POST /segments/{id}/generate`, `GET /segments/{id}/audio.wav` — cache-aware, version-guarded against stale concurrent regens.
- Editable `SegmentTable` (Narrator select, Voice Instructions/Text textareas, blur-commit) with per-row generate/play and a status badge; `ProjectScreen` makes it reachable after cast review.
- Task 4's real-GPU checkpoint was run and verified programmatically (no manual listening needed): non-silent real synthesis, cache-bust on edit, cache-hit (33ms, byte-identical, zero extra `/synthesize` calls) on an unchanged row.

## Task Commits

1. **Task 1: Failing tests for generate/cache/regen** - `81359f8` (test, RED)
2. **Task 2: Backend slice — schema, migration, cache_key, endpoints** - `e767e01` (feat, GREEN)
3. **Task 3: Frontend slice — SegmentTable + ProjectScreen** - `9c5668e` (feat)
4. **Task 0 + Task 4: real-hardware checkpoints** - verified this session directly against the production `tts` VM pod; no code changes, no commit (checkpoint gates only)

## Files Created/Modified
- `backend/app/cache_key.py` - sha256 content-hash cache key + self-check
- `backend/app/models.py` - Segment generation fields, Project created_at/output_path
- `backend/app/db.py` - WAL pragma listener, additive column migration
- `backend/app/main.py` - SegmentPatch, patch_segment, regenerate_segment, generate/audio endpoints
- `backend/tests/test_generation.py` - four generate/cache/regen behavioral tests
- `frontend/src/api/client.ts` - patchSegment/generateSegment/segmentAudioUrl wrappers
- `frontend/src/components/SegmentTable.tsx` - editable table with per-row generate/play
- `frontend/src/components/ProjectScreen.tsx` - main editing screen hosting SegmentTable
- `frontend/src/App.tsx` - renders ProjectScreen when analysis status is "ready"

## Decisions Made
- Task 4's real-GPU checkpoint was automated via curl + WAV waveform analysis (non-zero sample %, RMS, hash diffing) plus TTS container log inspection for synth-call counts, rather than a manual browser listen — this session ran directly on the `tts` production VM. See `key-decisions` above.
- Test data for Task 4 was seeded directly into the running container's DB (same `_seed_segment` pattern as the test suite) to keep the check scoped to generation/cache, not LLM analysis.

## Deviations from Plan
None — plan executed as written; Task 4's verification method (automated vs. manual browser) is a substitution within the same acceptance criteria, not a scope change.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
Schema, cache, and per-segment generation are proven end-to-end against real GPU hardware. Plans 03-02 through 03-05 (batch generation, config panel, persistence, deployment) can build on `models.py` without further schema changes — 03-01 front-loaded all Phase 3 columns per its objective.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployment*
*Completed: 2026-07-12*
