---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
fixed_at: 2026-07-09T16:48:58Z
review_path: .planning/phases/01-upload-to-audio-spike-tts-rocm-de-risk/01-REVIEW.md
iteration: 1
findings_in_scope: 12
fixed: 4
skipped: 8
status: partial
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-07-09T16:48:58Z
**Source review:** .planning/phases/01-upload-to-audio-spike-tts-rocm-de-risk/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 12 (`fix_scope=all`, so the 4 Info findings IN-01..IN-04 are included this run)
- Fixed (new this pass): 4
- Already fixed in a prior pass (re-verified against current code, no new commit needed): 8
- Skipped for other reasons: 0

Note: a prior fix pass (also recorded as "iteration 1" in this same file,
before this run overwrote it) already resolved CR-01, CR-02, and WR-01
through WR-06 with `fix_scope=critical_warning` — commits `b2010dc`,
`7cf6878`, `9fce687`, `cf81086`, `0461faa`, `549b6e4`, `8dab51d`, `8ac7892`.
`01-REVIEW.md` was never regenerated after that pass, so it still lists all
12 original findings including those 8. This run re-verified each of the 8
against the current source before treating them as resolved (none were
blindly assumed fixed just because a commit hash was supplied) and applied
new fixes only for the 4 Info-level findings that had not yet been touched.

## Fixed Issues

### IN-01: Misleading comment claims frozen `Settings` dataclass attributes can be monkeypatched

**Files modified:** `backend/app/config.py`
**Commit:** `0d58419`
**Applied fix:** Replaced the trailing module-level comment on the `settings`
singleton with an accurate description: tests must either reload the module
or use `monkeypatch.setattr(app.config, "settings", Settings(...))` to swap
the whole singleton, since individual fields can't be patched on a
`@dataclass(frozen=True)` instance.

### IN-02: `tts_health()` is dead code — defined but never called

**Files modified:** `backend/app/main.py`
**Commit:** `f1454da`
**Applied fix:** Added a `GET /healthz` route to `backend/app/main.py` that
calls `tts_health()` (offloaded via `run_in_threadpool`, consistent with the
existing CR-02 blocking-I/O fix) and returns 200 when the configured TTS
backend is reachable, 503 otherwise. This gives the pod a real backend
readiness probe and resolves the dead-code finding by wiring up the existing
helper rather than deleting it, per the finding's own suggested resolution.

### IN-03: `sox` dependency in `tts_service/requirements.txt` is unused and its native binary is not installed

**Files modified:** `backend/tts_service/requirements.txt`
**Commit:** `70e6092`
**Applied fix:** Confirmed `sox` is not imported anywhere in
`tts_service/model.py` or `tts_service/server.py`, and `Containerfile.tts`
never installs the underlying `sox` system binary. Removed the `sox` line
from `requirements.txt` and added a comment explaining why.

### IN-04: No `Content-Disposition` header on the generated audio response

**Files modified:** `backend/app/main.py`
**Commit:** `9da20c0`
**Applied fix:** Added a
`Content-Disposition: attachment; filename="{project_id}.{OUTPUT_FORMAT}"`
header to the final `Response` in `create_project()`, so browsers/`curl -O`
get a suggested filename for the downloaded audio.

## Skipped Issues (already fixed in a prior pass)

All 8 of the following were re-verified against the current state of the
source files in this pass and found to already contain the fix described in
REVIEW.md. No new commit was made for these; they are listed here only so
the fix-count in this report is traceable against all 12 original findings.

### CR-01: Empty/whitespace-only upload crashes with an unhandled exception instead of a clean 400

**File:** `backend/app/main.py:59-63`
**Reason:** Already fixed. `create_project()` checks `if not chunks:` and
raises `HTTPException(status_code=400, detail="Upload contains no synthesizable text")`
before any TTS/ffmpeg work starts. Regression test
`test_empty_upload_is_rejected_with_400` exists in `backend/tests/test_e2e.py`
and passes. Prior commit: `b2010dc`.

### CR-02: Blocking synchronous I/O inside `async def` route handlers stalls the entire event loop

**File:** `backend/app/main.py:91-137`
**Reason:** Already fixed. `synthesize()`, `chunk_path.write_bytes(...)`, and
`join_wavs(...)` are all offloaded via `starlette.concurrency.run_in_threadpool`.
Prior commit: `7cf6878`.

### WR-01: Generated chunk/output files are never cleaned up

**File:** `backend/app/main.py:78-145`
**Reason:** Already fixed. Chunk WAV paths are tracked in `chunk_paths` and
removed in a `finally` block regardless of success/failure. Regression test
`test_chunk_files_are_cleaned_up_after_successful_join` exists and passes.
Prior commit: `9fce687`.

### WR-02: TTS service 4xx client errors are misreported as 502 "TTS service unavailable"

**File:** `backend/app/main.py:98-115`
**Reason:** Already fixed. `httpx.HTTPStatusError` is caught separately from
the generic `httpx.HTTPError`; status codes `< 500` are surfaced as
`502 TTS service rejected request: {reason}` rather than the generic message.
Regression test `test_tts_4xx_response_is_surfaced_as_502_with_reason_not_generic`
exists and passes. Prior commit: `cf81086`.

### WR-03: `ffmpeg`/join failures are not caught in `main.py`

**File:** `backend/app/main.py:121-131`
**Reason:** Already fixed. The `join_wavs(...)` call is wrapped in
`try/except RuntimeError`, translated into `HTTPException(status_code=500, detail="Audio join failed")`.
Regression test `test_join_failure_is_a_clean_500_not_an_unhandled_exception`
exists and passes. Prior commit: `0461faa`.

### WR-04: `OUTPUT_FORMAT` setting is unvalidated

**File:** `backend/app/config.py:36,52-57`
**Reason:** Already fixed. `load_settings()` validates `output_format`
against `_ALLOWED_OUTPUT_FORMATS = {"wav", "mp3"}` and raises `ValueError` on
an unrecognized value, failing fast at settings-load time. Prior commit:
`549b6e4`.

### WR-05: Both container images run as root

**File:** `backend/Containerfile.backend`, `backend/Containerfile.tts`
**Reason:** Already fixed. `Containerfile.backend` creates and switches to
`appuser` (UID 1000); `Containerfile.tts` chowns `/app` to the base image's
existing `ubuntu` user, sets `HOME=/home/ubuntu`, and switches with
`USER ubuntu`. Prior commit: `8dab51d`.

### WR-06: Dual source of truth for pinned `qwen-tts`/`transformers`/`accelerate` versions

**File:** `backend/Containerfile.tts:22-25`, `backend/tts_service/requirements.txt`
**Reason:** Already fixed. `requirements.txt` no longer lists `qwen-tts`,
`transformers`, or `accelerate` — a comment at the top of the file explains
they are intentionally absent and must be bumped only in `Containerfile.tts`.
Prior commit: `8ac7892`.

## Verification

Ran after all IN-01..IN-04 fixes were applied and committed:

```
cd backend && TTS_BACKEND=mock uv run python -m pytest -x -q --tb=short
-> 14 passed, 2 skipped

uv run ruff check .
-> All checks passed!
```

No regressions observed. Each individual fix was also verified with Tier 1
(re-read modified section) and Tier 2 (`python3 -c "import ast; ast.parse(...)"`
syntax check) before being committed.

---

_Fixed: 2026-07-09T16:48:58Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
