# Phase 6: Discussion Log

**Gathered:** 2026-07-14  
**Participants:** User, Claude  
**Mode:** Standard discussion with AskUserQuestion multi-select

---

## Gray Areas Identified

Based on prior context (Phase 5's model-swap pattern, Phase 4's cancellation infrastructure, Phase 3's generation pipeline) and code review, the discussion identified three main decision areas:

1. **Output format selection strategy** — How should the user choose FLAC/MP3/Opus?
2. **Filename handling** — Auto-generated, user-set, or download-time choice?
3. **Codec availability risk** — Verify before planning or plan with fallback?

Additional areas explored during deep-dives:

4. **Download UX** — Where does the download control appear?
5. **File lifecycle** — What happens to previous output when regenerating?
6. **Filename validation** — How to handle invalid filesystem characters?
7. **Persistence** — Remember format/filename across sessions?
8. **Pre-generation review** — Confirmation dialog before Generate All?

---

## Decisions Captured

### Area 1: Output Format Selection (D-01, D-02)

**Question:** Should the audio output format be a global setting, per-project, or per-generation?

**Options Presented:**
- Global environment setting (v1.0 pattern; simpler but inflexible)
- Per-project choice (stored with project)
- **Per-generation choice (user picks each time, most flexible)** ← **USER SELECTED**
- Other

**Rationale:** Per-generation choice allows users to experiment with different formats (FLAC for archival, MP3 for portable) without re-generating the underlying audio synthesis. The WAV intermediates are reusable; only the final join step changes. This is more flexible than per-project and less ambiguous than global.

**Implementation:** New `Project.output_format` column with a Format dropdown in Config Panel, persisted for the next generation.

---

### Area 2: Output Filename Handling (D-03, D-04, D-05)

**Question:** How should output filenames be handled?

**Options Presented:**
- Auto-generated from upload filename
- **User sets before generation (text input in Config Panel)** ← **USER SELECTED**
- User sets at download time (browser download experience)
- Other

**Rationale:** User-set-before-generation keeps the user in control of the naming convention and aligns with the app's "user-triggered, never auto-fire" precedent. The filename is persisted per-project so it doesn't need re-entry on each generation.

**Validation Strategy Selected:** Automatically sanitize invalid filesystem characters (strict mode, no user confirmation).

**Default Strategy:** If the filename field is empty, auto-generate from the original upload filename stem (e.g., "book" from "book.epub") or use project id as fallback.

**Implementation:** New `Project.output_filename` text input in Config Panel, sanitized on every change, with correct extension auto-appended based on the chosen format.

---

### Area 3: Codec Library Verification (D-09, D-10)

**Question:** How should Phase 6 handle the unconfirmed libopus in deploy VM's ffmpeg?

**Options Presented:**
- **Verify first, plan with findings (spike before planning)** ← **USER SELECTED**
- Plan assuming all codecs work
- Plan fallback strategy (graceful degradation)

**Rationale:** This is a hard blocker. The requirements lock three formats (FLAC/MP3/Opus), but if Opus isn't available in production ffmpeg, the phase can't be implemented as specified. The user wants the spike result before planning, not a risky post-planning discovery.

**Spike Task:** Run `ffmpeg -codecs | grep -E 'opus|flac|mp3'` on the deploy container. If Opus is missing, escalate to the user — either drop Opus from Phase 6 or add a DevOps task to rebuild ffmpeg with libopus.

**Implementation:** Phase 6 planning proceeds only after this spike is complete and findings are reviewed.

---

### Area 4: Download UX (D-06)

**Question:** How should the user download the file once generation completes?

**Options Presented:**
- **Download button in Config Panel** ← **USER SELECTED**
- Download link in generation stream
- Both

**Rationale:** Consistent with Config Panel's existing role as the central control hub (model selection, filename, format are all there now). Button appears after generation succeeds, next to the Generate All button.

**Implementation:** New `GET /projects/{id}/download` endpoint, button disabled until generation succeeds and output_path is set.

---

### Area 5: File Lifecycle on Regeneration (D-07)

**Question:** When a user regenerates, what happens to the previous output file?

**Options Presented:**
- Keep old, generate new
- **Delete old, keep new (clean disk state)** ← **USER SELECTED**
- Timestamp-versioned files
- Configurable cleanup

**Rationale:** Only the latest output persists. Simpler mental model for the user (no confusing "which version should I download?"), smaller disk footprint, and matches typical UX patterns (overwrite, not accumulate).

**Implementation:** `run_batch_generation` deletes `Project.output_path` file (if it exists) before starting a new join. Path.unlink(missing_ok=True) pattern.

---

### Area 6: Filename Validation Strategy (D-04)

**Question:** How should the app handle invalid filesystem characters?

**Options Presented:**
- **Sanitize automatically (strict mode)** ← **USER SELECTED**
- Validate and reject with error
- Sanitize with notification toast

**Rationale:** Strict automatic sanitization keeps UX smooth — user always sees the actual filename that will be used, no surprises at download time. No user decision paralysis; the field always shows the truth.

**Implementation:** On any change to the filename input, sanitize in real-time (remove /, \, :, *, ?, |, ", <, >) and update the field. Append extension based on format.

---

### Area 7: Format & Filename Persistence (D-02, D-12)

**Question:** Should format and filename be remembered across sessions?

**Options Presented:**
- **Per-project persistence** ← **USER SELECTED**
- Session-only
- Store as global defaults

**Rationale:** Per-project persistence (stored in database) means reopening the same project shows the user's last choices. If they change projects and come back, the original format/filename is there. This matches the model-swap behavior (Phase 5), where per-project choices stick.

**Implementation:** `Project.output_format` and `Project.output_filename` columns, read on page load, updated via PATCH.

---

### Area 8: Pre-generation Confirmation (No additional decision needed)

**Question:** Should user review/confirm format and filename before clicking Generate All?

**Options Presented:**
- Confirmation dialog
- Summary below button
- **No pre-flight, trust the form** ← **USER SELECTED**

**Rationale:** The format and filename controls are inline in the Config Panel, always visible. User can see what they've chosen. No need for a modal interruption — if they made a mistake, they can edit and regenerate.

---

## Gray Areas NOT Selected for Discussion

None. The user engaged with all presented areas.

---

## Claude's Discretion Items (for planner/researcher)

1. **Default output_format value** (D-12) — After D-09's codec spike, likely MP3 for compatibility, but planner confirms.
2. **Exact Config Panel layout** — Where Format dropdown and Filename input appear relative to existing Model dropdown and Generate button.
3. **Exact filename extension handling** — If user types "my-book.mp3" for Opus output, strip and re-add, or trust the user?
4. **Correct Content-Type headers** — Confirm audio/flac, audio/mpeg, audio/opus (or audio/ogg) are canonical per RFCs.
5. **Download button UX polish** — Disabled state styling, tooltip text, position next to Generate All or below?

---

## Integration with Prior Phases

- **Phase 3 foundation:** Reuses `audio_join.py` and `run_batch_generation` pipeline; format is just a parameter.
- **Phase 5 pattern:** Follows the per-project-column pattern established by `Project.tts_model`.
- **Phase 4 prerequisite:** No direct dependency, but Phase 4's cancellation infrastructure means user could cancel a generation mid-join — no special handling needed, joined file just won't exist.
- **Phase 7 blocker:** Phase 7 wires up the yellow/red/green button across all 4 generation sites and must account for the download button's visibility state.

---

*Discussion gathered: 2026-07-14*  
*Next: Spike Phase 6 codec availability, then /gsd-plan-phase 6*
