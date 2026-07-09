---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
plan: 01
subsystem: backend-walking-skeleton
tags: [fastapi, uv, chunking, ffmpeg, tts-mock, upload]
dependency-graph:
  requires: []
  provides:
    - "POST /projects upload->chunk->synthesize->join->download pipeline"
    - "chunk_paragraphs() greedy paragraph-merge chunker"
    - "synthesize()/tts_health() internal TTS client (mock + http backends)"
    - "join_wavs() ffmpeg concat-demuxer wrapper"
    - "typed Settings module (config.py) with locked env var contract"
  affects:
    - "01-02 (GPU TTS spike) — implements the /synthesize + /healthz HTTP contract this plan defines"
    - "01-03 (two-container integration) — wires TTS_BACKEND=http against a real tts_service container"
tech-stack:
  added:
    - "fastapi==0.139.0, uvicorn==0.51.0, python-multipart==0.0.32, httpx (backend, CPU-only)"
    - "uv (Python dependency/venv manager) — not pre-installed on this host, installed via `pip install --user uv`"
    - "pytest, ruff (dev deps)"
  patterns:
    - "GPU/CPU isolation boundary: backend/app/ never imports torch/qwen_tts; TTS_BACKEND env flag switches mock (stdlib wave/struct silence) vs http (httpx POST to isolated TTS container)"
    - "Server-generated uuid4() filenames only; UploadFile.filename never touches a filesystem path (path-traversal safety)"
    - "ffmpeg invoked via subprocess.run([...]) arg-list only, never shell=True"
    - "Bounded chunked upload read (1 MiB chunks) rejects with 413 as soon as MAX_UPLOAD_BYTES is exceeded, rather than fully buffering an oversized body"
key-files:
  created:
    - backend/pyproject.toml
    - backend/.python-version
    - backend/.gitignore
    - backend/app/__init__.py
    - backend/app/config.py
    - backend/app/chunking.py
    - backend/app/tts_client.py
    - backend/app/audio_join.py
    - backend/app/main.py
    - backend/tests/__init__.py
    - backend/tests/test_e2e.py
    - backend/tests/test_chunking.py
    - backend/uploads/.gitkeep
    - backend/output/.gitkeep
    - frontend/.gitkeep
  modified: []
decisions:
  - "UPLOAD_DIR/OUTPUT_DIR resolved as absolute paths anchored to the repo root (via Path(__file__).resolve().parents[2]) rather than the interface doc's literal relative string \"backend/uploads\" — both pytest and `uv run uvicorn` invocations run with cwd=backend/, where a literal relative \"backend/uploads\" default would double-nest into backend/backend/uploads. Absolute-path resolution keeps the same on-disk location while being invocation-cwd-independent."
  - "CHUNK_TARGET_LEN default set to 800 (within the D-02 500-1000 discretion range); oversized single paragraphs split at sentence boundaries (regex `(?<=[.!?])\\s+`) and greedily re-merged, never mid-word."
  - "`uv` was not installed on this execution host; installed via `pip install --user uv` (official PyPI package, astral-sh) since it is explicitly named as required tooling in CLAUDE.md's Development Tools section, not an LLM-suggested/ambiguous package name."
metrics:
  duration_minutes: 10
  tasks_completed: 3
  files_created: 15
  completed_date: "2026-07-09"
---

# Phase 1 Plan 1: Upload-to-Audio Walking Skeleton (Mock TTS) Summary

A real FastAPI backend (`uv`-managed, no GPU deps) that accepts a `.txt` upload, chunks it into ~800-char paragraph blocks, synthesizes each chunk via a stdlib-only mock TTS backend, joins them with an ffmpeg concat-demuxer subprocess call, and returns one downloadable WAV — proven end-to-end with `TTS_BACKEND=mock` and zero GPU dependency.

## What Was Built

- **`backend/pyproject.toml`** — `uv`-managed Python 3.12 project. CPU-only deps: `fastapi==0.139.0`, `uvicorn==0.51.0`, `python-multipart==0.0.32`, `httpx`. Dev deps: `pytest`, `ruff`. Deliberately contains **no** `torch`/`qwen-tts`/`transformers`/`accelerate` — those live only in the future GPU-scoped TTS container (Plan 02/03).
- **`backend/app/config.py`** — typed `Settings` dataclass loaded from env vars (`TTS_BACKEND`, `TTS_SERVICE_URL`, `TTS_DEFAULT_SPEAKER`, `CHUNK_TARGET_LEN`, `MAX_UPLOAD_BYTES`, `OUTPUT_FORMAT`, `UPLOAD_DIR`, `OUTPUT_DIR`) matching the locked interface contract, with `UPLOAD_DIR`/`OUTPUT_DIR` resolved as cwd-independent absolute paths.
- **`backend/app/chunking.py`** — `chunk_paragraphs(text, target_len=800)`: stdlib regex paragraph split (`\n\s*\n`) with greedy merge up to `target_len`; oversized single paragraphs further split at sentence boundaries and re-merged. No NLP library (D-01).
- **`backend/app/tts_client.py`** — `synthesize(text, speaker)` / `tts_health()`. `TTS_BACKEND=mock` returns a ~0.3s silent 24kHz mono 16-bit WAV built purely with stdlib `wave`/`struct` (no torch/numpy). `TTS_BACKEND=http` POSTs `{"text", "speaker"}` JSON to `{TTS_SERVICE_URL}/synthesize` via `httpx` (connect 5s / read 300s timeout) and checks `{TTS_SERVICE_URL}/healthz` for readiness — this is the internal contract Plan 02's TTS container implements.
- **`backend/app/audio_join.py`** — `join_wavs(wav_paths, out_path, fmt)`: writes an ffmpeg concat-demuxer list file and invokes `ffmpeg` via `subprocess.run([...])` with an explicit argument list (`-c copy` for WAV, `-c:a libmp3lame` for MP3) — never `shell=True`.
- **`backend/app/main.py`** — `POST /projects`: reads the upload in bounded 1 MiB chunks (rejecting with `413` once `MAX_UPLOAD_BYTES` is exceeded), guards the UTF-8 decode (`400` on `UnicodeDecodeError` instead of a 500), chunks the text, synthesizes + writes each chunk under a `uuid4()`-derived filename, joins them, and returns the joined audio as an `audio/wav` `Response`.
- **Tests** — `backend/tests/test_e2e.py` (upload happy path returns `200 audio/wav` with a real RIFF/WAVE body; oversized upload → `413`/`400`; non-UTF-8 upload → `400`) and `backend/tests/test_chunking.py` (empty/whitespace → `[]`; paragraph merge; target_len split; oversized-paragraph sentence-boundary split). All 8 tests pass; `ruff check .` is clean.
- Pre-split monorepo scaffolding: empty `frontend/.gitkeep` per D-10; `backend/.gitignore` excludes `.venv`/caches while keeping `uploads/`/`output/` tracked via `.gitkeep`.

## Verification Performed

- `cd backend && TTS_BACKEND=mock uv run pytest tests/ -q` → 8 passed.
- `cd backend && uv run ruff check .` → clean.
- Manual smoke test: started `uv run uvicorn app.main:app --port 8123` with `TTS_BACKEND=mock`, `curl -F file=@sample.txt http://localhost:8123/projects -o out.wav` → real HTTP `200`, `out.wav` begins with `RIFF`/`WAVE` bytes (confirmed via `xxd`).
- `grep -rn "^import torch\|^import qwen_tts"` under `backend/app/` → none found; `pyproject.toml` contains none of `torch`/`qwen-tts`/`transformers`/`accelerate`.
- `grep uuid4 app/main.py` matches; `UploadFile.filename` is not used in any path construction; `grep -r shell=True app/` returns nothing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] `uv` was not installed on the execution host**
- **Found during:** Task 1 (attempting `uv sync`/`uv run`)
- **Issue:** `which uv` failed; `uv` is required by every verification command in the plan and is explicitly the mandated tool per CLAUDE.md's Development Tools section (D-11).
- **Fix:** Installed via `pip install --user uv` (official PyPI package published by astral-sh — not an ambiguous/LLM-suggested name, and explicitly named in the project's own CLAUDE.md, so this was treated as required dev tooling rather than a Rule-3-excluded "referenced package" install). `~/.local/bin` was already on `PATH`, so no shell profile changes were needed.
- **Files modified:** None (host-level tool install only).
- **Commit:** N/A (no repo changes).

**2. [Rule 2 - Missing critical functionality] Added `backend/.gitignore`**
- **Found during:** Task 1, before first commit
- **Issue:** Without a `.gitignore`, `uv sync` would have left `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` as candidates for accidental staging, and runtime-generated WAVs under `uploads/`/`output/` would pollute `git status` on every test run.
- **Fix:** Added `backend/.gitignore` excluding `.venv/`, caches, and `uploads/*`/`output/*` while explicitly keeping `.gitkeep` markers.
- **Files modified:** `backend/.gitignore`
- **Commit:** `397c21e`

**3. [Rule 1 - Bug] `ruff` B008 false-positive on FastAPI's `File(...)` dependency-injection default**
- **Found during:** Task 2
- **Issue:** `ruff check .` flagged `file: UploadFile = File(...)` under bugbear rule B008 ("do not perform function call in argument defaults") — this is FastAPI's standard, documented dependency-injection pattern (also RESEARCH.md's own Code Example), not a real bug.
- **Fix:** Added a targeted `# noqa: B008` on that line rather than disabling the bugbear rule project-wide.
- **Files modified:** `backend/app/main.py`
- **Commit:** `e2a6538`

**4. [Rule 1 - Bug] Docstring literal collided with the plan's own regression grep**
- **Found during:** Task 3 verification
- **Issue:** `audio_join.py`'s security-note docstring contained the literal substring `shell=True` (as a "never do this" caution), which false-triggered the plan's `! grep -rq "shell=True" app/` verification check — no actual `shell=True` usage existed.
- **Fix:** Reworded the docstring to describe the same constraint without using the literal flag syntax.
- **Files modified:** `backend/app/audio_join.py`
- **Commit:** `e656b64`

None of the above required user input — all fell within Rules 1-3 (bug fix / missing critical functionality / blocking-issue auto-fix).

## Known Stubs

None. The mock TTS backend (`TTS_BACKEND=mock`) is an intentional, documented stand-in for the real GPU model per CLAUDE.md's `TTS_BACKEND` dev-degradation pattern and this plan's explicit scope (Plan 02 implements the real GPU-backed `/synthesize` server this plan's `tts_client.py` already calls when `TTS_BACKEND=http`). It is not a stub masking incomplete work — it is the documented Phase 1 Plan 1 deliverable.

## Threat Flags

None. All new surface (upload endpoint, ffmpeg subprocess, filesystem writes) was explicitly anticipated and mitigated per the plan's `<threat_model>` (T-01-01 through T-01-04); no additional trust-boundary-crossing surface was introduced beyond what the plan specified.

## Self-Check: PASSED

All 13 created files verified present on disk; all 5 task/summary commits (397c21e, e2a6538, 1409536, e656b64, 65159a4) verified present in git log.
