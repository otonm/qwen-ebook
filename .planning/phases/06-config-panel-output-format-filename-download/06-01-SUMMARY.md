---
phase: 06-config-panel-output-format-filename-download
plan: 01
subsystem: api
tags: [fastapi, sqlmodel, ffmpeg, sanitization, file-response]

requires:
  - phase: 03-generation-pipeline
    provides: audio_join.join_wavs, generation_worker._join_project (2-way wav/mp3 dispatch)
  - phase: 05-model-swap
    provides: per-project Project.tts_model column pattern this plan mirrors
provides:
  - "Project.output_format / Project.output_filename DB columns (server-side truth for CFG-06/CFG-07)"
  - "audio_join.CODEC_TABLE — 3-way flac/mp3/opus codec dispatch with verified ffmpeg args and content types"
  - "generation_worker._join_project reading format live per-project + D-07 delete-old-output-before-join"
  - "PATCH /projects/{id} — format validation (422) + filename sanitization"
  - "GET /projects/{id}/download — FileResponse with correct Content-Type/Content-Disposition"
affects: [06-02-config-panel-ui, 06-03-integration]

tech-stack:
  added: []
  patterns:
    - "CODEC_TABLE dict as the single format->{codec_args, content_type} lookup, no catch-all else branch"
    - "sanitize_filename: rightmost-segment split on /, \\, : (true path/drive separators) then delete remaining illegal chars, then Path.stem for extension"
    - "PATCH endpoint validates enum BEFORE opening a DB session (mirrors set_project_model's MODEL_CHOICES 422)"
    - "FileResponse(..., filename=) for RFC-6266-correct Content-Disposition — never hand-formatted"

key-files:
  created:
    - backend/tests/test_audio_join.py
    - backend/tests/test_project_config.py
  modified:
    - backend/app/models.py
    - backend/app/db.py
    - backend/app/audio_join.py
    - backend/app/generation_worker.py
    - backend/app/config.py
    - backend/app/main.py
    - backend/tests/test_config.py

key-decisions:
  - "sanitize_filename treats /, \\, : as true separators (rightmost-segment retained) rather than pure character deletion — a straight re.sub on 'a/b:my*book.mp3' produces 'abmybook', but the plan's own worked example specifies 'mybook'; the rightmost-segment approach is the only reading that satisfies both the prohibitions block (no path reaches a filesystem write) and the documented example"
  - "Opus content_type is audio/ogg (RFC 7845 Ogg-Opus), not audio/opus — per 06-RESEARCH.md's verified ffprobe output"
  - "-f {fmt} added explicitly to the ffmpeg argv so the muxer can never disagree with CODEC_TABLE's content_type or the out_path extension"

patterns-established:
  - "Format-specific behavior (codec args, Content-Type, extension) lives in exactly one dict (CODEC_TABLE) consumed by both audio_join.py and main.py — no duplicated allowlists"

requirements-completed: [CFG-06, CFG-07, CFG-08]

coverage:
  - id: D1
    description: "join_wavs re-encodes to flac/mp3/opus per CODEC_TABLE and rejects any other fmt (no silent mp3 fallback)"
    requirement: "CFG-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audio_join.py#test_join_wavs_produces_correct_container"
        status: pass
      - kind: unit
        ref: "backend/tests/test_audio_join.py#test_join_wavs_rejects_unknown_format"
        status: pass
    human_judgment: false
  - id: D2
    description: "_join_project reads project.output_format live from the DB and deletes the previous output_path file before the new join (D-07)"
    requirement: "CFG-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_audio_join.py (fmt threaded through join_wavs call, verified via code path — no dedicated _join_project unit test added; covered indirectly by existing test_generation.py batch-join tests still passing)"
        status: pass
    human_judgment: false
  - id: D3
    description: "PATCH /projects/{id} persists output_format (422 for unsupported values) and a sanitized output_filename"
    requirement: "CFG-07"
    verification:
      - kind: unit
        ref: "backend/tests/test_project_config.py#test_patch_output_format_persists_and_returns_project"
        status: pass
      - kind: unit
        ref: "backend/tests/test_project_config.py#test_patch_output_format_rejects_unsupported_value"
        status: pass
      - kind: unit
        ref: "backend/tests/test_project_config.py#test_patch_output_filename_strips_illegal_chars_and_extension"
        status: pass
    human_judgment: false
  - id: D4
    description: "GET /projects/{id}/download serves the joined file with correct Content-Type + Content-Disposition filename; 404/409 branches"
    requirement: "CFG-08"
    verification:
      - kind: unit
        ref: "backend/tests/test_project_config.py#test_download_serves_file_with_correct_content_type_and_filename"
        status: pass
      - kind: unit
        ref: "backend/tests/test_project_config.py#test_download_returns_409_when_output_not_ready"
        status: pass
      - kind: unit
        ref: "backend/tests/test_project_config.py#test_download_returns_404_for_unknown_project"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 01: Server-side output format, filename, and download Summary

**3-way flac/mp3/opus ffmpeg codec dispatch via a single CODEC_TABLE, per-project output_format/output_filename DB columns, a PATCH validation/sanitization endpoint, and a FileResponse-based download route — no new dependencies.**

## Performance

- **Duration:** ~8 min (first commit 11:00:42, last commit 11:08:18, UTC+2)
- **Started:** 2026-07-15T11:00:42+02:00
- **Completed:** 2026-07-15T11:08:18+02:00
- **Tasks:** 3
- **Files modified:** 9 (7 modified, 2 created)

## Accomplishments
- `Project.output_format`/`output_filename` columns added (models.py + db.py additive migrator), defaulting to `"mp3"`/`None`
- `audio_join.CODEC_TABLE` replaces the 2-way `wav`/else dispatch with an explicit flac/mp3/opus table; `join_wavs` raises `ValueError` on any other fmt and forces the muxer via `-f {fmt}` so codec/container/extension can never disagree
- `generation_worker._join_project` reads `project.output_format` live per-project (never `settings.OUTPUT_FORMAT`), and deletes the previous `output_path` file before writing the new join (D-07)
- `PATCH /projects/{id}` validates `output_format` against `CODEC_TABLE` (422 otherwise) and persists a sanitized `output_filename`, with no generation lock claimed
- `GET /projects/{id}/download` serves the joined file via `FileResponse` with the correct `Content-Type` and a `Content-Disposition` filename (sanitized stem + current format's extension); 404 for unknown project, 409 when no output is ready
- `Settings.OUTPUT_FORMAT`/`_ALLOWED_OUTPUT_FORMATS` fully retired from `config.py`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Project.output_format/output_filename columns + additive migrator entries** - `6165c42` (feat)
2. **Task 2: 3-way CODEC_TABLE dispatch in join_wavs + per-project format read and D-07 delete-old in _join_project** - `9e43755` (feat)
3. **Task 3: PATCH config + download route + sanitize_filename + _serialize_project, retire settings.OUTPUT_FORMAT** - `acd0060` (feat)

_All three tasks were marked `tdd="true"`; implementation and tests were written together per task and verified against the plan's automated verify commands before each commit (consistent with how this repo's prior Phase 5 `tts_model` plan handled the same tdd flag) rather than split into separate RED/GREEN commits._

## Files Created/Modified
- `backend/app/models.py` - `Project.output_format`/`output_filename` columns
- `backend/app/db.py` - additive migrator entries for the two new columns
- `backend/app/audio_join.py` - `CODEC_TABLE` dict, 3-way `join_wavs` dispatch, explicit `-f {fmt}` muxer arg
- `backend/app/generation_worker.py` - `_join_project` reads `project.output_format` live, deletes previous output before joining (D-07)
- `backend/app/config.py` - removed `OUTPUT_FORMAT`/`_ALLOWED_OUTPUT_FORMATS`
- `backend/app/main.py` - `sanitize_filename()`, `ProjectConfigPatch`, `patch_project_config`, `download_project`, `_serialize_project` updated
- `backend/tests/test_config.py` - removed the two obsolete `OUTPUT_FORMAT` load-time tests
- `backend/tests/test_audio_join.py` (new) - ffprobe-verified container tests for flac/mp3/opus + ValueError case
- `backend/tests/test_project_config.py` (new) - PATCH validation/sanitization + download route contract tests

## Decisions Made
- **sanitize_filename separator handling:** the plan's `<action>` prose describes "a single re.sub" removing illegal chars, but its own `<behavior>` worked example (`"a/b:my*book.mp3"` → `"mybook"`) is only reachable if `/`, `\`, `:` are treated as true separators (keep the rightmost segment) rather than deleted in place — a pure `re.sub` on that input yields `"abmybook"`. Implemented rightmost-segment splitting for the three separator chars, then character-deletion `re.sub` for the remaining illegal set (`*?|"<>` + control chars), then `Path(...).stem` for the extension. This satisfies both the prohibitions block (on-disk path never touches `output_filename`) and the plan's documented example.
- **Opus Content-Type is `audio/ogg`**, not `audio/opus` — matches 06-RESEARCH.md's verified ffprobe output for ffmpeg's opus muxer (RFC 7845 Ogg-Opus).
- **Explicit `-f {fmt}` in the ffmpeg argv** for every join, independent of `out_path`'s suffix, so the muxer can never silently diverge from `CODEC_TABLE`'s declared content type.

## Deviations from Plan

None — plan executed exactly as written, aside from the sanitize_filename separator-handling clarification documented above under Decisions Made (not a deviation from intent, since the plan's own behavior example specifies this exact transformation; the `<action>` prose just under-specified the mechanism).

## Issues Encountered
- `tests/test_generation.py` shows non-deterministic failures (different tests fail on each full-suite run: `test_batch_continues_past_error`, `test_batch_skips_complete_rows`, `test_batch_resets_stale_generating`, `test_second_generate_all_while_running_is_rejected`) when run as part of the whole `tests/` suite. Confirmed pre-existing and unrelated to this plan by running the full suite against the pre-plan base commit (`7089995`) in an isolated worktree — a different single test failed there too (`test_cancel_running_batch_resets_generating_rows`). This is cross-test bleed in the process-wide generation lock's global state (`_running_generations`/`_generation_progress_queues` module dicts persisting across test modules), not a regression introduced here. All tests pass individually and `tests/test_audio_join.py`/`tests/test_project_config.py`/`tests/test_config.py` pass reliably as a group. Out of scope per the deviation rules' scope boundary (pre-existing, unrelated files) — not fixed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Server-side CFG-06/07/08 is fully wired: format/filename persisted per-project, the join respects the live format, and the download route serves the correct bytes/headers.
- 06-02 (Config Panel UI) can now build the format dropdown, filename input, and Download button directly against `PATCH /projects/{id}` and `GET /projects/{id}/download` — both return/consume the `output_format`/`output_filename` fields `_serialize_project` now exposes.
- No blockers identified for 06-02/06-03.

---
*Phase: 06-config-panel-output-format-filename-download*
*Completed: 2026-07-15*

## Self-Check: PASSED

All 9 files_modified paths confirmed present on disk (backend/app/models.py, backend/app/db.py, backend/app/audio_join.py, backend/app/generation_worker.py, backend/app/config.py, backend/app/main.py, backend/tests/test_config.py, backend/tests/test_audio_join.py, backend/tests/test_project_config.py). All 3 task commit hashes (6165c42, 9e43755, acd0060) confirmed present in `git log --oneline`.
