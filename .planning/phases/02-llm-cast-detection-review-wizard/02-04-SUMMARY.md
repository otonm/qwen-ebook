---
phase: 02-llm-cast-detection-review-wizard
plan: 04
subsystem: api
tags: [fastapi, sqlmodel, wizard, tts, preview, race-condition]

# Dependency graph
requires:
  - phase: 02-llm-cast-detection-review-wizard (plan 01/02/03)
    provides: Project/Character/Segment persistence, background analysis pipeline, tts_client.synthesize() from Phase 1
provides:
  - "GET /voices — preset voice list for the wizard's picker"
  - "PATCH /characters/{id} — rename/edit/voice-assign, persisted"
  - "POST /characters/{id}/merge — reassign segments, delete source"
  - "GET /characters/{id}/preview.wav — serves the eagerly-generated preview"
  - "Eager, race-safe voice-preview generation on voice assignment (Pitfall 5 guard)"
affects: [02-05 (wizard frontend consumes these endpoints)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "voice_version integer stamp + fresh-Session reload for last-request-wins race resolution on a fire-and-forget asyncio.create_task background job"
    - "TestClient(app).__enter__() (persistent portal) instead of bare TestClient(app) for tests that exercise a fire-and-forget background task with a real run_in_threadpool cross-thread hop"

key-files:
  created: [backend/app/voices.py, backend/tests/test_wizard_endpoints.py]
  modified: [backend/app/main.py, backend/app/models.py, backend/app/config.py]

key-decisions:
  - "PRESET_VOICES ships a single known-default entry (empty-string speaker, same convention as TTS_DEFAULT_SPEAKER) instead of a guessed/hallucinated preset roster — no prior Phase 1 doc or log ever enumerated get_supported_speakers()' real output, and this dev/CI environment has no GPU to call it. Documented as a ponytail-flagged ceiling with a clear upgrade path (a /voices proxy to the TTS container)."
  - "Free-text voice_instructions steering resolves to a preset via best_guess_preset() at generation time rather than a real per-request instruct parameter, because Phase 1's locked /synthesize wire contract (backend/tts_service/server.py) only accepts {text, speaker} — there is no instruct-steering parameter to send even though D-17 describes this phase as shipping free-text steering 'on the same TTS surface as Phase 1's client'."
  - "Guarded merge against source_id == target_id (400) — not in the plan text, but a self-merge would delete the only copy of a character via the existing 'delete source' step, a silent data-loss footgun for one stray double-click."

requirements-completed: [WIZ-02, WIZ-03, WIZ-04, WIZ-05]

coverage:
  - id: D1
    description: "PATCH /characters/{id} persists name/description/voice_preset/voice_instructions changes"
    requirement: "WIZ-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_patch_character_renames_and_persists"
        status: pass
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_patch_character_edits_description_and_persists"
        status: pass
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_patch_character_assigns_voice_and_persists"
        status: pass
    human_judgment: false
  - id: D2
    description: "POST /characters/{id}/merge reassigns segments to target, deletes source, preserves total segment count"
    requirement: "WIZ-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_merge_reassigns_segments_and_deletes_source"
        status: pass
    human_judgment: false
  - id: D3
    description: "GET /voices returns a non-empty preset list"
    requirement: "WIZ-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_voices_returns_nonempty_preset_list"
        status: pass
    human_judgment: false
  - id: D4
    description: "Assigning a voice via PATCH eagerly generates a preview (no separate generate call needed); GET /characters/{id}/preview.wav serves it once ready, 409 while pending"
    requirement: "WIZ-04"
    verification:
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_preview_not_ready_returns_409"
        status: pass
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_patch_voice_eagerly_generates_preview"
        status: pass
    human_judgment: false
  - id: D5
    description: "A rapid re-assignment does not leave a stale preview: last-assignment-wins via a per-character voice_version stamp (Pitfall 5)"
    requirement: "WIZ-05"
    verification:
      - kind: unit
        ref: "backend/tests/test_wizard_endpoints.py#test_rapid_reassignment_race_last_wins"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-10
status: complete
---

# Phase 02 Plan 04: Wizard character edit/merge + eager race-safe voice preview Summary

**PATCH/merge character endpoints, a `/voices` preset list, and eager voice-preview generation guarded by a `voice_version` stamp so a rapid re-assignment can never leave a stale preview served.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-10
- **Tasks:** 2 (both TDD: RED test commit -> GREEN implementation commit)
- **Files modified:** 5 (1 new module, 1 new test file, 3 modified)

## Accomplishments

- `backend/app/voices.py`: `PRESET_VOICES`, `list_presets()`, `best_guess_preset(description)` (D-16 best-guess pick)
- `PATCH /characters/{id}`: partial rename/description/voice-assign, persisted (WIZ-02, WIZ-03)
- `POST /characters/{id}/merge`: reassigns source's segments to target, deletes source, 404s on missing/cross-project ids, 400s on self-merge (WIZ-02)
- `GET /voices`: preset list for the wizard's dropdown (WIZ-03)
- Eager preview generation: a voice-field PATCH bumps `Character.voice_version`, schedules a background `_generate_preview()` task that synthesizes the WIZ-04 intro line via `run_in_threadpool(tts_client.synthesize)`, writes `PREVIEW_DIR/<uuid4>.wav`, and only writes `preview_audio_path` back if `voice_version` still matches (Pitfall 5 last-request-wins)
- `GET /characters/{id}/preview.wav`: 200 `audio/wav` once ready, 409 while pending
- `backend/tests/test_wizard_endpoints.py`: 10 tests covering all of the above, including a controllable slow-then-fast race test that proves the last-wins guard

## Task Commits

Both tasks followed RED (failing test) -> GREEN (implementation) TDD gates:

1. **Task 1: Preset voice list + best-guess pick + wizard mutation endpoints**
   - `bdb611a` test(02-04): add failing wizard endpoint tests (voices/patch/merge) — RED
   - `5adcb88` feat(02-04): preset voice list + wizard character edit/merge endpoints — GREEN
2. **Task 2: Eager, race-safe voice-preview generation + serving**
   - `b35f11e` test(02-04): add failing eager preview generation + race tests — RED
   - `0cb82bb` feat(02-04): eager race-safe voice-preview generation + serving — GREEN

## Files Created/Modified

- `backend/app/voices.py` — preset voice roster + `list_presets()`/`best_guess_preset()` (new)
- `backend/app/models.py` — added `Character.voice_version: int = 0`
- `backend/app/config.py` — added `Settings.PREVIEW_DIR` (default `{OUTPUT_DIR}/previews`, `PREVIEW_DIR` env override)
- `backend/app/main.py` — `GET /voices`, `PATCH /characters/{id}`, `POST /characters/{id}/merge`, `GET /characters/{id}/preview.wav`, `_generate_preview()` background task, `_serialize_character()` helper (extracted from `_serialize_project`)
- `backend/tests/test_wizard_endpoints.py` — 10 tests (new)

## Decisions Made

- **PRESET_VOICES ceiling:** Seeded with a single known-default entry (`{"name": "", "label": "Default narrator (auto-selected)"}`) rather than a guessed preset roster, since neither this environment nor any prior Phase 1 artifact ever enumerated `model.get_supported_speakers()`'s real output (02-RESEARCH.md Open Question 2 was left open, not resolved). The empty-string speaker value reuses the same "empty means let the container pick its default" convention `TTS_DEFAULT_SPEAKER` already established in `config.py`. Documented as a `# ponytail:` comment with the upgrade path (a `/voices` proxy to the real TTS container) rather than inventing plausible-sounding preset names.
- **Free-text instruction "steering":** Phase 1's locked `/synthesize` wire contract (`backend/tts_service/server.py`) only accepts `{text, speaker}` — there is no instruct-steering parameter on the wire, despite D-17 describing this phase's free-text steering as being on "the same TTS surface as Phase 1's client." Resolved this by having `_generate_preview()` fall back to `best_guess_preset(voice_instructions)` when no explicit `voice_preset` is set — the free-text description influences which preset gets used, rather than being sent as real per-request instruct text (which the deployed TTS surface can't accept). Flagged inline; VoiceDesign (real instruct-steering) is explicitly deferred out of Phase 2 by D-17 already.
- **Test harness fix:** `test_wizard_endpoints.py` calls `client.__enter__()` on its module-level `TestClient(app)` (unlike every other test module in this repo, which use the bare constructor). This was required, not stylistic — Starlette's `TestClient` spins up a brand-new portal/event loop per call unless `__enter__`'d, and the fire-and-forget `_generate_preview()` background task does a genuine cross-thread `run_in_threadpool` hop; without a persistent portal, that hop's event loop gets torn down mid-flight the instant the triggering PATCH request returns, permanently orphaning the task. Confirmed via a manual repro before applying the fix (see Issues Encountered).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Guarded `POST /characters/{id}/merge` against `source_id == target_id`**
- **Found during:** Task 1 (merge endpoint implementation)
- **Issue:** The plan's merge logic (reassign segments, then delete source) silently destroys the character entirely if a caller passes the same id as both source and target — a self-merge would reassign a character's segments to itself (no-op) and then delete it, losing the character.
- **Fix:** Added a `400 "Cannot merge a character into itself"` guard before any mutation.
- **Files modified:** `backend/app/main.py`
- **Verification:** Covered implicitly by the existing merge test suite passing; no dedicated test added (single-line guard, not exercised by a distinct scenario in this plan's acceptance criteria).
- **Committed in:** `5adcb88` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical / input validation)
**Impact on plan:** Necessary correctness guard against silent data loss on a plausible client bug; no scope creep — everything else in the plan's `must_haves`/acceptance criteria was implemented as written.

## Issues Encountered

- **Eager background task never completed under the default `TestClient`.** Initial implementation of Task 2 passed all Task 1 tests but the new preview tests hung/timed out: `PATCH` returned 200, but the background `_generate_preview()` task never progressed past its first `run_in_threadpool` await. Root-caused via a manual repro script with debug wrappers: Starlette's `TestClient`, when not entered as a context manager, spins up a brand-new `anyio.from_thread.start_blocking_portal()` (and its event loop) for every single HTTP call and tears it down the instant that call's response is sent. `run_analysis`'s existing background task (Plan 02-01) happens to dodge this because its mock path never crosses a real thread boundary (no `run_in_threadpool` call), so it completes within the same event-loop tick sequence before the portal closes. `_generate_preview()`'s `run_in_threadpool(tts_client.synthesize, ...)` does a real thread hop, so it needs the portal's loop to still be running when the thread's result comes back — which it isn't, under the bare-`TestClient()` pattern the other test modules use. Fixed by calling `client.__enter__()` on this module's `TestClient` instance so its portal (and event loop) persists across every call in the module, confirmed with a standalone repro before and after the fix.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The wizard's full backend surface (character edit/merge/voice-assign, preset list, eager race-safe preview) is in place and tested against the mock LLM/TTS backends — ready for Plan 05's React frontend to consume.
- `PRESET_VOICES` currently ships only one entry (the documented ceiling). Once the app is actually run against the real GPU TTS container, a follow-up should enumerate `model.get_supported_speakers()`'s real output and either hardcode the full roster or add a `/voices` proxy to the TTS service, per the `# ponytail:` note in `voices.py`.
- Free-text `voice_instructions` currently only influences preset *selection* (via `best_guess_preset`), not real per-request TTS steering — this matches Phase 1's locked wire contract and D-17's deferral of VoiceDesign, but is worth flagging if a future UAT pass expects the free-text field to audibly change delivery beyond preset choice.

---
*Phase: 02-llm-cast-detection-review-wizard*
*Completed: 2026-07-10*
