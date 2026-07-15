---
phase: 06-config-panel-output-format-filename-download
fixed_at: 2026-07-15T13:19:36Z
review_path: .planning/phases/06-config-panel-output-format-filename-download/06-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 6: Code Review Fix Report

**Fixed at:** 2026-07-15T13:19:36Z
**Source review:** .planning/phases/06-config-panel-output-format-filename-download/06-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 3 (fix_scope: critical_warning — 0 critical, 3 warning; the 3 Info findings are out of scope for this run, not skipped-on-failure)
- Fixed: 3
- Skipped: 0

## Fixed Issues

### WR-01: Format change after a completed join serves the old file with the wrong extension and Content-Type

**Files modified:** `backend/app/main.py`, `frontend/src/components/ConfigPanel.tsx`
**Commit:** 57e8c03
**Applied fix:** `patch_project_config` now detects an actual `output_format` change, captures the stale `output_path`, clears it on the project row, commits, and unlinks the old file only after commit — mirroring `patch_segment`'s established invalidate-on-edit / post-commit-unlink pattern already used elsewhere in `main.py`. With `output_path` cleared, `hasOutput` (`Boolean(project.output_path)`) on the frontend already disables the Download button correctly, so no additional client-side gating was needed for this finding; the client's `downloadFilename` derivation was still updated as part of WR-03 below (same call site the reviewer flagged).

### WR-02: D-07 deletes the previous output before the new join runs — a failed join destroys the last good output and leaves a dangling `output_path`

**Files modified:** `backend/app/generation_worker.py`
**Commit:** 3fb463e
**Applied fix:** `_join_project` now captures `old_output_path` before running `join_wavs`, runs the join first, commits the new `output_path` to the DB, and only then deletes the old file (guarded by `old_output_path != out_path` and an `is_file()` check) — reordered exactly per the review's suggested fix, so a failed `join_wavs` (ffmpeg error, disk full, corrupt segment) leaves the previous good output and its `output_path` intact instead of a dangling reference to a deleted file.

### WR-03: Empty-sanitized `output_filename` is stored as `""`, and the client's `??` fallback then produces a broken download name (`.mp3`)

**Files modified:** `backend/app/main.py`, `frontend/src/components/ConfigPanel.tsx`
**Commit:** 57e8c03
**Applied fix:** Server: `patch_project_config` now stores `sanitize_filename(patch.output_filename) or None` instead of the raw (possibly `""`) sanitized result, so an all-illegal-chars input persists as `NULL` rather than an empty string sentinel. Client: `ConfigPanel.tsx`'s `downloadFilename` derivation was rewritten to use `||` (not `??`) across the full three-step fallback chain — `output_filename` → upload-filename stem → literal `"output"` — matching the server's `download_project` fallback exactly, including the `"output"` backstop the client previously lacked entirely.

## Skipped Issues

None — all in-scope findings (WR-01, WR-02, WR-03) were fixed. IN-01, IN-02, and IN-03 were out of scope for this `critical_warning` fix run and were not attempted (IN-02 is explicitly noted in REVIEW.md as already covered by the WR-02 fix applied above; IN-01 and IN-03 remain open for a future `--fix-scope all` pass or manual follow-up).

---

_Fixed: 2026-07-15T13:19:36Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
