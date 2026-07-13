---
phase: quick-260713-dye
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/voices.py
  - backend/app/schemas.py
  - backend/app/analysis_client.py
  - backend/app/analysis_worker.py
  - backend/app/main.py
  - backend/tests/test_wizard_endpoints.py
  - backend/tests/test_generation.py
  - backend/tests/test_analysis_pipeline.py
autonomous: false
requirements: [PRESET-REWORK]
must_haves:
  truths:
    - "GET /voices returns exactly 5 fixed presets, each with a fleshed-out steering description."
    - "The analysis LLM picks one of the 5 presets per character and stores an adapted description as that character's base voice instructions."
    - "Narration segments carry NO per-segment voice instruction; dialogue segments each carry a short delivery instruction."
    - "At segment TTS time the character's adapted base description is MERGED with the segment's delivery instruction into the final instruct string."
    - "The narrator falls back to the default preset (young sultry woman) unless the LLM identifies a specific first/third-person character voice."
  artifacts:
    - backend/app/voices.py
    - backend/app/schemas.py
    - backend/app/analysis_client.py
    - backend/app/main.py
  key_links:
    - "CharacterSuggestion.voice_preset (LLM pick) -> Character.voice_preset -> preset_speaker() -> synthesize(speaker=...)"
    - "Character.voice_instructions (adapted base) + Segment.voice_instructions (delivery) -> merge_instructions() -> synthesize(instruct=...) -> compute_cache_key()"
---

<objective>
Rework the voice-preset feature into 5 fixed personas that the analysis LLM
adapts per character, with per-dialogue-segment delivery instructions that
merge with the character's adapted preset at TTS time.

Purpose: The current 10 presets are raw Qwen speaker IDs with generic labels;
the LLM invents free-form descriptions and never picks a preset, and at segment
generation only the segment's own short instruction steers TTS — the character's
base voice is dropped. The user wants a small fixed persona set the LLM casts
from and adapts, plus per-line delivery merged onto the character's base voice.

Output: 5 curated presets with steering descriptions; a `voice_preset` enum on
the LLM character schema; a rewritten analysis prompt; and a merge at the two
synth call sites so the final `instruct` = adapted character base + per-segment
delivery.

Scope notes (rework, not rebuild):
- NO SQLModel/schema migration. `Character.voice_preset/voice_instructions/
  description` and `Segment.voice_instructions` all already exist (commit
  f51f748). Reuse them.
- NO frontend code change. The preset dropdown (CharacterCard) and the segment
  Voice Instructions cell (SegmentTable) are data-driven off `/voices` and the
  segment field — they pick up the new presets automatically. Manual UAT only.
- NO preset config UI. The 5 presets are hardcoded constants.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
</execution_context>

<context>
@CLAUDE.md
@backend/app/voices.py
@backend/app/schemas.py
@backend/app/analysis_client.py
@backend/app/analysis_worker.py
@backend/app/main.py
@backend/app/cache_key.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Replace the preset roster with 5 fixed personas + add resolver and merge helpers</name>
  <files>backend/app/voices.py</files>
  <action>
Replace PRESET_VOICES with exactly 5 fixed presets. Each entry keeps the
existing dict shape but gains a `speaker` (the underlying Qwen CustomVoice
speaker name that actually drives timbre) and a `description` (a 2-3 sentence
fleshed-out steering prompt in the same register as the existing
CharacterSuggestion.description guidance — age, gender, vocal tone/register,
pace, emotional demeanor only; no plot/occupation). The 5 presets, in order,
with their `name` (stable id, snake_case), label, and persona:
  1. name "narrator_sultry_woman" — young woman, deep sultry voice. This is the
     DEFAULT preset (used when nothing is selected AND as the general narrator
     fallback voice).
  2. name "middle_sultry_woman" — middle-aged woman, sultry voice.
  3. name "playful_student" — 19-year-old student, youthful playful bright tone.
  4. name "bright_young_guy" — young guy, bright tone, positive attitude.
  5. name "reassuring_young_man" — young man, deep reassuring voice.

Map each preset's `speaker` to one of the confirmed Qwen speakers already
documented in this file's roster (female: serena, vivian, sohee, ono_anna;
male: aiden, dylan, eric, ryan, uncle_fu). Pick the closest-timbre match per
persona (e.g. a deeper mature female for the sultry-woman presets, a young
female for the student, distinct young-male speakers for the two male presets).
Add a `# ponytail:` comment noting the speaker choice is best-effort timbre
matching — the wizard preview is the source of truth and `instruct` steering
(commit f51f748) is the real lever, so re-map from listening rather than
guessing harder.

Add three module functions:
  - `preset_speaker(preset_id: str) -> str`: return the Qwen `speaker` for a
    preset id; for the empty-string / unknown case return the DEFAULT preset's
    speaker (narrator_sultry_woman). This is what the synth call sites pass to
    tts_client.synthesize().
  - `preset_description(preset_id: str) -> str`: return a preset's steering
    description (used to build the analysis prompt).
  - `merge_instructions(base: str, delivery: str) -> str`: combine the
    character's adapted base description with a segment's delivery instruction
    into one instruct string. Join the non-empty parts with ". " (so narration,
    which has an empty delivery, yields just the base; a dialogue line yields
    base + delivery). Strip and skip empties so no stray separators appear.

Keep `list_presets()` returning name+label only (the dropdown contract is
unchanged). Rework `best_guess_preset` so its keyword tuples map to the 5 new
preset ids and it falls back to the DEFAULT preset id (narrator_sultry_woman) —
it stays the fallback for manually-added / empty-preset characters. Keep the
existing DEFAULT_SPEAKER note accurate.

Keep the existing `if __name__ == "__main__"` self-check discipline: extend the
module with a small assert-based self-check for `merge_instructions`
(base+delivery merges both; empty delivery yields base only; empty base yields
delivery only) and `preset_speaker("")` returning the default speaker.

Follow CLAUDE.md: ruff strict (E,F,I,UP,B), f-strings, logging not print, no
noqa, no new abstractions beyond these functions.
  </action>
  <verify>
    <automated>cd backend && uv run python -m app.voices && uv run ruff check app/voices.py</automated>
  </verify>
  <done>PRESET_VOICES has exactly 5 entries each with name/label/keywords/speaker/description; preset_speaker/preset_description/merge_instructions exist; best_guess_preset returns one of the 5 ids; self-check passes; ruff clean.</done>
</task>

<task type="auto">
  <name>Task 2: LLM schema + prompt — cast from the 5 presets, dialogue-only segment instructions</name>
  <files>backend/app/schemas.py, backend/app/analysis_client.py, backend/app/analysis_worker.py</files>
  <action>
schemas.py — add a required `voice_preset` field to CharacterSuggestion typed
as a `Literal[...]` of the 5 preset ids (narrator_sultry_woman,
middle_sultry_woman, playful_student, bright_young_guy, reassuring_young_man).
Its Field description: "The closest-matching fixed voice preset for this
character." Keep `description` as the adapted, per-character voice description.
The Literal makes the OpenRouter strict json_schema enforce a valid pick.

For SegmentSuggestion.voice_instructions: keep the field but make its contract
"empty string for narration segments; a short spoken-delivery direction for a
single dialogue line" — update the Field description accordingly. Do not make it
Optional; an empty string is the narration sentinel (keeps DB column non-null).

analysis_client.py — rewrite CAST_ANALYSIS_SYSTEM_PROMPT so it:
  1. Lists the 5 fixed presets with their ids and descriptions (build this block
     from voices.py's preset_description() so the prompt and the constants can't
     drift). Instruct: for each character, pick the closest-matching preset id
     as `voice_preset`, then ADAPT that preset's description to the character's
     specifics from the text (e.g. shy vs. playful girl, teenager vs. mid-20s
     man) and put the adapted result in `description`.
  2. Narrator handling: assign the narrator the DEFAULT preset
     (narrator_sultry_woman) UNLESS the narration is clearly a specific
     character's first- or third-person voice, in which case pick/adapt the
     matching preset.
  3. Segment instructions: ONLY dialogue segments get a short `voice_instructions`
     delivery direction (tone/pace/volume/emotional inflection for that line,
     e.g. "whispers", "in a happy tone, getting more excited", "scared, voice
     trembling"). Narration segments MUST have an empty `voice_instructions`
     string. Keep the existing anti-injection / no-scene-description guidance.
  4. Keep the existing running_cast / recent_segments continuity rules intact.

Update the mock path (_mock_analyze and the module's _MOCK_* / _INSTRUCTIONS
constants): give _MOCK_NARRATOR voice_preset="narrator_sultry_woman" and
_MOCK_CHARACTER a different preset id (e.g. "playful_student"); make the
narrator's mock segments carry an EMPTY voice_instructions and only the
character segments carry a delivery instruction, matching the new dialogue-only
contract. (CharacterSuggestion now requires voice_preset, so the mock
constants must set it or import fails.)

analysis_worker.py — persist the LLM pick: set
`voice_preset=suggestion.voice_preset` on the created Character (replacing the
current unset/None-then-best_guess behavior for analyzed characters), and keep
`voice_instructions=suggestion.description` (the adapted base). Update the
inline comment that currently says CharacterSuggestion carries no preset field.

Follow CLAUDE.md conventions. Run ruff.
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.analysis_client import _mock_analyze; r=_mock_analyze('a\n\nb\n\nc'); assert all(c.voice_preset for c in r.characters); assert any(s.voice_instructions=='' for s in r.segments) and any(s.voice_instructions for s in r.segments), r" && uv run ruff check app/schemas.py app/analysis_client.py app/analysis_worker.py</automated>
  </verify>
  <done>CharacterSuggestion has a required Literal voice_preset over the 5 ids; the prompt lists the 5 presets (built from preset_description) and instructs pick+adapt, narrator-default, and dialogue-only segment instructions; the mock sets voice_preset on both characters and leaves narrator segments' voice_instructions empty; analysis_worker persists suggestion.voice_preset; ruff clean.</done>
</task>

<task type="auto">
  <name>Task 3: Merge character base + segment delivery at the two TTS synth call sites</name>
  <files>backend/app/main.py</files>
  <action>
Two synth call sites resolve speaker + instruct. Update both to use the new
preset resolver and the merge helper (import preset_speaker and
merge_instructions from app.voices alongside the existing best_guess_preset /
list_presets imports).

`_resolve_segment_speaker` (and `_generate_preview`'s inline speaker resolution):
`Character.voice_preset` now stores a preset ID, not a raw Qwen speaker name, so
the value can no longer be passed straight to synthesize(). Resolve it through
`preset_speaker(...)`. Keep the existing empty/auto fallback: when
voice_preset is falsy, use best_guess_preset(...) (which now returns a preset
id) and resolve that through preset_speaker() too. Net effect: the value handed
to tts_client.synthesize(speaker=...) is always a real Qwen speaker name.

`regenerate_segment` — this is the required MERGE point. Today it passes ONLY
`segment.voice_instructions` as instruct, dropping the character's base voice.
Change it to build the final instruct via
`merge_instructions(character.voice_instructions, segment.voice_instructions)`
(character adapted base + this line's delivery). For a narration segment the
segment delivery is empty, so the merge yields just the narrator's base — no
special-casing needed. Pass this merged string as the `instruct` arg to
synthesize AND as the voice_instructions arg to compute_cache_key(...), so a
change to the character's base voice naturally busts the segment cache (it
currently would not, since only the segment field was hashed).

`_generate_preview` is the CHARACTER-level preview: it should keep using the
character's own base (character.voice_instructions) as instruct — no segment to
merge — so only its speaker resolution changes (preset_speaker). Do not merge
anything extra into the preview.

Follow CLAUDE.md: f-strings, logging (the existing logger) not print, ruff
strict, no noqa.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/main.py</automated>
  </verify>
  <done>Both synth sites resolve speaker via preset_speaker(); regenerate_segment passes merge_instructions(character base, segment delivery) as both the synth instruct and the compute_cache_key voice_instructions arg; _generate_preview still uses the character's base as instruct; ruff clean.</done>
</task>

<task type="auto">
  <name>Task 4: Update the backend tests that assumed the old preset roster / all-segments-have-instructions</name>
  <files>backend/tests/test_wizard_endpoints.py, backend/tests/test_generation.py, backend/tests/test_analysis_pipeline.py</files>
  <action>
The preset rework changes three test-visible contracts; update the affected
assertions (do NOT weaken a real check — align it to the new intended behavior):
  - test_wizard_endpoints.py GET /voices test: now expects 5 presets. Any
    hardcoded old speaker id (e.g. a `voice_preset="ryan"` / `"different"` used
    as a stand-in preset value) must become one of the 5 new preset ids, since
    Character.voice_preset is now a preset id resolved through preset_speaker().
  - test_generation.py: any seed using `voice_preset="ryan"` (line ~526) or an
    old speaker id must switch to a new preset id; if a test asserts the exact
    instruct passed to synthesize for a dialogue segment, update the expectation
    to the MERGED string (character base + segment delivery) rather than the
    segment instruction alone.
  - test_analysis_pipeline.py: keep the existing "characters get a non-empty
    voice_instructions/description" check; add/adjust so a narration segment is
    allowed to have an empty voice_instructions (the dialogue-only contract) and
    every character has a non-empty voice_preset.

Run the FULL backend suite and fix any other fallout the rework surfaces (e.g.
imports of removed speaker ids). Test files may use noqa freely per CLAUDE.md.
  </action>
  <verify>
    <automated>cd backend && uv run pytest -q</automated>
  </verify>
  <done>Full backend pytest suite passes with the new 5-preset roster, LLM voice_preset field, dialogue-only segment instructions, and merged-instruct generation.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
5 fixed voice presets the analysis LLM casts from and adapts per character,
per-dialogue-segment delivery instructions, and a TTS merge so each spoken
segment is steered by (adapted character base + that line's delivery). Frontend
is data-driven and unchanged — the preset dropdown and segment instruction cell
pick this up automatically.
  </what-built>
  <how-to-verify>
1. Start the app (backend + frontend) as usual for this project.
2. Analyze a short multi-character text with a real OPENROUTER_API_KEY
   (LLM_BACKEND != mock). In the Cast wizard confirm: each detected character
   shows one of the 5 presets, and the narrator shows the default
   "young sultry woman" preset unless it is clearly a specific character voice.
3. Open the segment table: narration rows have an EMPTY Voice Instructions cell;
   dialogue rows have a short per-line delivery instruction.
4. Generate/preview a dialogue segment and a narration segment. Confirm the
   dialogue voice reflects BOTH the character's persona and the line's delivery
   (e.g. a whispered/excited line sounds different from the character's neutral
   preview), and narration uses the narrator's base voice.
5. Confirm the 5 preset personas sound distinct enough to be usable; if a
   preset's underlying Qwen speaker is a poor timbre match, note it — the
   speaker mapping in voices.py is the tunable knob (instruct steering does the
   rest).
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues (e.g. a preset that needs a different underlying speaker, or narration still getting delivery instructions)</resume-signal>
</task>

</tasks>

<verification>
- `cd backend && uv run pytest -q` passes.
- `cd backend && uv run ruff check .` clean (strict E,F,I,UP,B; no new noqa in non-test code).
- `cd backend && uv run python -m app.voices` self-check passes.
- GET /voices returns exactly 5 presets.
- Human checkpoint: real-key analysis casts from the 5 presets, narration cells
  are empty, dialogue generation is steered by merged base+delivery.
</verification>

<success_criteria>
- Exactly 5 fixed presets with fleshed-out steering descriptions (voices.py).
- Analysis LLM outputs a `voice_preset` pick per character and an adapted
  `description`; both are persisted (Character.voice_preset / voice_instructions).
- Narration segments have empty per-segment instructions; dialogue segments have
  short delivery instructions.
- Segment TTS instruct = merge of character adapted base + segment delivery, and
  the cache key hashes that merged string.
- No SQLModel migration and no frontend code change were needed (reused existing
  fields and data-driven UI).
</success_criteria>

<output>
Create `.planning/quick/260713-dye-rework-the-presets-feature-5-fixed-voice/260713-dye-SUMMARY.md` when done.
</output>