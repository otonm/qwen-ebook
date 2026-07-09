---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
fixed_at: 2026-07-09T16:30:00Z
review_path: .planning/phases/01-upload-to-audio-spike-tts-rocm-de-risk/01-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-07-09T16:30:00Z
**Source review:** .planning/phases/01-upload-to-audio-spike-tts-rocm-de-risk/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (2 critical, 6 warning; `fix_scope=critical_warning`, so the 4 Info findings IN-01..IN-04 were not attempted)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: Empty/whitespace-only upload crashes with an unhandled exception instead of a clean 400

**Files modified:** `backend/app/main.py`, `backend/tests/test_e2e.py`
**Commit:** b2010dc
**Applied fix:** Added a `chunks` emptiness check right after `chunk_paragraphs()` in `create_project()`, raising `HTTPException(400, "Upload contains no synthesizable text")` before any TTS/ffmpeg work starts. Added regression test `test_empty_upload_is_rejected_with_400` (whitespace-only body → 400).

### CR-02: Blocking synchronous I/O inside `async def` route handlers stalls the entire event loop for the whole generation job

**Files modified:** `backend/app/main.py`, `backend/tts_service/server.py`
**Commit:** 7cf6878
**Applied fix:** Wrapped `synthesize()`, `chunk_path.write_bytes()`, `join_wavs()`, and `output_path.read_bytes()` in `starlette.concurrency.run_in_threadpool()` inside `main.py`'s `create_project()`. Applied the equivalent fix to `tts_service/server.py`'s `/synthesize` handler, offloading the GPU-bound `_model_module.synthesize_wav()` call to the threadpool so `/healthz` and other requests are no longer blocked for the duration of a synthesis call. Verified by full test suite (mock backend) and `py_compile` on `tts_service/server.py` (GPU service, not runtime-testable on this host).

## Warnings

### WR-01: Generated chunk/output files are never cleaned up — unbounded disk growth, including orphaned files on error paths

**Files modified:** `backend/app/main.py`, `backend/tests/test_e2e.py`
**Commit:** 9fce687
**Applied fix:** Wrapped the per-chunk synthesis loop and the join call in a `try`/`finally` that unlinks every chunk file actually written, on both the success and failure paths (chunk files are scratch — no longer needed once the join succeeds, and must not survive a partial failure). Added regression test `test_chunk_files_are_cleaned_up_after_successful_join`, and verified end-to-end against a real built `Containerfile.backend` image (see WR-05 verification below) that `UPLOAD_DIR` is empty after a request.

### WR-02: TTS service 4xx client errors are misreported as 502 "TTS service unavailable"

**Files modified:** `backend/app/main.py`, `backend/tests/test_e2e.py`
**Commit:** cf81086
**Applied fix:** Added an `except httpx.HTTPStatusError` branch before the generic `except httpx.HTTPError` in the synthesize-call error handling, checking `exc.response.status_code < 500` and surfacing `f"TTS service rejected request: {exc.response.text}"` for genuine 4xx responses, while still collapsing 5xx/connectivity failures to the generic 502. Added regression test `test_tts_4xx_response_is_surfaced_as_502_with_reason_not_generic` (monkeypatches `synthesize` to raise a 400 `HTTPStatusError` and asserts the reason text is preserved in the response detail).

### WR-03: `ffmpeg`/join failures are not caught in `main.py`, unlike TTS failures

**Files modified:** `backend/app/main.py`, `backend/tests/test_e2e.py`
**Commit:** 0461faa
**Applied fix:** Wrapped the `join_wavs()` call in `try`/`except RuntimeError`, translating any `ffmpeg` non-zero-exit failure into a clean `HTTPException(500, "Audio join failed")` instead of letting it propagate as an unhandled exception. Added regression test `test_join_failure_is_a_clean_500_not_an_unhandled_exception` (monkeypatches `join_wavs` to raise `RuntimeError` and asserts a clean 500).

### WR-04: `OUTPUT_FORMAT` setting is unvalidated and can produce a codec/container/Content-Type mismatch

**Files modified:** `backend/app/config.py`, `backend/tests/test_config.py` (new file)
**Commit:** 549b6e4
**Applied fix:** `load_settings()` now validates `OUTPUT_FORMAT` against `{"wav", "mp3"}` and raises `ValueError` immediately on an unrecognized value, rather than letting an unvalidated format silently fall through the `else` branches in `audio_join.py`/`main.py`. Added a new `tests/test_config.py` covering both the accepted-values case and the rejection case.

### WR-05: Both container images run as root — no non-root `USER` in either Containerfile

**Files modified:** `backend/Containerfile.backend`, `backend/Containerfile.tts`, `deploy/run-local.sh`
**Commit:** 8dab51d
**Applied fix:** Adapted the review's literal suggestion after discovering it would have broken two things if applied blindly:
1. `Containerfile.backend`'s app resolves default `UPLOAD_DIR`/`OUTPUT_DIR` to `/backend/uploads`/`/backend/output` (a repo-root-anchored path that lands at the container filesystem root) — a non-root user can't `mkdir` there at request time, so those directories are now pre-created and `chown`'d to a new `appuser` (uid 1000) at build time, before `USER appuser`.
2. `Containerfile.tts`'s base image (`rocm/pytorch:...ubuntu24.04...`) already ships a UID-1000 `ubuntu` user — `useradd --uid 1000` collided (`useradd: UID 1000 is not unique`), caught by an actual `podman build`. Switched to reusing the existing `ubuntu` user instead of creating a new one. Also moved `HOME` to `/home/ubuntu` (the Hugging Face cache defaults to `$HOME/.cache/huggingface`, unwritable by a non-root user under `/root`) and updated `deploy/run-local.sh`'s named-volume mount from `/root/.cache/huggingface` to `/home/ubuntu/.cache/huggingface` to match — required for the fix to not silently break the documented HF model cache persistence across pod restarts.

**Verification (beyond py_compile/ruff, since this is a Containerfile change):** Actually built and ran both images locally with `podman build`/`podman run` (base images were already cached on this host):
- `Containerfile.backend`: built cleanly; confirmed the running container is `uid=1000(appuser)`; issued a real `POST /projects` against it (mock TTS backend) — got `200`, the output WAV was written under `/backend/output` owned by `appuser`, and `/backend/uploads` was empty afterward (WR-01 also verified end-to-end this way).
- `Containerfile.tts`: built cleanly (including a full pip-install re-run after the WR-06 requirements.txt change below); confirmed `id` reports `uid=1000(ubuntu)`, `$HOME=/home/ubuntu`, and Python's `os.path.expanduser("~/.cache/huggingface")` resolves to `/home/ubuntu/.cache/huggingface` matching the updated volume mount. Real GPU inference itself remains untested on this host per the existing, accepted `GPU-ENABLEMENT.md` limitation (out of scope for this review, per review instructions).
Both test images were removed after verification; no test artifacts left behind.

### WR-06: Dual source of truth for pinned `qwen-tts`/`transformers`/`accelerate` versions

**Files modified:** `backend/tts_service/requirements.txt`
**Commit:** 8ac7892
**Applied fix:** Removed the `qwen-tts==0.1.1`, `transformers==4.57.3`, `accelerate==1.12.0` lines from `requirements.txt` (they're already installed explicitly and pinned in `Containerfile.tts` via `--no-deps` + exact-pin `pip install` steps preceding the `requirements.txt` install), and added a comment explaining why they're intentionally absent, so `Containerfile.tts` is the single source of truth for those three pins.

**Verification:** Rebuilt `Containerfile.tts` end-to-end with the updated `requirements.txt` (full pip install re-run, since the `COPY requirements.txt` layer hash changed) and confirmed via `importlib.metadata.version()` inside the built image that `qwen-tts`, `transformers`, and `accelerate` still resolve to exactly `0.1.1`, `4.57.3`, `1.12.0` — i.e. removing the duplicate pins did not change the installed versions.

## Skipped Issues

None — all 8 in-scope findings (CR-01, CR-02, WR-01 through WR-06) were fixed. The 4 Info findings (IN-01 through IN-04) were out of scope for this run (`fix_scope=critical_warning`) and were not attempted.

## Verification Summary

- `TTS_BACKEND=mock uv run python -m pytest -q` (backend): 14 passed, 2 skipped (skipped tests require a live two-container pod, per `test_integration.py`'s own skip condition) after every commit — was 8 passed/2 skipped at the start of this run.
- `uv run ruff check .` (backend): clean after every commit.
- `Containerfile.backend` and `Containerfile.tts`: both actually built and run-tested locally with `podman build`/`podman run` for the WR-05/WR-06 fixes (see verification notes above), since neither has a syntax checker in the standard verification-tier table and the changes carried real risk of breaking the container at runtime if applied literally.
- `backend/tts_service/*` Python source changes (CR-02's `server.py` edit): verified via `python -m py_compile` and `ruff` only, per this task's instructions — not runtime-tested (no working GPU on this host).

---

_Fixed: 2026-07-09T16:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
