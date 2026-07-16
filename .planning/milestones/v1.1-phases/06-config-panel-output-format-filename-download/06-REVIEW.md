---
phase: 06-config-panel-output-format-filename-download
reviewed: 2026-07-15T13:05:55Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - backend/app/audio_join.py
  - backend/app/config.py
  - backend/app/db.py
  - backend/app/generation_worker.py
  - backend/app/main.py
  - backend/app/models.py
  - backend/tests/test_audio_join.py
  - backend/tests/test_config.py
  - backend/tests/test_project_config.py
  - frontend/src/api/client.ts
  - frontend/src/components/ConfigPanel.tsx
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-07-15T13:05:55Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the Phase 6 diff (`7089995^..HEAD`): per-project `output_format`/`output_filename` columns + SQLite column migration, the 3-way `CODEC_TABLE` ffmpeg dispatch in `audio_join.py`, `PATCH /projects/{id}` config endpoint, `GET /projects/{id}/download` `FileResponse` route, `sanitize_filename`, and the editable ConfigPanel controls.

Verified during review: all 11 phase tests pass against an isolated DB, `ruff check .` is clean (no new `noqa`, f-string logging convention followed), the concat list-file escaping matches ffmpeg's quoting rules, ffmpeg is invoked as an argument list (no shell), the download path is never derived from any client string, `Content-Disposition` goes through `FileResponse(filename=)` (no header injection — `sanitize_filename` also strips control chars and quotes), and `settings.OUTPUT_FORMAT` is fully retired with no dangling references. No security-critical findings.

Three warnings, all correctness gaps in state transitions the happy path doesn't hit: a format change after a completed join serves the old file mislabeled with the new extension/Content-Type; the D-07 delete-old-output runs *before* the new join so a failed join destroys the last good output; and the empty-string-sanitized filename divergence between server (falsy fallback) and client (`??` keeps `""`) the phase verifier already flagged.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Format change after a completed join serves the old file with the wrong extension and Content-Type

**File:** `backend/app/main.py:566-580`, `frontend/src/components/ConfigPanel.tsx:272`
**Issue:** `download_project` reads `fmt = project.output_format` (the *current* setting) but serves the bytes at `project.output_path`, which were encoded with the format in effect at join time. `patch_project_config` (main.py:533-534) does not invalidate `output_path` when `output_format` changes. Sequence: Generate All with `mp3` → join succeeds → user switches the Output Format Select to `flac` → Download button is still enabled (`hasOutput` only checks `output_path`) → the server sends the mp3-encoded file as `book.flac` with `media_type=audio/flac`, and the client anchor's `download` attribute (ConfigPanel.tsx:272, also built from the live `project.output_format`) names it `.flac` too. The user receives a mislabeled audio file. This directly contradicts the route's own contract ("serve the joined output file with the correct Content-Type").
**Fix:** Simplest coherent fix, matching the project's existing invalidate-on-config-change discipline (model swap, segment edits): clear `output_path` when the format actually changes, so Download honestly disables until the (cheap, all-cache-hit) re-join:
```python
if patch.output_format is not None and patch.output_format != project.output_format:
    old_output = project.output_path
    project.output_format = patch.output_format
    project.output_path = None
    # unlink old_output after commit, mirroring patch_segment's pattern
```
Alternative if the old download should stay available: derive `fmt` from the join-time truth already embedded in the stored path — `fmt = Path(project.output_path).suffix.lstrip(".")` — and do the same for the client's extension (it has `output_path`).

### WR-02: D-07 deletes the previous output before the new join runs — a failed join destroys the last good output and leaves a dangling `output_path`

**File:** `backend/app/generation_worker.py:224-236`
**Issue:** `_join_project` unlinks the previous joined file (line 228) *before* calling `join_wavs` (line 236). `join_wavs` can raise `RuntimeError` on any ffmpeg failure (disk full, a corrupt segment WAV, encoder error). When it does: the previous good output is already gone from disk, and `project.output_path` still points at the deleted file (the write-back at lines 238-243 never runs). Downstream, `download_project`'s `is_file()` check turns this into a persistent 409 "Output not ready", and the frontend Download button stays enabled off the stale truthy `output_path` — clicking it fails. Nothing in D-07 ("only the latest output persists") requires delete-*before*-write; each join writes to a fresh uuid path, so there is no name collision forcing this ordering.
**Fix:** Capture the old path, join first, delete only after the new path is committed:
```python
with Session(engine) as session:
    project = session.get(Project, project_id)
    if project is None:
        raise RuntimeError(f"project {project_id} not found — join blocked")
    fmt = project.output_format
    old_output = project.output_path

out_path = str(out_dir / f"{uuid.uuid4().hex}.{fmt}")
await run_in_threadpool(join_wavs, wav_paths, out_path, fmt)

with Session(engine) as session:
    project = session.get(Project, project_id)
    if project is not None:
        project.output_path = out_path
        session.add(project)
        session.commit()
if old_output and old_output != out_path and Path(old_output).is_file():
    logger.info(f"project {project_id}: deleting previous output {old_output}")
    Path(old_output).unlink(missing_ok=True)
```

### WR-03: Empty-sanitized `output_filename` is stored as `""`, and the client's `??` fallback then produces a broken download name (`.mp3`)

**File:** `backend/app/main.py:535-536`, `frontend/src/components/ConfigPanel.tsx:272`
**Issue:** (Noted by the phase verifier; confirmed and assessed here.) If the user's input sanitizes to nothing (`"???"`, whitespace, or simply clearing the field — verified: `sanitize_filename("???") == ""`), `patch_project_config` persists `""`, not `NULL`. The server's download route handles this (`if project.output_filename` is falsy → upload-stem fallback → `"output"` backstop), but the client's `downloadFilename` uses nullish coalescing: `project.output_filename ?? project.filename.replace(...)` — `""` is not nullish, so the anchor renders `download=".mp3"`. For same-origin links the `download` attribute wins over `Content-Disposition`, so the browser saves a dotfile named `.mp3` (hidden on Linux/macOS), and the server's carefully derived fallback name never applies in the app's own UI. Related micro-divergence in the same expression: the client's stem regex (`/\.[^.]+$/`) strips a dotfile upload name like `.hidden` to `""`, while the server's `Path(...).stem` keeps `.hidden` — and the client has no `"output"` backstop at all.
**Fix:** Root cause is the empty-string sentinel — normalize it away at the write boundary so both consumers agree:
```python
# main.py patch_project_config
project.output_filename = sanitize_filename(patch.output_filename) or None
```
And harden the client expression to mirror the server's full fallback chain:
```ts
const stem = project.output_filename || project.filename.replace(/\.[^.]+$/, "") || "output"
const downloadFilename = `${stem}.${project.output_format}`
```

## Info

### IN-01: `CODEC_TABLE` values typed as `object` defeat static typing at both use sites

**File:** `backend/app/audio_join.py:22`
**Issue:** `dict[str, dict[str, object]]` means `codec_args` is unpacked into the `subprocess.run` argv as `object` (audio_join.py:64,76) and `content_type` is passed as `media_type=object` (main.py:579). Runtime-correct, but any future type checker (mypy/pyright) flags both, and a typo'd inner key (`"codec_arg"`) is a runtime `KeyError` instead of a static error.
**Fix:** A small `NamedTuple`/frozen dataclass — `class Codec(NamedTuple): codec_args: list[str]; content_type: str` — keeps the table one dict and fully typed.

### IN-02: TOCTOU window between the download route's `is_file()` check and `FileResponse` opening the file

**File:** `backend/app/main.py:563-577`, `backend/app/generation_worker.py:228`
**Issue:** The existence check runs in the handler; the file is actually opened later when the response streams. A concurrent re-join's D-07 unlink (or a project delete) landing in that window yields a failed download/500 instead of the clean 409. Single-user app, tiny window — noting because WR-02's fix (delete-after-commit) also shrinks this: the old file stays valid until the new `output_path` is already committed.
**Fix:** Covered by WR-02's reordering; no separate change needed.

### IN-03: `test_project_config.py` seeds the live `projects.db` when run without a `DATABASE_URL` override

**File:** `backend/tests/test_project_config.py:32`
**Issue:** `init_db()` + `_seed_project()` write to `settings.DATABASE_URL`'s default — the real `backend/projects.db` on this machine, which is also the deploy target — and never clean up, so every test run leaves junk projects visible in the app's landing-screen list. This follows the pre-existing convention of every other backend test file (not introduced by this phase), so it's noted for the backlog rather than as a phase defect.
**Fix:** A one-line session-scoped `conftest.py` fixture (or `os.environ.setdefault("DATABASE_URL", ...)` to a tmp path before app imports, matching the existing `LLM_BACKEND`/`TTS_BACKEND` pattern) would isolate the whole suite at once.

---

_Reviewed: 2026-07-15T13:05:55Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
