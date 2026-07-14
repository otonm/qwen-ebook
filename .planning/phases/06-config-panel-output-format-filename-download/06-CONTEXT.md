# Phase 6: Config Panel — Output Format, Filename & Download - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

User can pick the output audio format (FLAC, MP3, or Opus), set a custom output filename, and download the finished joined file via a blue Download button in the Config Panel once generation completes. Format selection is per-generation (not a global env setting like v1.0), and filename is persisted per-project but can be changed before each generation run.

Out of scope (per REQUIREMENTS.md v1.1): auto-download or auto-play on completion (GEN-03 precedent: user-triggered, never auto-fire); WAV as an output format (explicitly dropped); a configurable codec fallback strategy (codec availability is a verified fact before planning, not a runtime choice); multi-file retention (only the latest output persists; older files are deleted).

</domain>

<decisions>
## Implementation Decisions

### Output format selection

- **D-01:** Format choice is **per-generation, selectable from the Config Panel** — not a global environment setting like v1.0's `OUTPUT_FORMAT` env var. The selector shows three options: FLAC, MP3, Opus. User can try different formats for the same segment/project without re-generating the underlying audio (all formats use the same WAV intermediates from synthesis; the format choice only affects the final ffmpeg join step).

- **D-02:** Format selection is **persisted per-project** in a new `Project.output_format` column (defaults to a sensible first choice, TBD once codec availability is confirmed — likely MP3 for broad compatibility). User can change the format before each generation run; the previous choice is preserved as the default.

### Output filename strategy

- **D-03:** Filename is **user-set and persisted per-project** via a new `Project.output_filename` column. A text input in the Config Panel lets the user type a custom filename. The app automatically appends the correct file extension based on the chosen format (e.g., user types "my-book" + format=MP3 → saved as "my-book.mp3"). User can edit the filename anytime before clicking Generate All.

- **D-04:** Filename is **sanitized automatically (strict mode)** — the app removes/replaces invalid filesystem characters (e.g., /, \, :, *, ?, |, ", <, >) without showing a dialog. If sanitization occurs, the user sees the final name in the Config Panel immediately (no hidden surprise at download time). No user confirmation for sanitization; the field always shows the actual filename that will be used.

- **D-05:** If the user leaves the filename field empty, **auto-generate a sensible default** — derive it from the original upload filename (e.g., book.epub → "book"; or if that's unavailable, use the project id or "output"). This keeps the user from accidentally leaving it blank.

### Download UX and file lifecycle

- **D-06:** After batch generation completes and the output file is successfully joined, a blue **"Download" button appears in the Config Panel** (next to or below the existing Generate All button). Clicking it triggers a browser download with the chosen filename.

- **D-07:** When a user clicks Generate All while a previous output file exists, the **old file is deleted and replaced** with the new one. Only the latest output ever persists on disk. The `Project.output_path` always points to the current file.

- **D-08:** The download endpoint must serve the file with the **correct `Content-Type` header** based on the actual format (audio/flac for FLAC, audio/mpeg for MP3, audio/opus or audio/ogg for Opus). The file extension must always match the format so the browser doesn't double-guess the type.

### Format + codec validation strategy

- **D-09:** **Before planning, spike to verify codec availability** (specifically, `libopus` in the deploy VM's ffmpeg build). Run `ffmpeg -codecs | grep -E 'opus|flac|mp3'` on the deploy container. If Opus is unavailable, escalate to the user — either drop Opus from the Phase 6 requirements or add a DevOps task to rebuild ffmpeg with libopus support.

- **D-10:** Phase 6 planning and implementation **assumes all three codecs (FLAC, MP3, Opus) are available** and working. No runtime fallback if a codec fails; if the spike finds Opus missing, the decision is made upstream before code lands.

- **D-11:** Existing `audio_join.py`'s `join_wavs(fmt)` function is the integration point. The function already handles "wav" (stream copy) and "mp3" (libmp3lame) — add "flac" (libflac or -c:a flac) and "opus" (libopus or -c:a libopus) with the same pattern. No new internal codecs, no named_codec registries; keep the same simple `if fmt == X` dispatch.

### Configuration and integration points

- **D-12:** New `Project.output_format` and `Project.output_filename` columns default sensibly:
  - `output_format`: Default to MP3 (broad compatibility, smallest cognitive load for a first choice — planner to confirm once D-09's spike is done)
  - `output_filename`: Default to the original upload filename's stem (e.g., "book" from "book.epub") or project id if unavailable

- **D-13:** Format and filename choices flow through the existing generation pipeline **unchanged**:
  - `generate_project` (Phase 3's endpoint) remains fire-and-forget; it reads `Project.output_format` and `Project.output_filename` when it calls `run_batch_generation`
  - `run_batch_generation` (Phase 3's worker) passes these to `join_wavs(..., fmt=project.output_format)` — no change to the function signature, just pass the format
  - Download is a **separate, new endpoint** (`GET /projects/{id}/download` or similar) that serves the file from `Project.output_path` with the correct Content-Type header

- **D-14:** No change to segment/character preview generation — those still produce WAV (or remain configurable, per Phase 3). Only the final joined output respects the user's format choice.

### Claude's Discretion

- Exact default value for `output_format` column (to be decided after D-09's codec-availability spike confirms all three formats work)
- Exact location of the Format dropdown + Filename text input in the Config Panel layout (next to the model dropdown, or below it; exact copy/labels)
- Exact file extension strategy if the user's filename already includes an extension (e.g., user types "my-book.mp3" for an Opus output — strip it and re-add, or leave as-is and let ffmpeg-and-the-browser-sort-it-out?)
- Exact Content-Type headers for each format (confirm audio/flac, audio/mpeg, audio/opus or audio/ogg are the correct canonical types)
- Whether the Download button should be disabled until output exists, or visible-but-disabled with a tooltip

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 6 requirements and scope
- `.planning/REQUIREMENTS.md` — CFG-06, CFG-07, CFG-08 (locked requirements for this phase); Out of Scope table (explicitly no auto-download/auto-play, no WAV format, no multi-file retention, no 4th codec)
- `.planning/ROADMAP.md` §Phase 6 — success criteria, dependencies (technically independent of Phases 4-5, sequenced per research's default build order), and UI hint flag

### Current audio handling (reused in this phase)
- `.planning/phases/03-editable-table-full-generation-pipeline/03-CONTEXT.md` — existing output_path semantics and where join_wavs is called in the generation pipeline
- `backend/app/audio_join.py` — the `join_wavs(wav_paths, out_path, fmt)` function that is the integration point for format selection (currently handles "wav" and "mp3"; Phase 6 extends to "flac" and "opus")
- `backend/app/generation_worker.py` line ~225 — where `join_wavs` is called with `settings.OUTPUT_FORMAT`; this phase makes the format dynamic (per-project) instead of fixed (env var)

### Prior model/config patterns (to reuse)
- `.planning/phases/05-on-demand-model-swap/05-CONTEXT.md` — Pattern D-02 for new per-project columns (Project.tts_model) and how they flow through the existing pipeline without major restructuring; Phase 6 follows the same pattern with `Project.output_format` and `Project.output_filename`

### Deployment verification (blocking)
- STATE.md §Blockers/Concerns — "libopus presence in deploy VM's ffmpeg build is unconfirmed" — this is the D-09 spike gate. Before planning Phase 6, run `ffmpeg -codecs | grep -E 'opus|flac'` on the deploy container and bring findings back to the user.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `audio_join.py`'s `join_wavs(wav_paths, out_path, fmt)` — already parametrized by format, currently handles "wav" (stream copy) and "mp3" (libmp3lame). Phase 6 extends to "flac" and "opus" with the same conditional dispatch pattern.

- `generation_worker.py` line ~225: `join_wavs(wav_paths, out_path, settings.OUTPUT_FORMAT)` — currently reads from a global env-based setting. Phase 6 changes this to `settings.OUTPUT_FORMAT` → `project.output_format` (read from the database per project, not env).

- `main.py`'s existing `POST /projects/{id}/generate` (batch generation) and SSE `generation_stream` — no structural changes needed; format/filename are just read from the Project object when called.

- Model pattern from Phase 5: `Project.tts_model: str` column, read via session at generation time, threaded through the existing pipeline without major API changes. Phase 6 reuses this pattern exactly for `output_format` and `output_filename`.

### Established Patterns

- Config Panel (ConfigPanel.tsx): Already shows the Model dropdown (Phase 5). Phase 6 adds two more controls: a Format dropdown (FLAC/MP3/Opus) and a Filename text input. Both are persisted (read/write via `PATCH /projects/{id}` or dedicated endpoint).

- Generation flow: Project is read from DB, fields like `tts_model` are accessed inline. Phase 6's format/filename follow the same pattern — no new API contract needed.

- File storage: `Project.output_path` is set once join completes and persists. Phase 6 changes this to delete-old-on-regenerate semantics (per D-07), but the column remains the same — just a timing/cleanup logic change, not a schema redesign.

### Integration Points

- New `Project` columns: `output_format: str` (default TBD after codec spike), `output_filename: str` (default to upload filename stem or project id).

- New download endpoint (e.g., `GET /projects/{id}/download`): Serves file from `Project.output_path` with the correct Content-Type header based on the actual format. Simple passthrough after join completes.

- Config Panel (frontend): Add Format dropdown + Filename text input. Both fields persist immediately on blur/change via a `PATCH /projects/{id}` endpoint (or extend the existing config update call if one exists). Download button appears next to Generate All once generation succeeds.

- File cleanup logic in `run_batch_generation`: Before starting a new join, delete the previous output file if one exists (per D-07). Use `Path(old_path).unlink(missing_ok=True)` before the new join call.

</code_context>

<specifics>
## Specific Ideas

No specific visual/copy examples given — exact dropdown labels, button wording, and filename input placeholder text are Claude's discretion. Phase 5's UI-SPEC.md can serve as the precedent for copy style/tone.

</specifics>

<deferred>
## Deferred Ideas

None yet.

</deferred>

---

*Phase: 6 — Config Panel — Output Format, Filename & Download*
*Context gathered: 2026-07-14*
