---
phase: 06-config-panel-output-format-filename-download
verified: 2026-07-15T10:05:55Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 6: Config Panel — Output Format, Filename & Download Verification Report

**Phase Goal:** User can choose the output audio format, set a custom output filename, and download the finished joined file once generation completes, all from the config panel UI.
**Verified:** 2026-07-15T10:05:55Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Merged from ROADMAP.md Success Criteria (4) and the three plans' `must_haves.truths` (deduplicated).

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can select FLAC, MP3, or Opus as the output format (WAV no longer offered) | ✓ VERIFIED | `frontend/src/components/ConfigPanel.tsx:404-416` — `Select` bound to `project.output_format`, exactly three `SelectItem`s (flac/mp3/opus), no wav. `backend/app/audio_join.py:22-37` `CODEC_TABLE` has exactly `{flac, mp3, opus}` keys. `PATCH /projects/{id}` rejects `output_format="wav"` with 422 (`backend/app/main.py:523-526`, confirmed by passing test `test_patch_output_format_rejects_unsupported_value`). |
| 2 | User can set a custom output filename before generating | ✓ VERIFIED | `ConfigPanel.tsx:418-430` editable `Input`, commits on blur via `handleFilenameBlur` → `patchProjectConfig({output_filename})`. Server persists a sanitized value (`main.py:512-536`); confirmed by passing test `test_patch_output_filename_strips_illegal_chars_and_extension` (`a/b:my*book.mp3` → `a_b_mybook`, matching the UAT-amended underscore-substitution behavior). |
| 3 | Once the joined file is ready, user can click a blue "Download" button to save it under the chosen filename | ✓ VERIFIED | `ConfigPanel.tsx:517-532` — `variant="default"` Button (documented in `06-UI-SPEC.md:70` as the app's blue `--primary` accent, same as Generate All), `hasOutput = Boolean(project.output_path)` gates an `<a href={downloadUrl(project.id)} download={downloadFilename}>` vs. a disabled button with a tooltip. `downloadFilename` uses the same D-05 stem derivation as the server. |
| 4 | The downloaded file matches the selected format (correct extension, content type, and audio codec) | ✓ VERIFIED | `GET /projects/{id}/download` returns `FileResponse(..., media_type=CODEC_TABLE[fmt]["content_type"], filename=display_name)` (`main.py:577-581`) — no hand-formatted header. `backend/tests/test_audio_join.py` runs real `ffmpeg`/`ffprobe` and asserts `format_name` is `flac`/`mp3`/`ogg` for the three formats (not mocked). Human UAT (06-03) additionally confirmed on the real deploy target: `ffprobe` reported `ogg` for the `.opus` download and the file played. |
| 5 | `join_wavs` encodes with the correct codec per format; unrecognized fmt raises (no silent mp3 fallback) | ✓ VERIFIED | `audio_join.py:49-50` raises `ValueError` when `fmt not in CODEC_TABLE`; `test_join_wavs_rejects_unknown_format` passes. |
| 6 | `_join_project` reads `project.output_format` live from the DB (not a global setting) and the on-disk path is a server-generated uuid, never derived from `output_filename` | ✓ VERIFIED | `generation_worker.py:223,235` — `fmt = project.output_format`; `out_path = str(out_dir / f"{uuid.uuid4().hex}.{fmt}")`. Grep confirms no `output_filename` reference in any filesystem-write path in `generation_worker.py`/`main.py` (prohibition upheld). |
| 7 | Before a new join, the previous `project.output_path` file is deleted (D-07 — only latest output persists) | ✓ VERIFIED | `generation_worker.py:226-228` unconditionally unlinks the prior file before the new join. No dedicated automated unit test isolates this exact transition, but it was explicitly and successfully exercised by the human UAT (06-03, step 7): "Confirmed old output is deleted when format changes and only the latest persists" — a genuine live-system check (not an executor self-report), documented with the specific pre-flight/mid-UAT sanitizer correction as corroborating evidence of a real session. |
| 8 | `_serialize_project` exposes `output_format`/`output_filename` per-project (not the old global setting) | ✓ VERIFIED | `main.py:258-259`; `settings.OUTPUT_FORMAT` fully removed from `config.py` (`grep -rn OUTPUT_FORMAT backend/app` → no matches). |
| 9 | `GET /projects/{id}/download` returns 404 for missing project, 409 when output isn't ready | ✓ VERIFIED | `main.py:561-564`; tests `test_download_returns_404_for_unknown_project` and `test_download_returns_409_when_output_not_ready` pass. |

**Score:** 9/9 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/models.py` | `Project.output_format`/`output_filename` columns | ✓ VERIFIED | Lines 36-37, defaults `"mp3"`/`None`, mirrors `tts_model` pattern |
| `backend/app/db.py` | Additive migrator entries | ✓ VERIFIED | `_NEW_COLUMNS["project"]` includes both tuples |
| `backend/app/audio_join.py` | `CODEC_TABLE` 3-way dispatch | ✓ VERIFIED | Exactly `{flac, mp3, opus}`, no catch-all; `-f {fmt}` forces muxer |
| `backend/app/main.py` | `sanitize_filename`, `ProjectConfigPatch`, `patch_project_config`, `download_project` | ✓ VERIFIED | All present and wired; see Truths 1-9 |
| `backend/tests/test_audio_join.py` | ffprobe-verified container tests | ✓ VERIFIED | 4 tests, real ffmpeg subprocess calls, all pass |
| `backend/tests/test_project_config.py` | PATCH + download contract tests | ✓ VERIFIED | 6 tests, all pass |
| `frontend/src/api/client.ts` | `patchProjectConfig`, `downloadUrl`, `output_filename` field | ✓ VERIFIED | Lines 57, 306-322 |
| `frontend/src/components/ConfigPanel.tsx` | Editable Select/Input/Download button | ✓ VERIFIED | Lines 230-532 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `generation_worker._join_project` | `project.output_format` (live DB read) | direct attribute read each call | ✓ WIRED | `generation_worker.py:223` |
| `_join_project` | `join_wavs(..., fmt)` | positional arg | ✓ WIRED | `generation_worker.py:236` |
| `download_project` | `CODEC_TABLE[fmt]["content_type"]` | dict lookup → `FileResponse media_type` | ✓ WIRED | `main.py:579` |
| `patch_project_config` | `sanitize_filename` → `project.output_filename` | function call → attribute assign | ✓ WIRED | `main.py:536` |
| ConfigPanel Format `Select.onValueChange` | `patchProjectConfig({output_format})` → `onRefresh()` | `handleConfigChange` | ✓ WIRED | `ConfigPanel.tsx:332-343, 406` |
| ConfigPanel Filename `Input.onBlur` | `patchProjectConfig({output_filename})` → re-seed draft | `handleFilenameBlur` + `lastSyncedFilename` render-time sync | ✓ WIRED | `ConfigPanel.tsx:230-240, 344-347` |
| Download `<a href={downloadUrl(project.id)}>` | `GET /projects/{id}/download` | native anchor navigation, no fetch/blob | ✓ WIRED | `ConfigPanel.tsx:526`; grep confirms no fetch/blob in download path |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| join_wavs produces correct container per format | `uv run pytest tests/test_audio_join.py -q` (real ffmpeg/ffprobe, not mocked) | 4 passed | ✓ PASS |
| PATCH/download route contract | `uv run pytest tests/test_project_config.py -q` | 6 passed | ✓ PASS |
| OUTPUT_FORMAT setting fully retired | `grep -rn OUTPUT_FORMAT backend/app` | no matches | ✓ PASS |
| No hand-formatted Content-Disposition | `grep -n "Content-Disposition" backend/app/main.py` | only in a docstring/comment, not a literal header | ✓ PASS |
| Frontend type-check | `cd frontend && npx tsc --noEmit` | clean | ✓ PASS |
| Frontend build | `cd frontend && npm run build` | succeeds | ✓ PASS |
| Frontend lint | `npx eslint src/components/ConfigPanel.tsx src/api/client.ts` | clean | ✓ PASS |
| Backend lint | `cd backend && uv run ruff check .` | clean | ✓ PASS |
| Full backend suite (single run) | `cd backend && uv run pytest -q` | 107 passed, 2 failed (pre-existing, unrelated — see below), 1 skipped | ✓ PASS (phase-relevant) |
| Human UAT end-to-end on deploy target | 06-03-PLAN's 7-step checkpoint | "approved" with 1 amendment (underscore-substitution) now reflected in code + tests (commit `3f49822`) | ✓ PASS |

**Pre-existing failures (verified NOT introduced by this phase):** `tests/test_generation.py::test_batch_continues_past_error` (cross-test bleed in the process-wide generation-lock globals — a different test in the same file fails non-deterministically depending on run order) and `tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined` (expects 200, upload returns 201). Reproduced independently in this verification run; consistent with the orchestrator's note that these fail identically at the pre-phase base commit `7089995`. Not counted against Phase 6.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|--------------|--------|----------|
| CFG-06 | 06-01, 06-02, 06-03 | User can choose FLAC/MP3/Opus output format | ✓ SATISFIED | Truths 1, 5, 6, 8 |
| CFG-07 | 06-01, 06-02, 06-03 | User can set a custom output filename | ✓ SATISFIED | Truths 2, 6 |
| CFG-08 | 06-01, 06-02, 06-03 | User can download the finished joined file via a blue Download button | ✓ SATISFIED | Truths 3, 4, 9 |

Cross-referenced against `.planning/REQUIREMENTS.md` — CFG-06/07/08 all map to Phase 6 and no other Phase-6 requirement IDs appear there (no orphaned requirements).

### Anti-Patterns Found

None. `grep` for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|not yet implemented|coming soon` across all files modified by this phase (`backend/app/main.py`, `audio_join.py`, `generation_worker.py`, `models.py`, `db.py`, `config.py`, `frontend/src/api/client.ts`, `frontend/src/components/ConfigPanel.tsx`) returned no matches.

**Minor observation (not a gap, not part of any must-have):** the client's `downloadFilename` uses `project.output_filename ?? ...` (nullish-coalescing, only falls back on `null`/`undefined`), while the server's fallback in `download_project` checks `if project.output_filename` (falsy, so also falls back on empty string `""`). If a user set a filename consisting entirely of illegal characters, `sanitize_filename` would persist `""`, and the client's `download` attribute would render `.mp3` while the server's `Content-Disposition` would use the upload-filename stem — a same-origin browser honors the anchor's `download` attribute, so the saved name would be `.mp3` instead of the server's derived name. This is a narrow edge case not covered by any must-have or the UAT script; noting for awareness, not blocking.

### Human Verification Required

None. The one item requiring human judgment (D-07 delete-old-output-before-join, and full end-to-end format/filename/download/codec correctness) was already exercised and signed off in plan 06-03's human-verify checkpoint on the real deploy target (`https://tts.pigeon-bearded.ts.net`), including a live mid-UAT correction (`3f49822`) that is itself evidence the session was genuine rather than a rubber-stamped self-report.

### Gaps Summary

None. All 9 merged truths (4 roadmap Success Criteria + plan-level must-haves) are verified against actual code: server-side format/filename persistence and validation, a real 3-way ffmpeg codec dispatch proven against ffprobe (not mocked), a download route using `FileResponse`'s built-in header handling, and a frontend UI wired end-to-end to both endpoints — plus a genuine human UAT pass on the deploy target with one real amendment applied and re-verified. Backend tests (11 phase-specific, 107/109 full-suite), ruff, tsc, eslint, and the frontend build are all clean. The two full-suite failures are pre-existing and reproduced identically outside this phase's scope.

---

_Verified: 2026-07-15T10:05:55Z_
_Verifier: Claude (gsd-verifier)_
