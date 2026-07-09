# Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk) - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 13 (new; 0 modified — greenfield repo)
**Analogs found:** 0 / 13 (no prior source code exists in this repo)

## Important: This is the project's first phase

The repository currently contains only `CLAUDE.md`, `.git/`, `.claude/`, and `.planning/` — confirmed by directory listing at pattern-mapping time. There is **no existing application code** (no `backend/`, no `frontend/`, no prior commits touching source files). Consequently:

- There are **zero codebase analogs** for any file in this phase's scope.
- `CLAUDE.md`'s Technology Stack section and RESEARCH.md's "Recommended Project Structure" / "Architecture Patterns" sections are the only available pattern sources, and function as the de facto analog until real code exists.
- The Step 5.5 convention-derivation tool was run and returned `{"skipped": true, "reason": "no-readable-files"}` — there are no files to derive file-naming/identifier/export/import conventions from yet. The `## Conventions` section below reflects this null result; Phase 2's pattern-mapper should re-run derivation once this phase's code lands, since Phase 1 sets the conventions Phase 2 will then be able to detect.
- Every file below is classified using CONTEXT.md/RESEARCH.md's decisions (D-01–D-11) and RESEARCH.md's Architecture Patterns section, with concrete code sourced directly from RESEARCH.md's "Code Examples" and "Pattern 1/2" sections (the closest thing to verified, concrete code available pre-implementation).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/app/main.py` | controller (route) | request-response (multipart upload in, file download out) | none (greenfield) | no-analog — pattern sourced from RESEARCH.md Code Examples |
| `backend/app/chunking.py` | utility / transform | transform (text -> list[str]) | none (greenfield) | no-analog — pattern sourced from RESEARCH.md Pattern 2 |
| `backend/app/tts_client.py` | service (HTTP client) | request-response (internal HTTP call to TTS container) | none (greenfield) | no-analog — pattern sourced from RESEARCH.md Architecture Diagram / Pattern 1 |
| `backend/app/audio_join.py` | utility / file-I/O | file-I/O (subprocess -> ffmpeg -> file) | none (greenfield) | no-analog — pattern sourced from RESEARCH.md Code Examples (ffmpeg concat) |
| `backend/app/config.py` | config | — (env var loading) | none (greenfield) | no-analog — pattern implied by CLAUDE.md (`TTS_BACKEND`, `TTS_SERVICE_URL` env flags) |
| `backend/tts_service/server.py` | controller (internal route) | request-response (text in, WAV bytes out) | none (greenfield) | no-analog — pattern sourced from RESEARCH.md Pattern 1 / Architecture Diagram |
| `backend/tts_service/model.py` | model / service (GPU inference wrapper) | request-response (synchronous inference call) | none (greenfield) | no-analog — pattern sourced from RESEARCH.md Pattern 1 (`Qwen3TTSModel.from_pretrained`) |
| `backend/Containerfile.backend` | config (container build) | — | none (greenfield) | no-analog — pattern implied by CLAUDE.md (Podman, ffmpeg apt-get install) |
| `backend/Containerfile.tts` | config (container build) | — | none (greenfield) | no-analog — pattern implied by CLAUDE.md + RESEARCH.md (`rocm/pytorch` base, `/dev/kfd`+`/dev/dri`) |
| `backend/pyproject.toml` | config (dependency manifest) | — | none (greenfield) | no-analog — `uv`-managed per D-11 |
| `backend/uploads/` , `backend/output/` | storage (filesystem dirs) | file-I/O | none (greenfield) | no-analog — plain local dirs per RESEARCH.md structure, no DB this phase |
| `frontend/` | — (empty placeholder dir) | — | none (greenfield) | no-analog — D-10, stays empty this phase |
| `backend/tests/test_chunking.py` (implied by CONTEXT.md's Claude-discretion chunk-length choice and general good practice; not explicitly named but a natural test target) | test | transform (assert chunk output) | none (greenfield) | no-analog — no test framework/convention established yet; planner should pick one (e.g. `pytest`, matching `uv`/FastAPI ecosystem norms) and record it as the new convention |

## Pattern Assignments

Since there is no prior code, each "pattern assignment" below cites the **RESEARCH.md section** it is drawn from instead of a codebase file+line-range analog. Treat these as the seed patterns for this phase; there is nothing to copy from within this repo.

### `backend/app/main.py` (controller, request-response)

**Analog:** none — source: RESEARCH.md "Code Examples > FastAPI upload endpoint (ING-01)"

**Core pattern:**
```python
from fastapi import FastAPI, UploadFile, File

app = FastAPI()

@app.post("/projects")
async def create_project(file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8")
    # -> chunk_paragraphs(text) -> per-chunk TTS calls -> ffmpeg join -> return audio
    ...
```

**Security note to apply (RESEARCH.md Security Domain, V5/V12):** never use `file.filename` directly to build a server-side path (path traversal risk) — generate a server-side filename/UUID and store original name only as metadata; enforce a max upload size before reading fully into memory.

---

### `backend/app/chunking.py` (utility, transform)

**Analog:** none — source: RESEARCH.md "Pattern 2: Greedy paragraph-merge chunking (D-01/D-02)"

**Core pattern:**
```python
import re

def chunk_paragraphs(text: str, target_len: int = 800) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    chunks, buf = [], ""
    for p in paragraphs:
        if buf and len(buf) + len(p) + 2 > target_len:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)
    return chunks
```
Notes: this is stdlib-only per D-01 (no NLTK/spaCy). `target_len` (500-1000 range) and oversized-single-paragraph handling are Claude's discretion per CONTEXT.md — decide and document the chosen value in the plan/implementation, don't leave it implicit.

---

### `backend/tts_service/server.py` + `backend/tts_service/model.py` (controller + model/service, request-response)

**Analog:** none — source: RESEARCH.md "Pattern 1: Isolated GPU-scoped TTS container behind an internal HTTP boundary"

**Core pattern (model load, once at startup, not per-request):**
```python
# tts_service/server.py — loaded once, not per-request
import torch
from qwen_tts import Qwen3TTSModel

model = Qwen3TTSModel.from_pretrained(
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    device_map="cuda:0",       # ROCm PyTorch keeps the "cuda" device string for compatibility
    dtype=torch.bfloat16,
    attn_implementation="sdpa",  # ROCm-safe; NOT the package README's default flash_attention_2
)
```
**Anti-pattern to avoid (RESEARCH.md Anti-Patterns):** do not load the model per HTTP request — load once at process startup and hold it resident in `model.py`, with `server.py` exposing a thin `/synthesize` endpoint that calls the already-loaded model.

**Internal HTTP contract:** RESEARCH.md leaves the exact `/synthesize` request/response shape as Claude's discretion within the locked two-container-isolation constraint (Open Question 2) — the planner should specify this concretely (e.g., JSON `{text, speaker}` in, `audio/wav` bytes out, or multipart) since no analog exists to copy from.

---

### `backend/app/tts_client.py` (service/HTTP client, request-response)

**Analog:** none — source: RESEARCH.md Architecture Diagram (backend container "POST /synthesize (HTTP, same Podman pod)")

**Core pattern (no verified code sample exists yet in RESEARCH.md — plan should specify a standard `httpx`/`requests` POST to `TTS_SERVICE_URL` per chunk, collecting the returned WAV bytes to a local file per chunk index).** This is a genuine no-analog gap: RESEARCH.md's Code Examples section covers upload and ffmpeg join concretely but does not give a worked internal-HTTP-client example. The planner should treat the internal API contract (request/response schema, error handling for TTS container failures/timeouts) as net-new design, informed by Open Question 2 in RESEARCH.md.

---

### `backend/app/audio_join.py` (utility, file-I/O)

**Analog:** none — source: RESEARCH.md "Code Examples > ffmpeg concat demuxer join (GEN-04)"

**Core pattern:**
```bash
# list.txt contains lines like: file 'chunk_000.wav'
ffmpeg -f concat -safe 0 -i list.txt -c copy output.wav
# For MP3 output where inputs are WAV (re-encode needed, not a stream copy):
ffmpeg -f concat -safe 0 -i list.txt -c:a libmp3lame output.mp3
```
**Security note to apply (RESEARCH.md Security Domain — command injection):** always invoke via `subprocess.run([...])` with an explicit argument list, never `shell=True` / string-interpolated commands, even though the join operates on filenames this app generates itself (not raw user text) — guard the filenames, not the chunk content.

---

### `backend/app/config.py` (config)

**Analog:** none — pattern implied by CLAUDE.md's `TTS_BACKEND=mock` dev-degradation convention and RESEARCH.md's recommended structure listing `config.py` for "env vars (TTS_BACKEND, TTS_SERVICE_URL, chunk target length)". No concrete code sample exists yet in either upstream doc — planner should design this as a small typed settings module (e.g., `pydantic-settings` or plain `os.environ.get(...)` with defaults), consistent with the rest of the stack's Pydantic-heavy conventions.

---

### `backend/Containerfile.backend` / `backend/Containerfile.tts` (config, container build)

**Analog:** none — source: CLAUDE.md Installation section + RESEARCH.md "Installation (inside the TTS container...)" block and Podman rootless GPU passthrough example:
```bash
podman run --rm \
  --device /dev/kfd:/dev/kfd \
  --device /dev/dri:/dev/dri \
  --group-add keep-groups \
  -p 8001:8001 \
  localhost/qwen-ebook-tts:dev
```
`Containerfile.tts` should build FROM `rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1` (verified to exist on Docker Hub per RESEARCH.md) and must NOT `pip install torch` again on top of the base image. `Containerfile.backend` needs `apt-get install -y ffmpeg` and has no GPU/ROCm dependency at all.

## Shared Patterns

### GPU/CPU container isolation boundary
**Source:** RESEARCH.md Architecture Diagram + Pattern 1 (no codebase source — first phase)
**Apply to:** `backend/app/tts_client.py`, `backend/tts_service/server.py`, `backend/tts_service/model.py`, both Containerfiles
The backend (FastAPI) container must never `import torch` / `import qwen_tts` directly — all GPU work crosses the internal HTTP boundary into the isolated `tts_service` container. This is a hard DEPL-01 architectural constraint, not just a spike convenience.

### Exact dependency pinning for the TTS container
**Source:** RESEARCH.md Package Legitimacy Audit / Pitfall 3
**Apply to:** `backend/Containerfile.tts`, TTS container's own dependency file (isolated from the backend's `pyproject.toml`)
```bash
pip install "qwen-tts==0.1.1" --no-deps
pip install "transformers==4.57.3" "accelerate==1.12.0"  # exact pins required by qwen-tts 0.1.1
pip install soundfile einops onnxruntime librosa sox
pip install torchaudio --index-url https://download.pytorch.org/whl/rocm7.2
```
Never let the backend container's dependency file share a lockfile with these exact pins if it independently needs a newer `transformers`/`accelerate` for anything else.

### Subprocess safety (ffmpeg calls)
**Source:** RESEARCH.md Security Domain — Known Threat Patterns
**Apply to:** `backend/app/audio_join.py`
Always `subprocess.run([...])` with an argument list; never build a shell string from any variable content (filenames included).

### Upload safety
**Source:** RESEARCH.md Security Domain — V5/V12, Known Threat Patterns
**Apply to:** `backend/app/main.py`
Never trust `UploadFile.filename` for path construction (path traversal); generate server-side filenames; cap upload size at the ASGI/uvicorn level before full in-memory read.

## No Analog Found

All files in this phase have no codebase analog, since this is the project's first phase and no source code preceded it.

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `backend/app/main.py` | controller | request-response | Greenfield repo — no prior FastAPI app exists |
| `backend/app/chunking.py` | utility | transform | Greenfield repo — no prior chunking logic exists |
| `backend/app/tts_client.py` | service | request-response | Greenfield repo — no prior internal HTTP client exists; also no worked code example in RESEARCH.md (genuine design gap, flagged above) |
| `backend/app/audio_join.py` | utility | file-I/O | Greenfield repo — no prior ffmpeg wrapper exists |
| `backend/app/config.py` | config | — | Greenfield repo — no prior settings module exists |
| `backend/tts_service/server.py` | controller | request-response | Greenfield repo — no prior internal TTS server exists |
| `backend/tts_service/model.py` | model/service | request-response | Greenfield repo — no prior model-loading wrapper exists |
| `backend/Containerfile.backend` | config | — | Greenfield repo — no prior container build files exist |
| `backend/Containerfile.tts` | config | — | Greenfield repo — no prior container build files exist |
| `backend/pyproject.toml` | config | — | Greenfield repo — no prior dependency manifest exists |
| `backend/uploads/`, `backend/output/` | storage | file-I/O | Greenfield repo — no prior filesystem layout exists |
| `frontend/` | — | — | Empty placeholder per D-10; nothing to pattern-match |
| `backend/tests/test_chunking.py` | test | transform | Greenfield repo — no test framework/convention chosen yet; planner must pick one (e.g. `pytest`) |

## Conventions

Convention derivation was run via the shared deterministic module and returned:
```json
{ "mode": "derive", "skipped": true, "reason": "no-readable-files", "axes": [] }
```

| Axis | Dominant | Share | Entropy | Status |
|---|---|---|---|---|
| file-name casing | n/a | n/a | n/a | not derivable — no source files exist yet |
| identifier casing | n/a | n/a | n/a | not derivable — no source files exist yet |
| export style | n/a | n/a | n/a | not derivable — no source files exist yet |
| import style | n/a | n/a | n/a | not derivable — no source files exist yet |

Convention derivation skipped (no-readable-files) — this is the project's first phase, so there is no existing code to vote on conventions from. The Python-side convention default should follow standard `ruff`-formatted PEP 8 (snake_case files/identifiers, explicit imports) per CLAUDE.md's tooling section (`ruff` for lint/format), since CLAUDE.md is the only "authored" convention source available pre-implementation. Once Phase 1's code lands, Phase 2's pattern-mapper should re-run `verify conventions --derive` to establish real, code-derived axis data instead of this CLAUDE.md-inferred default.

**Contested hotspots (author's choice):** Not yet applicable — there is no code, so there are no contested hotspots. For future reference (once code exists), this project's prototype intentional-contested-split pattern to be aware of if/when a similar dual-module-system boundary ever arises here is the general principle illustrated by the GSD plugin's own `bin/lib/**` (CJS `module.exports`/`require`) vs `sdk/src/**` (ESM `export`/`import`) split: each half stays internally consistent per-directory, and is contested only when compared repo-wide — reviewers/planners should match the local directory's style rather than forcing one style project-wide. This project has no such split planned in Phase 1 (backend is pure Python; `frontend/` is empty), so this note is informational only, not an active hotspot.

## Metadata

**Analog search scope:** entire repository root (`.`), confirmed via `find . -maxdepth 3 -not -path './.git*' -not -path './.planning*'` — contains only `.claude/`, `CLAUDE.md`, `.git/`, `.planning/`
**Files scanned:** 0 source files (none exist)
**Pattern extraction date:** 2026-07-09
**Convention derivation tool result:** `{"skipped": true, "reason": "no-readable-files"}`
