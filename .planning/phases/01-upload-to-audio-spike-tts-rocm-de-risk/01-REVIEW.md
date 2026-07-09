---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
reviewed: 2026-07-09T12:00:00Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - backend/app/audio_join.py
  - backend/app/chunking.py
  - backend/app/config.py
  - backend/app/__init__.py
  - backend/app/main.py
  - backend/app/tts_client.py
  - backend/Containerfile.backend
  - backend/Containerfile.backend.dockerignore
  - backend/Containerfile.tts
  - backend/.gitignore
  - backend/GPU-ENABLEMENT.md
  - backend/output/.gitkeep
  - backend/pyproject.toml
  - backend/tests/__init__.py
  - backend/tests/test_chunking.py
  - backend/tests/test_e2e.py
  - backend/tests/test_integration.py
  - backend/tts_service/__init__.py
  - backend/tts_service/model.py
  - backend/tts_service/requirements.txt
  - backend/tts_service/server.py
  - backend/tts_service/smoke_gpu.py
  - backend/uploads/.gitkeep
  - deploy/qwen-ebook-pod.yaml
  - deploy/README.md
  - deploy/run-local.sh
  - frontend/.gitkeep
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-09T12:00:00Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Reviewed the mock-backed FastAPI pipeline (`backend/app/*`), the GPU-scoped TTS
inference container (`backend/tts_service/*`, `Containerfile.tts`), and the
two-container Podman pod wiring (`Containerfile.backend`, `deploy/*`). Path
handling for uploads is genuinely path-traversal-safe (server-generated UUID
filenames only), `ffmpeg` is invoked via an explicit argument list with no
shell interpolation, and the GPU/CPU process isolation is real (verified: no
`torch`/`qwen_tts` import anywhere in `backend/app`). The known, accepted GPU
inference limitation on the local unsupported dev GPU (`GPU-ENABLEMENT.md`) is
out of scope per review instructions and is not flagged below.

Two confirmed, reproducible correctness bugs were found: (1) uploading an
empty/whitespace-only file crashes the request with an unhandled `ValueError`
instead of a clean 400 (reproduced against the real `TestClient`), and (2)
every I/O-bound step of the pipeline (TTS HTTP call, disk writes, `ffmpeg`
subprocess, and the GPU inference call itself in the TTS container) is
invoked with blocking/synchronous APIs from inside `async def` route
handlers, which fully blocks the single-process event loop for the entire
duration of a generation job — undermining both request concurrency and the
SSE-based live-progress design the tech stack doc commits to for a later
phase. Several further warnings cover unbounded disk growth from orphaned
files, lossy error-status collapsing, containers running as root, and a
dual-source-of-truth version-pinning hazard in the TTS image build. Note: I
verified experimentally (via a scratch `buildah`/`podman build` test on this
host, `buildah 1.43.2`) that the `Containerfile.backend.dockerignore` naming
convention actually is honored by this Podman/buildah version, so that is
*not* flagged as a bug.

## Critical Issues

### CR-01: Empty/whitespace-only upload crashes with an unhandled exception instead of a clean 400

**File:** `backend/app/main.py:58-90`
**Issue:** `chunk_paragraphs()` returns `[]` for empty or whitespace-only
input (`backend/app/chunking.py:52-53`). When that happens, the `for index,
chunk_text in enumerate(chunks)` loop in `create_project()` never executes,
so `chunk_paths` stays `[]`, and `join_wavs([], ...)` is then called
unconditionally at line 90. `join_wavs` immediately raises
`ValueError("wav_paths must not be empty")` (`backend/app/audio_join.py:24`),
which is never caught anywhere in `main.py`. This propagates out of the route
handler as an unhandled exception — reproduced directly against the app:

```
$ uv run python -c "... POST /projects with a whitespace-only file ..."
raised <class 'ValueError'> wav_paths must not be empty
```

In production (behind real `uvicorn`, not `TestClient`) this becomes a bare
500 Internal Server Error for a completely ordinary user action (uploading a
blank document, a chapter placeholder, or a file that is whitespace after
encoding normalization). There is no test covering this case — `test_e2e.py`
only covers oversized and non-UTF-8 uploads, not empty content.
**Fix:** Validate `chunks` right after computing it and fail with a clean
400 before any TTS/ffmpeg work starts:
```python
chunks = chunk_paragraphs(text, target_len=settings.CHUNK_TARGET_LEN)
if not chunks:
    raise HTTPException(
        status_code=400, detail="Upload contains no synthesizable text"
    )
```
Add a regression test asserting `client.post("/projects", files={"file": ("empty.txt", b"   \n\n  ", "text/plain")})` returns 400.

### CR-02: Blocking synchronous I/O inside `async def` route handlers stalls the entire event loop for the whole generation job

**File:** `backend/app/main.py:76` (via `backend/app/tts_client.py:49-55`), `backend/app/main.py:86-90` (via `backend/app/audio_join.py:39-55`), `backend/tts_service/server.py:90-108` (via `backend/tts_service/model.py:74-82`)
**Issue:** `create_project()` in `main.py` is declared `async def`, but every
step inside it is a blocking call executed directly on the asyncio event
loop, not offloaded to a thread pool:
- `synthesize()` (`tts_client.py:49`) uses the module-level `httpx.post(...)`
  (a synchronous call) with up to a 300s read timeout, called once per
  chunk in a loop — for a full-length book this can block the loop for many
  minutes to hours.
- `chunk_path.write_bytes(chunk_audio)` (`main.py:86`) is a synchronous
  file write.
- `join_wavs()` (`main.py:90`) calls `subprocess.run(..., capture_output=True)`
  (`audio_join.py:39`) synchronously, blocking until `ffmpeg` exits.

The same anti-pattern exists across the internal HTTP boundary: the TTS
container's `@app.post("/synthesize")` handler in `tts_service/server.py` is
also `async def`, yet calls `_model_module.synthesize_wav(...)`
(`server.py:98`) directly — a synchronous, GPU-bound call
(`model.py:74-82`) that can take a long time per chunk.

Because uvicorn's default single worker runs one event loop, any one of
these blocking calls freezes the *entire* ASGI application for its duration
— not just the in-flight request. Concretely: while a generation job is
running, the TTS container's own `/healthz` endpoint (used by
`deploy/run-local.sh`'s readiness loop and any future liveness probe) cannot
be served, and no other request to either service can be handled. This also
directly conflicts with the tech-stack plan to use
`fastapi.sse.EventSourceResponse` for live per-segment progress in a later
phase — that requires the event loop to remain free to push SSE frames while
generation is in flight, which this blocking-call pattern makes impossible
without also being fixed.
**Fix:** Either declare these routes as plain `def` (FastAPI/Starlette
automatically dispatches sync `def` routes to a thread pool), or explicitly
offload blocking calls:
```python
from starlette.concurrency import run_in_threadpool

chunk_audio = await run_in_threadpool(synthesize, chunk_text, settings.TTS_DEFAULT_SPEAKER)
...
await run_in_threadpool(join_wavs, chunk_paths, str(output_path), fmt=settings.OUTPUT_FORMAT)
```
or switch `tts_client.synthesize()` to `httpx.AsyncClient` and `await` it.
Apply the equivalent fix to `tts_service/server.py`'s `/synthesize` handler
(`run_in_threadpool(_model_module.synthesize_wav, req.text, req.speaker)`).

## Warnings

### WR-01: Generated chunk/output files are never cleaned up — unbounded disk growth, including orphaned files on error paths

**File:** `backend/app/main.py:85-93`
**Issue:** Every successful request writes N chunk WAV files to `UPLOAD_DIR`
and one joined file to `OUTPUT_DIR`, and none of them are ever deleted —
there is no TTL, no cleanup-on-response, and no cleanup in an error path. If
a request fails partway through the synthesis loop (e.g. chunk 5 of 10 hits
a `httpx.TimeoutException`), the already-written chunk files for indices 0-4
are silently orphaned on disk forever. For a personal tool that will be used
repeatedly on full-length books, this is a real and fast-growing disk-usage
problem, not merely a performance concern.
**Fix:** Clean up chunk files after a successful join (they're no longer
needed once `output_path` exists), and wrap the per-request work in a
`try/finally` that removes any partially-written chunk files on failure.
Consider also expiring old files in `OUTPUT_DIR` on a schedule or cap, since
there is currently no project/session concept tying a client to its own
output for later cleanup.

### WR-02: TTS service 4xx client errors are misreported as 502 "TTS service unavailable"

**File:** `backend/app/main.py:75-84`
**Issue:** `synthesize()` in `tts_client.py` calls
`response.raise_for_status()` (line 54), which raises
`httpx.HTTPStatusError` (a subclass of `httpx.HTTPError`) for *any*
non-2xx response, including the TTS service's intentional `400` responses
for an unsupported speaker or oversized text (`tts_service/server.py:99-103`,
`model.py:67-68`). `main.py`'s `except httpx.HTTPError` catch-all
(lines 81-84) then converts every such case — genuine connectivity failures
*and* legitimate 4xx client/config errors alike — into a generic `502 TTS
service unavailable`, discarding the actual reason and misleading the
caller about where the fault lies (a config problem like an invalid
`TTS_DEFAULT_SPEAKER` looks identical to the TTS container being down).
**Fix:** Distinguish status ranges before mapping:
```python
except httpx.HTTPStatusError as exc:
    if exc.response.status_code < 500:
        raise HTTPException(status_code=502, detail=f"TTS service rejected request: {exc.response.text}") from exc
    raise HTTPException(status_code=502, detail="TTS service unavailable") from exc
except httpx.TimeoutException as exc:
    raise HTTPException(status_code=504, detail="TTS service timed out") from exc
except httpx.HTTPError as exc:
    raise HTTPException(status_code=502, detail="TTS service unavailable") from exc
```

### WR-03: `ffmpeg`/join failures are not caught in `main.py`, unlike TTS failures

**File:** `backend/app/main.py:90`
**Issue:** `join_wavs()` raises a plain `RuntimeError` on any `ffmpeg`
non-zero exit (`audio_join.py:56-57`) — e.g. a bad `OUTPUT_FORMAT`
value (see WR-04), a corrupt intermediate chunk, or `ffmpeg` missing from
`PATH`. Unlike the TTS call a few lines above, which is carefully wrapped to
translate failures into clean 502/504 responses, this call is not wrapped at
all, so any join failure becomes an unhandled exception (bare 500 in
production) with no attempt at a clean client-facing error.
**Fix:** Wrap the `join_wavs()` call similarly:
```python
try:
    join_wavs(chunk_paths, str(output_path), fmt=settings.OUTPUT_FORMAT)
except RuntimeError as exc:
    raise HTTPException(status_code=500, detail="Audio join failed") from exc
```

### WR-04: `OUTPUT_FORMAT` setting is unvalidated and can produce a codec/container/Content-Type mismatch

**File:** `backend/app/config.py:38,50`, `backend/app/main.py:89-92`, `backend/app/audio_join.py:38`
**Issue:** `OUTPUT_FORMAT` is read as a raw string with no allowed-value
check. `main.py` only special-cases the literal `"wav"` for both the
`ffmpeg` codec args (`audio_join.py:38`: anything other than `"wav"` gets
`-c:a libmp3lame`) and the response `media_type` (`main.py:92`: anything
other than `"wav"` gets `audio/mpeg`). If `OUTPUT_FORMAT` is ever set to
anything besides `"wav"`/`"mp3"` (e.g. a typo like `"mp e"`, or a
future `"flac"`), the output filename extension, the actual encoded codec
(forced to `libmp3lame` for any non-"wav" value), and the `Content-Type`
header can all disagree, and `ffmpeg` may fail outright (feeding
`libmp3lame` output into a `.flac`-suffixed muxer).
**Fix:** Validate `OUTPUT_FORMAT` against `{"wav", "mp3"}` in
`load_settings()` and raise/fail fast on an unrecognized value, rather than
silently falling through the `else` branch in two unrelated places.

### WR-05: Both container images run as root — no non-root `USER` in either Containerfile

**File:** `backend/Containerfile.backend`, `backend/Containerfile.tts`
**Issue:** Neither `Containerfile.backend` nor `Containerfile.tts` declares
a `USER` instruction, so both images run their `uvicorn` process as root by
default. `Containerfile.tts` also runs with `--security-opt label=disable`
in `deploy/run-local.sh` (an accepted, documented tradeoff for this specific
dev host per `GPU-ENABLEMENT.md`), which further weakens container
confinement — combining that with a root process increases blast radius if
either service is ever compromised (e.g. via a future dependency CVE in the
FastAPI/httpx/qwen-tts stack). Neither container needs root for its actual
job (serving HTTP, running `ffmpeg`, or running GPU inference — GPU access
is via group membership on `/dev/kfd`/`/dev/dri`, not root).
**Fix:** Add a non-root `USER` in both Containerfiles (for `Containerfile.tts`,
ensure the created user is a member of the group(s) that own
`/dev/kfd`/`/dev/dri` inside the container, or rely on `--group-add
keep-groups` as already used, which maps host supplementary groups in
regardless of the in-container user).

### WR-06: Dual source of truth for pinned `qwen-tts`/`transformers`/`accelerate` versions

**File:** `backend/Containerfile.tts:22-25`, `backend/tts_service/requirements.txt:10-12`
**Issue:** `Containerfile.tts` explicitly pins `qwen-tts==0.1.1`,
`transformers==4.57.3`, and `accelerate==1.12.0` via dedicated `pip install`
steps (with `--no-deps` on `qwen-tts` specifically, per the comment, "so
nothing else in requirements.txt can override them via normal resolution").
However, `requirements.txt` itself *also* lists all three packages at the
same exact pins (lines 10-12), and the final build step
(`pip install --no-cache-dir -r /app/tts_service/requirements.txt`, line 24)
installs from that file *without* `--no-deps`. Today the versions happen to
match, so this is a no-op — but the two places must be kept manually in sync
by hand for every future version bump; if one is updated without the other,
the resulting build is either inconsistent or (worse) the final
`pip install -r requirements.txt` step is exactly the kind of "normal
resolution" pass the `--no-deps` step's own comment says it is meant to
prevent, since `qwen-tts` is resolved a second time here without
`--no-deps`.
**Fix:** Keep the version pin in exactly one place — e.g. remove
`qwen-tts`/`transformers`/`accelerate` from `requirements.txt` entirely
(since they're already installed by the preceding explicit `pip install`
lines) and add a comment there explaining why they're intentionally absent,
so there's a single, unambiguous source of truth for those three pins.

## Info

### IN-01: Misleading comment claims frozen `Settings` dataclass attributes can be monkeypatched

**File:** `backend/app/config.py:56-58`
**Issue:** The trailing comment says "tests that need different env vars
should reload the module or monkeypatch `settings` attributes," but
`Settings` is `@dataclass(frozen=True)` (line 31), so directly monkeypatching
an attribute on the singleton raises `dataclasses.FrozenInstanceError`
(verified: `settings.MAX_UPLOAD_BYTES = 5` raises `FrozenInstanceError`).
Only reloading the module, or monkeypatching the whole `app.config.settings`
name to a different `Settings` instance, actually works.
**Fix:** Correct the comment, e.g.: "tests that need different env vars
should reload the module, or use `monkeypatch.setattr(app.config, 'settings', Settings(...))` to swap the whole singleton — individual fields can't be
patched since `Settings` is frozen."

### IN-02: `tts_health()` is dead code — defined but never called

**File:** `backend/app/tts_client.py:60-72`
**Issue:** `tts_health()` implements a `/healthz` check against the TTS
service but is not imported or called anywhere in `backend/app` (confirmed
via repo-wide search — the only match for `tts_health` is its own
definition). `main.py` has no health-check endpoint of its own and never
uses this helper.
**Fix:** Either wire it into a backend `/healthz` endpoint (useful for the
pod's own readiness checks) or remove it until it has a caller.

### IN-03: `sox` dependency in `tts_service/requirements.txt` is unused and its native binary is not installed

**File:** `backend/tts_service/requirements.txt:17`, `backend/Containerfile.tts`
**Issue:** `sox` (the PyPI Python wrapper around the `sox` CLI tool) is
listed in `requirements.txt` but is not imported anywhere in
`tts_service/model.py` or `tts_service/server.py`, and `Containerfile.tts`
never installs the underlying `sox` system binary via `apt`. If this
dependency actually is required transitively by `qwen-tts` at runtime, the
Python wrapper would fail the moment it tries to invoke the (missing)
`sox` binary; if it isn't required, it's simply dead weight.
**Fix:** Confirm whether `qwen-tts` genuinely needs the `sox` binary at
runtime; if so, install it via `apt-get install -y sox` in
`Containerfile.tts` and add a comment explaining why; if not, drop it from
`requirements.txt`.

### IN-04: No `Content-Disposition` header on the generated audio response

**File:** `backend/app/main.py:93`
**Issue:** The final `Response(content=..., media_type=media_type)` has no
`Content-Disposition` header, so a browser or `curl -O` downloading the
result gets no suggested filename (this is also why `deploy/README.md`'s
example instructs `curl ... -o audiobook.wav` explicitly). Minor UX gap,
worth fixing before this becomes a browser-facing feature in a later phase.
**Fix:** `Response(..., headers={"Content-Disposition": f'attachment; filename="{project_id}.{settings.OUTPUT_FORMAT}"'})`.

---

_Reviewed: 2026-07-09T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
