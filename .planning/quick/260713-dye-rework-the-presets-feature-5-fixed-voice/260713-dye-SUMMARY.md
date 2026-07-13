---
quick_task: 260713-dye
subsystem: ai
tags: [voice-presets, qwen-tts, openrouter, structured-output, fastapi]

key-files:
  created: []
  modified:
    - backend/app/voices.py
    - backend/app/schemas.py
    - backend/app/analysis_client.py
    - backend/app/analysis_worker.py
    - backend/app/main.py
    - backend/tests/test_analysis_pipeline.py
    - backend/tests/test_analysis_reconciliation.py
    - backend/tests/test_generation.py

key-decisions:
  - "5 fixed presets replace the 10 raw-speaker-id roster; each has a fleshed-out 2-3 sentence steering description the LLM adapts per character, not a generic label"
  - "voice_preset is now a required Pydantic Literal on CharacterSuggestion (OpenRouter strict json_schema enforces a valid pick) instead of an absent/free-text field"
  - "Character.voice_preset stores a preset ID, not a raw Qwen speaker name — preset_speaker() is the single resolution point at both TTS synth call sites"
  - "regenerate_segment now merges character.voice_instructions (adapted base) + segment.voice_instructions (delivery) via merge_instructions() into the final instruct AND feeds that merged string into compute_cache_key(), so a character base-voice edit naturally busts the segment cache"
  - "Narration segments are contractually empty voice_instructions (delivery is dialogue-only); test_analysis_pipeline.py's blanket per-segment non-empty assertion was relaxed to any-empty + any-non-empty"

# Metrics
duration: ~35min
completed: 2026-07-13
status: tasks-1-4-complete-checkpoint-pending
---

# Quick Task 260713-dye: Rework the presets feature — 5 fixed voice personas Summary

**5 curated Qwen CustomVoice presets (with fleshed-out steering descriptions) that the analysis LLM now casts from and adapts per character via a required `voice_preset` schema field, plus a merge of the character's adapted base voice with each dialogue segment's own delivery instruction at TTS synth time.**

## Performance

- **Started:** 2026-07-13T07:41:00Z (approx, worktree base commit 961bdec)
- **Completed (tasks 1-4):** 2026-07-13T08:16:51Z
- **Tasks:** 4 of 5 (tasks 1-4 `type="auto"` complete; task 5 is `type="checkpoint:human-verify" gate="blocking"` — NOT executed, see below)
- **Files modified:** 8

## Accomplishments

- **Task 1 — `backend/app/voices.py`:** replaced the 10-speaker roster with exactly 5 fixed personas (`narrator_sultry_woman` [default], `middle_sultry_woman`, `playful_student`, `bright_young_guy`, `reassuring_young_man`), each carrying a `speaker` (Qwen CustomVoice speaker id, best-effort timbre match) and a `description` (steering prompt). Added `preset_speaker()`, `preset_description()`, `merge_instructions()`; reworked `best_guess_preset()` to map onto the 5 new ids and fall back to the default preset. Extended the module's assert-based self-check.
- **Task 2 — schema + prompt:** `CharacterSuggestion.voice_preset` is now a required `Literal` over the 5 preset ids; `CAST_ANALYSIS_SYSTEM_PROMPT` is rebuilt to list the 5 presets (rendered live from `voices.preset_description()` so the prompt can't drift from the roster), instructs pick-then-adapt casting, a narrator-default-unless-clearly-a-character rule, and a dialogue-only `voice_instructions` contract (narration = `""`). The mock path's `_MOCK_NARRATOR`/`_MOCK_CHARACTER` now set `voice_preset`, and mock narration segments carry empty `voice_instructions`. `analysis_worker.py` persists `suggestion.voice_preset` onto the created `Character`.
- **Task 3 — `backend/app/main.py` merge points:** `_generate_preview` and `_resolve_segment_speaker` now resolve `Character.voice_preset` (a preset id) through `preset_speaker()` before passing it to `synthesize()`. `regenerate_segment` is the merge point: it builds `merge_instructions(character.voice_instructions, segment.voice_instructions)` and passes that merged string as both the synth `instruct` and the `compute_cache_key()` voice-instructions field. `_generate_preview` is unchanged at the instruct level — it still uses only the character's own base voice.
- **Task 4 — tests:** updated `test_analysis_pipeline.py` (narration segments allowed empty `voice_instructions`; every character now asserted to have a non-empty `voice_preset`), `test_analysis_reconciliation.py` (every `CharacterSuggestion(...)` construction now supplies `voice_preset`), and `test_generation.py` (the reassign-to-different-voice regression test's seed character now uses the real preset id `bright_young_guy` instead of the stale raw speaker id `"ryan"`, which is no longer a recognized preset and was silently resolving to the same default speaker as the unset narrator — masking the regression the test exists to catch). Full backend suite run; ruff strict (`E,F,I,UP,B`) clean across all touched files.

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace the preset roster with 5 fixed personas + add resolver and merge helpers** - `e5089df` (feat)
2. **Task 2: LLM schema + prompt — cast from the 5 presets, dialogue-only segment instructions** - `326243f` (feat)
3. **Task 3: Merge character base + segment delivery at the two TTS synth call sites** - `50a87a1` (feat)
4. **Task 4: Update the backend tests that assumed the old preset roster / all-segments-have-instructions** - `14b937b` (test)

No separate plan-metadata commit was made — per this task's execution constraints, SUMMARY.md/STATE.md/PLAN.md are docs artifacts the orchestrator commits in its own step.

## Files Created/Modified

- `backend/app/voices.py` - 5 fixed presets + `preset_speaker()`/`preset_description()`/`merge_instructions()` + reworked `best_guess_preset()`
- `backend/app/schemas.py` - `CharacterSuggestion.voice_preset: Literal[...]` (required), `SegmentSuggestion.voice_instructions` contract updated to dialogue-only
- `backend/app/analysis_client.py` - prompt rebuilt from `voices.preset_description()`; mock constants set `voice_preset`; narrator mock segments empty
- `backend/app/analysis_worker.py` - persists `suggestion.voice_preset` onto the created `Character`
- `backend/app/main.py` - `_generate_preview`/`_resolve_segment_speaker` resolve via `preset_speaker()`; `regenerate_segment` merges base+delivery via `merge_instructions()` for both synth `instruct` and `compute_cache_key`
- `backend/tests/test_analysis_pipeline.py` - dialogue-only segment-instruction assertion, non-empty `voice_preset` per character
- `backend/tests/test_analysis_reconciliation.py` - `voice_preset` added to every `CharacterSuggestion(...)` construction
- `backend/tests/test_generation.py` - seed character preset id `"ryan"` → `"bright_young_guy"`

## Decisions Made

- Kept the 5 preset ids as a duplicated `Literal` in `schemas.py` (not imported from `voices.py`) so the Pydantic contract stays dependency-free for OpenRouter's `json_schema` payload; `analysis_client.py` is the single place responsible for keeping the prompt's rendered preset list in sync with `voices.PRESET_VOICES` (via `preset_description()`).
- `_generate_preview`'s "auto" fallback (`voice_preset` falsy → `best_guess_preset()` → `preset_speaker()`) was kept as two explicit resolution steps rather than collapsing into one helper, matching `_resolve_segment_speaker`'s existing shape — no new abstraction introduced for a single call site's convenience.
- No SQLModel migration and no frontend code change were made, per the plan's explicit scope notes — `Character.voice_preset`/`voice_instructions`/`description` and `Segment.voice_instructions` already existed, and the wizard's preset dropdown / segment Voice Instructions cell are data-driven off `/voices` and the segment field.

## Deviations from Plan

None - plan executed exactly as written for Tasks 1-4.

## Issues Encountered

- **Environmental, not caused by this task's changes:** `tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined` fails in this sandbox because an unrelated live backend process (`uvicorn app.main:app` on `127.0.0.1:8000`, a different working tree/session per `ps aux`) makes the test's `requires_pod` reachability probe succeed, so the real-pod integration test runs instead of being skipped — and fails on that external process's own state (`201 != 200` on a multi-chunk upload), not on anything this plan touched. Logged in `deferred-items.md` in this quick-task's directory per the scope-boundary rule (pre-existing/out-of-scope, not fixed).
- The `test_batch_regenerates_after_reassign_to_different_voice` test initially failed too, but for a real reason directly caused by this rework and explicitly anticipated by the plan: its seed character used the old raw speaker id `"ryan"` as a stand-in preset value, which is no longer a recognized preset after Task 1 and silently fell back to the same default speaker as the untouched narrator — masking the very regression the test exists to catch. Fixed in Task 4 by switching the seed to a real preset id (`bright_young_guy`), which now genuinely differs from the narrator's default and lets the test correctly observe a speaker/cache-key change.

## User Setup Required

None - no external service configuration required. Task 5's checkpoint (below) requires a real `OPENROUTER_API_KEY` for manual verification, but no new setup beyond what the project already needs.

## Checkpoint Pending — Human Verification Required (Task 5)

The plan's final task is `type="checkpoint:human-verify" gate="blocking"` and requires starting the app, running a real-key LLM analysis, and listening to generated audio in the UI. This cannot be performed by a non-interactive agent and was **not executed**. Per this quick task's execution constraints, tasks 1-4 (all `type="auto"`) were run fully, including the full backend pytest suite and ruff — the checkpoint itself is reported here, not guessed at.

**What a human needs to do to complete verification** (from the plan's `<how-to-verify>`):

1. Start the app (backend + frontend) as usual for this project.
2. Analyze a short multi-character text with a real `OPENROUTER_API_KEY` set (`LLM_BACKEND != mock`). In the Cast wizard, confirm: each detected character shows one of the 5 new presets, and the narrator shows the default "young sultry woman" preset unless it is clearly a specific character's voice.
3. Open the segment table: narration rows should have an EMPTY Voice Instructions cell; dialogue rows should have a short per-line delivery instruction.
4. Generate/preview a dialogue segment and a narration segment. Confirm the dialogue voice reflects BOTH the character's persona and the line's delivery (e.g. a whispered/excited line sounds different from the character's neutral preview), and narration uses the narrator's base voice.
5. Confirm the 5 preset personas sound distinct enough to be usable; if a preset's underlying Qwen speaker is a poor timbre match, note it — the speaker mapping in `backend/app/voices.py`'s `PRESET_VOICES` list is the tunable knob (the `instruct` steering does the rest, per the `# ponytail:` comment in that file).

**Resume signal:** Type "approved" or describe issues (e.g. a preset that needs a different underlying speaker, or narration still getting delivery instructions).

## Next Phase Readiness

- Backend implementation and all automated verification (full pytest suite, ruff strict, `python -m app.voices` self-check) is complete and green (excluding the one documented environmental integration-test failure, unrelated to this rework).
- Not yet ready to close this quick task: the real-key manual UAT checkpoint above is outstanding and requires a human with `OPENROUTER_API_KEY` access and the ability to listen to generated audio.

---
*Quick task: 260713-dye*
*Status: Tasks 1-4 complete; Task 5 (checkpoint:human-verify, blocking) pending human action*

## Self-Check: PASSED

All 8 modified source/test files and this SUMMARY.md verified present on disk; all 4 task commit hashes (`e5089df`, `326243f`, `50a87a1`, `14b937b`) verified present in git log.
