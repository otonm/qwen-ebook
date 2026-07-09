# Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk) - Research

**Researched:** 2026-07-09
**Domain:** Self-hosted multi-voice TTS (Qwen3-TTS) on unofficially-supported AMD APU ROCm hardware, inside rootless Podman GPU-passthrough containers, fronted by a minimal FastAPI upload/chunk/synthesize/join pipeline.
**Confidence:** MEDIUM (stack/API layer is HIGH; ROCm-on-gfx1103 GPU layer is LOW-MEDIUM — this is the phase's explicit, acknowledged risk)

## Summary

This phase has two nearly-independent halves with very different confidence levels. The **application half** (FastAPI upload endpoint, stdlib-regex paragraph chunking, `qwen-tts` Python API, ffmpeg concat-demuxer join) is standard, well-documented, and verified directly against the actual `qwen-tts==0.1.1` package downloaded and inspected from PyPI during this research — HIGH confidence. The **GPU/ROCm half** is the real risk this phase exists to de-risk: the verification machine is a Radeon 780M (Phoenix/HawkPoint APU, `gfx1103`), an architecture that is **not** on ROCm's officially-supported list at any released version (confirmed against the current AMD compatibility matrix, which lists RDNA3 desktop targets gfx1100/gfx1101 but not gfx1103). Community evidence on gfx1103 specifically is thinner and more contradictory than the gfx1151-Strix-Halo precedent CLAUDE.md cites: `HSA_OVERRIDE_GFX_VERSION` spoofing, the standard workaround for unsupported-but-similar targets, has been reported to cause GPU page faults (override=11.0.0) or full system hard locks (override=11.0.2) specifically on gfx1103 in at least one documented case — a materially different (worse) outcome than the "override to 11.0.0 works fine" story for gfx1151. Separately, more recent (2026) community reports describe gfx1103 working **without** any override on sufficiently new ROCm/rocBLAS builds (Fedora 42+, ROCm 7.1+), which is a more promising path and matches this host's Fedora-Atomic (Bazzite) lineage — but this path itself has a known gap: stock Ubuntu-based rocBLAS (which is what the official `rocm/pytorch` container images ship) omits gfx1103 Tensile GEMM kernels entirely, requiring a manual kernel-file patch documented by the community. Both paths are real, sourced, but neither is proven for *this exact host*.

**Primary recommendation:** Build the TTS service as its own Podman container based on the official `rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1` image (verified to exist on Docker Hub) with `/dev/kfd` + `/dev/dri` passthrough and `--group-add keep-groups`, first attempting **no** `HSA_OVERRIDE_GFX_VERSION` override at all (2026 community reports suggest gfx1103 may now work natively on ROCm 7.1+ userspace). Treat GPU enablement as its own timeboxed spike task with an explicit, ordered fallback ladder (see Common Pitfalls) rather than a single assumed-working step — because the evidence here is genuinely contradictory, this is the one place in the phase where the plan must budget for iteration, not just implementation.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| .txt file upload (ING-01) | API/Backend (FastAPI container) | — | Multipart upload handled by FastAPI's `UploadFile`; no browser/client tier exists in this phase (D-05/D-06) |
| Paragraph/structural chunking (ING-03) | API/Backend (FastAPI container) | — | Pure Python stdlib logic (D-01/D-02); no external service needed |
| TTS synthesis (GEN-01) | TTS Inference Service (dedicated GPU-scoped Podman container) | — | DEPL-01 explicitly requires the TTS service isolated in its own GPU-scoped container, separate from the main app container — this is a locked architectural constraint, not a phase-1-only shortcut |
| Audio joining (GEN-04) | API/Backend (FastAPI container) | — | ffmpeg subprocess call from the backend container; no GPU needed for concat |
| GPU device passthrough / container isolation (DEPL-01) | Deployment/Infra (Podman pod + device cgroups) | — | Rootless Podman `--device`/`--group-add keep-groups`/SELinux device labels are host-level concerns, not application code |
| Storage of uploaded text + generated audio | Database/Storage (local filesystem) | — | No DB needed yet for a single-shot spike endpoint; files on disk are sufficient (persistence proper is Phase 3/PERS-01) |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Chunk plain .txt using Python stdlib/regex paragraph splitting (blank-line-delimited paragraphs) — no NLP library (NLTK/spaCy) dependency for this phase.
- **D-02:** Greedily merge consecutive paragraphs into chunks up to a target length of ~500-1000 characters.
- **D-03:** LLM-based interpretation of chunks into narrative/speech blocks is explicitly OUT of scope for Phase 1 (that's CAST-03 in Phase 2). Chunks go straight to TTS with one voice, no per-segment tagging.
- **D-04:** Use a single default Qwen3-TTS-1.7B-CustomVoice built-in speaker preset for every chunk — plain preset playback, no free-text instruct-steering. Exact preset name is Claude's discretion (see below).
- **D-05:** Phase 1 ships as a FastAPI upload endpoint (curl/Postman-driven), not a web page. Accepts a .txt file, runs chunk -> TTS -> join, returns the resulting audio file. This is the real app skeleton, not throwaway code.
- **D-06:** No frontend work in Phase 1 — deferred to Phase 2/3.
- **D-07:** Local dev machine's GPU is confirmed (via `lspci`/`glxinfo`) to be an AMD Radeon 780M integrated GPU — Phoenix/HawkPoint APU, RDNA3, `gfx1103`, shared system RAM. User confirmed this GPU is usable with ROCm despite not being on the officially-supported list — trust the user's direct knowledge over doc caution.
- **D-08:** Success criterion #3 ("real audio, verified from inside the real deployed container, not mocked") is satisfied on this LOCAL hardware: build the actual Podman container with real GPU device passthrough and verify real synthesized audio bytes come out of it, on the Radeon 780M.
- **D-09:** The RX 9070 XT production VM is not ready yet. Re-verification on that hardware is an explicit tracked follow-up, NOT part of this phase's scope or success criteria. The plan/verification must flag "re-verify on target VM once available" rather than silently treating Phase 1 as proving the target-hardware bet.
- **D-10:** Pre-split monorepo from day one — `backend/` + `frontend/` directories at repo root, `frontend/` stays empty until Phase 2.
- **D-11:** Python tooling: `uv` for dependency/venv management, `ruff` for lint/format, per CLAUDE.md, no deviation.

### Claude's Discretion
- Exact target chunk length within the ~500-1000 char range.
- Exact CustomVoice preset name chosen for the spike.
- Whether a single paragraph that alone exceeds the target chunk length gets further split (e.g., at a sentence boundary) or kept whole as an oversized chunk.
- Internal `backend/` folder structure (routes/services/etc.) beyond the top-level `backend/` + `frontend/` split.

### Deferred Ideas (OUT OF SCOPE)
- LLM-based interpretation of chunks into narrative/dialogue blocks — Phase 2 (CAST-03).
- Full deployment + verification on the actual target RX 9070 XT VM — cannot happen until that VM exists post-release; tracked as an explicit follow-up gate, not scoped into this phase's plan.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ING-01 | User can upload a plain text (.txt) file as the source for a new project | FastAPI `UploadFile` multipart pattern (HIGH confidence, standard) — see Code Examples |
| ING-03 | Long source texts are chunked on natural structural boundaries (chapter/paragraph) rather than arbitrary token counts | Stdlib regex paragraph-split + greedy merge to target length (D-01/D-02, HIGH confidence — pure Python, no new library) |
| GEN-01 | Each table row's audio segment is generated via self-hosted Qwen TTS running on the AMD GPU host | `qwen-tts` package `Qwen3TTSModel.generate_custom_voice()` API, verified directly from the downloaded 0.1.1 wheel; GPU enablement path is the phase's core risk (MEDIUM-LOW confidence, see Common Pitfalls) |
| GEN-04 | Generated segments are joined in table order into a single output audio file (MP3 or WAV) | ffmpeg concat demuxer (HIGH confidence, standard, matches CLAUDE.md) |
| DEPL-01 | App is deployed as Podman container(s) on a VM with an AMD GPU, with the TTS service isolated in its own GPU-scoped container | Rootless Podman `--device /dev/kfd --device /dev/dri --group-add keep-groups` pattern, verified against this actual host's device nodes/SELinux labels (see Environment Availability) |

## Project Constraints (from CLAUDE.md)

- Must use Podman, not Docker (project-wide constraint; DEPL-01 restates it for this phase).
- TTS model: Qwen3-TTS-1.7B-CustomVoice (not Base, not VoiceDesign as primary) via HF Transformers `qwen-tts` package, `attn_implementation="sdpa"` preferred over `flash-attn` (CUDA-only) on ROCm — **caveat found this session:** the `qwen-tts` package's own README example uses `attn_implementation="flash_attention_2"` by default; CLAUDE.md's `sdpa` guidance is the correct ROCm-compatible override to pass instead, not the package's own default.
- FastAPI backend, `uv` for Python deps, `ruff` for lint/format.
- ffmpeg concat demuxer for joining (not `pydub`, not the concat filter).
- `TTS_BACKEND=mock` env-flag pattern for GPU-less dev machines — not directly needed for Phase 1 itself (this phase's entire point is real GPU verification), but worth wiring the flag in now since D-05 says this is the real app skeleton, not throwaway code, and Phase 2/3 work will run on non-GPU dev machines.
- Pin exact versions for `qwen-tts` and its ROCm/PyTorch stack — confirmed critical this session (see Package Legitimacy Audit: `qwen-tts==0.1.1` hard-pins `transformers==4.57.3` and `accelerate==1.12.0`, both far behind current PyPI latest).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `qwen-tts` | `0.1.1` [VERIFIED: pip index / downloaded wheel, 2026-02-06] | Qwen3-TTS Python inference wrapper | Official Alibaba Qwen team package; only maintained way to run `Qwen3TTSModel.from_pretrained(...)` + `generate_custom_voice(...)` outside vLLM |
| `torch` | `2.13.0+rocm7.2` (or base image's bundled `2.9.1`) [VERIFIED: download.pytorch.org/whl/rocm7.2 index listing] | GPU tensor runtime | Only way to get ROCm-accelerated PyTorch; stable (non-nightly) `rocm7.2` wheels for `cp312` confirmed present on the official PyTorch wheel index |
| `transformers` | `==4.57.3` (EXACT PIN, required by `qwen-tts` 0.1.1) [VERIFIED: qwen-tts wheel METADATA `Requires-Dist`] | Model loading (`AutoModel`, `AutoConfig`, `AutoProcessor`) | `qwen-tts` registers `Qwen3TTSConfig`/`Qwen3TTSForConditionalGeneration` via HF Auto* classes; the pin is exact, not a floor — installing "latest" `transformers` (currently `5.13.0`) will very likely break this |
| `accelerate` | `==1.12.0` (EXACT PIN, required by `qwen-tts` 0.1.1) [VERIFIED: qwen-tts wheel METADATA] | Device placement / `device_map` support | Same exact-pin caveat as transformers — current PyPI latest is `1.14.0` |
| FastAPI | `0.139.0` [VERIFIED: pip index versions] | Upload endpoint + orchestration | Matches CLAUDE.md; current as of this research date |
| `python-multipart` | `0.0.32` [VERIFIED: pip index versions] | Required by FastAPI for `UploadFile`/form-data parsing | FastAPI raises a runtime error on file-upload endpoints without it installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `soundfile` | pulled in by `qwen-tts` [VERIFIED: Requires-Dist, unpinned] | Write `generate_custom_voice()`'s `np.ndarray` output to a `.wav` file | Every synthesis call — `qwen-tts`'s own README example uses exactly this (`sf.write(...)`) |
| `torchaudio` | pulled in by `qwen-tts` [VERIFIED: Requires-Dist, unpinned] | Audio I/O helper used internally by the package | Installed automatically; **must** be installed from the same `rocm7.2` wheel index as `torch`, or plain `pip install torchaudio` will silently fetch a CPU/mismatched build (see Common Pitfalls) |
| `librosa`, `onnxruntime`, `einops`, `sox` (PyPI wrapper), `gradio` | pulled in by `qwen-tts` [VERIFIED: Requires-Dist, unpinned] | Internal audio-processing / demo-UI dependencies of the package | Not used directly by this app's code; installed transitively. `gradio` in particular is dead weight for a backend-only spike but is a hard dependency of `qwen-tts` 0.1.1 — cannot be avoided without patching the package |
| `uvicorn` | `0.51.0` [VERIFIED: pip index versions] | ASGI server to run the FastAPI app | Standard FastAPI companion; not in CLAUDE.md's explicit table but required to actually serve the app |
| `ffmpeg` (system binary) | Debian/Ubuntu 6.x+, confirmed `8.1.2` on this dev host [VERIFIED: `ffmpeg -version` on this machine] | Concat-demuxer join of per-chunk WAV/MP3 into one file | Install via `apt-get install -y ffmpeg` in the backend container image per CLAUDE.md |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `rocm/pytorch` prebuilt container base | Plain `ubuntu:24.04` + manual `pip install torch --index-url .../rocm7.2` | The prebuilt image already has a ROCm userspace matching its bundled torch build tested together; building manually risks a userspace/wheel version mismatch, a documented common ROCm failure mode. Prefer the prebuilt image for this spike. |
| No `HSA_OVERRIDE_GFX_VERSION` (native gfx1103 attempt first) | `HSA_OVERRIDE_GFX_VERSION=11.0.0` (spoof as gfx1100) | Community reports disagree on gfx1103 specifically: one report says override=11.0.0 causes page faults on gfx1103 (vs. working fine on gfx1151/Strix Halo); more recent 2026 reports say sufficiently new ROCm/rocBLAS now works natively without any override. Try native first; only reach for the override, cautiously, as a fallback (see Common Pitfalls). |

**Installation (inside the TTS container, after choosing a `rocm/pytorch` base):**
```bash
# Base image already includes a matching torch+ROCm userspace; do not `pip install torch` again on top of it.
pip install "qwen-tts==0.1.1" --no-deps
pip install "transformers==4.57.3" "accelerate==1.12.0"  # exact pins required by qwen-tts 0.1.1
pip install soundfile einops onnxruntime librosa sox
# torchaudio must come from the SAME rocm wheel index as the base image's torch build:
pip install torchaudio --index-url https://download.pytorch.org/whl/rocm7.2
```

**Version verification performed this session:**
- `pip index versions qwen-tts` -> `0.1.1` (latest), released 2026-02-06 [VERIFIED]
- `pip index versions torch` -> `2.13.0` on default PyPI (CPU/CUDA build; **not** the ROCm build) [VERIFIED]
- `curl https://download.pytorch.org/whl/rocm7.2/torch/` -> confirmed `torch-2.13.0+rocm7.2-cp312-*.whl` exists as a stable (non-nightly) release [VERIFIED]
- `pip index versions fastapi` -> `0.139.0` (matches CLAUDE.md) [VERIFIED]
- Downloaded and unzipped the actual `qwen_tts-0.1.1-py3-none-any.whl`; confirmed `Qwen3TTSModel.from_pretrained`, `.generate_custom_voice`, `.get_supported_speakers` exist with the documented signatures, and that `Requires-Dist` hard-pins `transformers==4.57.3` / `accelerate==1.12.0` [VERIFIED: direct package inspection]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|--------------|-----------|-------------|
| `qwen-tts` | PyPI | ~5 mo (first release ~Jan 2026, latest 2026-02-06) | not checked (new/niche) | github.com/QwenLM/Qwen3-TTS | OK | Approved — official Alibaba Qwen team package, confirmed by direct wheel inspection |
| `torch` | PyPI (+ rocm7.2 wheel index) | 10+ yrs | very high | github.com/pytorch/pytorch | OK | Approved |
| `transformers` | PyPI | 7+ yrs | very high | github.com/huggingface/transformers | OK | Approved (pin to `4.57.3` exactly per qwen-tts requirement) |
| `accelerate` | PyPI | 5+ yrs | very high | github.com/huggingface/accelerate | OK | Approved (pin to `1.12.0` exactly per qwen-tts requirement) |
| `fastapi` | PyPI | 6+ yrs | very high | github.com/fastapi/fastapi | OK | Approved |
| `python-multipart` | PyPI | 8+ yrs | very high | github.com/Kludex/python-multipart | OK (flagged `HALLUCINATION_PATTERN`/info: "name starts with python- , classic LLM naming pattern, but package is established") | Approved — info-level flag only, package is long-established and is FastAPI's own documented dependency for file uploads |
| `soundfile` | PyPI | 8+ yrs | very high | github.com/bastibe/python-soundfile | OK | Approved |
| `librosa` | PyPI | 10+ yrs | very high | github.com/librosa/librosa | OK | Approved |
| `uvicorn` | PyPI | 6+ yrs | very high | github.com/Kludex/uvicorn | OK | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none (one `python-multipart` info-level naming-pattern note, not a suspicion flag — kept as-is)

slopcheck 0.6.1 was installed and run successfully this session (`pip install slopcheck`, then `slopcheck scan --pkg pypi <name> --json` per package). All checked packages returned `OK`. Package names above were cross-checked against official sources this session (direct wheel download for `qwen-tts`; CLAUDE.md's pre-existing research + PyPI registry confirmation for the rest) — tagged `[VERIFIED]` in the tables above rather than `[ASSUMED]` per the provenance rule, since existence was confirmed via direct package/API inspection, not just registry presence.

## Architecture Patterns

### System Architecture Diagram

```
   curl / Postman (no browser client this phase)
        │  POST /projects  (multipart .txt upload)
        ▼
 ┌─────────────────────────────┐
 │  Backend container (no GPU) │
 │  FastAPI app                │
 │   1. Save uploaded .txt     │
 │   2. Chunk into paragraphs  │──── stdlib re, no network call
 │      (target 500-1000 char) │
 │   3. For each chunk:        │
 │      POST /synthesize ──────┼────────────┐
 │      (HTTP, same Podman pod)│            │
 │   4. Collect chunk WAVs     │            ▼
 │   5. ffmpeg concat demuxer  │   ┌───────────────────────────────┐
 │      -> single output file  │   │ TTS container (GPU-scoped)   │
 │   6. Return audio file      │   │ /dev/kfd + /dev/dri passed in │
 └─────────────────────────────┘   │ qwen-tts + torch+ROCm         │
        ▲                          │ Qwen3-TTS-1.7B-CustomVoice     │
        │  audio bytes             │ loaded once at container start │
        └──────────────────────────│ generate_custom_voice(chunk)   │
                                    │ -> wav bytes back over HTTP    │
                                    └───────────────────────────────┘
```

A reader can trace: upload -> chunk -> per-chunk HTTP call into the GPU container -> per-chunk WAV -> ffmpeg join -> download. The GPU-scoped container is a hard boundary — it is the *only* process in the pod with `/dev/kfd`/`/dev/dri` passed in, matching DEPL-01's "isolated GPU-scoped container" requirement literally, not just a same-container convenience separation.

### Recommended Project Structure
```
backend/
├── app/
│   ├── main.py              # FastAPI app, upload endpoint
│   ├── chunking.py           # paragraph-split + greedy merge (D-01/D-02)
│   ├── tts_client.py         # HTTP client calling the TTS container's /synthesize
│   ├── audio_join.py         # ffmpeg concat-demuxer subprocess wrapper
│   └── config.py             # env vars (TTS_BACKEND, TTS_SERVICE_URL, chunk target length)
├── tts_service/
│   ├── server.py             # tiny FastAPI/Flask app inside the GPU container
│   └── model.py              # Qwen3TTSModel.from_pretrained() loaded once at startup
├── Containerfile.backend     # no GPU, ffmpeg installed
├── Containerfile.tts         # rocm/pytorch base, /dev/kfd + /dev/dri
├── pyproject.toml            # uv-managed
└── uploads/ , output/         # local filesystem storage for this phase
frontend/                      # empty, per D-10/D-06
```

### Pattern 1: Isolated GPU-scoped TTS container behind an internal HTTP boundary
**What:** The TTS model lives in its own container/process, loaded once at startup, exposing a minimal internal `/synthesize` endpoint (text + speaker in, WAV bytes out). The main backend never imports `torch`/`qwen-tts` directly.
**When to use:** Any time a GPU-dependent component must be isolated from a CPU-only orchestrator container — this is exactly DEPL-01's requirement, and it is also the shape GEN-01 in Phase 3 will need anyway (queueing generation requests against one persistent model-loaded process, not re-loading the 1.7B model per request).
**Example:**
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
# Source: qwen-tts 0.1.1 wheel METADATA (verified directly from downloaded package this session)
```

### Pattern 2: Greedy paragraph-merge chunking (D-01/D-02)
**What:** Split on blank-line-delimited paragraphs (`re.split(r"\n\s*\n", text)`), then greedily accumulate consecutive paragraphs into a chunk buffer until adding the next paragraph would exceed the target length, at which point the buffer is flushed as one chunk.
**When to use:** Exactly this phase's ING-03 requirement — natural structural boundaries, not arbitrary token counts.
**Example:**
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
This is plain stdlib logic per D-01 — no external library needed, HIGH confidence.

### Anti-Patterns to Avoid
- **Loading the 1.7B model per HTTP request:** Model load (HF weights download/deserialize) takes real time and VRAM churn; the TTS container must load the model once at process startup and hold it resident.
- **Installing `torch`/`torchaudio` from the default PyPI index inside the ROCm container:** silently installs a CPU or CUDA build that will not use the GPU (no error, just silent fallback) — always pin the `--index-url .../whl/rocm7.2` explicitly, or better, don't reinstall `torch` at all if starting from an `rocm/pytorch` base image that already bundles it.
- **Treating GPU enablement as a solved sub-step of the plan:** given the contradictory community evidence for gfx1103 specifically (see Common Pitfalls), the plan must budget explicit iteration/troubleshooting time here, not a single "install and go" task.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Audio format conversion / concatenation | Custom WAV byte-splicing or `pydub` | `ffmpeg` concat demuxer via `subprocess` | Concat demuxer handles same-codec joins correctly and fast; CLAUDE.md already rules out `pydub` (unmaintained since 2021) |
| Multipart file upload parsing | Manual `Content-Type` header parsing | FastAPI `UploadFile` (backed by `python-multipart`) | FastAPI's built-in handling is battle-tested; hand-parsing multipart bodies is a well-known source of subtle bugs (boundary edge cases, large-file memory blowup) |
| Speaker/language validation against the model | Custom string-matching against a hardcoded speaker list | `model.get_supported_speakers()` / `model.get_supported_languages()` (case-insensitive validation built into `qwen-tts`) | The package already validates and raises `ValueError` on unsupported speakers — duplicating this logic risks drift if the model's speaker list changes across versions |

**Key insight:** Everything in this phase that touches "known problem, well-trodden library" (uploads, concatenation, speaker validation) already has a correct, maintained solution baked into the chosen stack — the actual hand-rolling risk in this phase is entirely on the ROCm/GPU-enablement side, where there is no library to reach for and the plan must instead budget investigation time.

## Common Pitfalls

### Pitfall 1: gfx1103 is not on ROCm's officially-supported list — evidence on the override workaround is contradictory
**What goes wrong:** The standard "unsupported-but-similar-architecture" fix, `HSA_OVERRIDE_GFX_VERSION`, is reported to work cleanly for the *adjacent* Strix Halo APU (`gfx1151` -> override to `11.0.0`, per the tinycomputers.io blog CLAUDE.md cites) but has at least one documented report of causing GPU page faults (override=`11.0.0`) or a full system hard lock (override=`11.0.2`) specifically on `gfx1103`.
**Why it happens:** `gfx1103` (Phoenix/HawkPoint, RDNA3) and `gfx1151` (Strix Halo, RDNA3.5) are different enough at the ISA level that an override that works for one does not necessarily work for the other, even though both are "RDNA3-family APU, not officially supported."
**How to avoid:** Try **no override first** — more recent (2026) community reports describe `gfx1103` working nativel on sufficiently new ROCm userspace (Fedora 42+/ROCm 7.1+ rocBLAS, `ollama-rocm` 0.13.0-2 built with hipblas 7.1.0) without any `HSA_OVERRIDE_GFX_VERSION` at all. Only reach for an override as a fallback, and test conservatively (verify with a lightweight `rocminfo`/tiny-tensor-op smoke test *before* loading the full 1.7B model, so a bad override value doesn't hang the process mid-model-load).
**Warning signs:** GPU page faults in `dmesg`, kernel driver resets, or (worst case) the whole desktop session locking up. If any override value causes an immediate hang, kill it and try the next path rather than experimenting further with `HSA_OVERRIDE_GFX_VERSION` values on this specific host, since a real hard-lock has been reported for this architecture.

### Pitfall 2: Ubuntu-based rocBLAS (the base of official `rocm/pytorch` images) is documented to omit gfx1103 Tensile GEMM kernels
**What goes wrong:** Even after solving device passthrough and getting `rocminfo` to detect the GPU, matmul-heavy operations may fail or fall back silently because the prebuilt Tensile kernel database bundled with Ubuntu's rocBLAS package doesn't include gfx1103 binaries — a gap the community has worked around by extracting Fedora's prebuilt gfx1103 Tensile kernels into the container's rocBLAS installation.
**Why it happens:** Tensile kernels are pre-compiled per-architecture and per-distro-package; AMD's official Ubuntu builds target the officially-supported architecture list, which excludes gfx1103.
**How to avoid:** After passthrough works, run a minimal PyTorch matmul (`torch.randn(...).to("cuda") @ torch.randn(...).to("cuda")`) as an isolated smoke test before attempting a full TTS forward pass. If it fails specifically with a rocBLAS/Tensile "no kernel found" style error (distinct from a device-not-found error), that confirms this specific gap, and the workaround is extracting a Fedora rocBLAS package's gfx1103 kernel files into the container's rocBLAS path — a real but non-trivial extra build step to budget for.
**Warning signs:** `rocminfo`/`rocm-smi` succeed (device detected) but any real tensor op on GPU hangs, errors with a kernel-not-found rocBLAS message, or produces garbage output.

### Pitfall 3: `qwen-tts==0.1.1` hard-pins `transformers==4.57.3` and `accelerate==1.12.0` — exact pins, not floors
**What goes wrong:** A naive `pip install qwen-tts transformers accelerate` (or any dependency-resolution order that lets a newer `transformers`/`accelerate` get installed first) will conflict with `qwen-tts`'s exact `Requires-Dist` pins, or worse, silently install the pinned old versions and break unrelated tooling expectations if the environment also needs current `transformers` for something else.
**Why it happens:** `qwen-tts` is a fast-moving, ~5-month-old package (first release ~Jan 2026) that pins exact versions of its two heaviest dependencies rather than floor/ceiling ranges — verified directly from the downloaded wheel's `METADATA` this session. Current PyPI latest for these packages (`transformers==5.13.0`, `accelerate==1.14.0` as of this research date) are multiple major versions ahead.
**How to avoid:** Give the TTS container its own isolated `uv`/venv environment with `transformers==4.57.3` and `accelerate==1.12.0` pinned explicitly in the container's dependency file — never let a shared/repo-wide dependency file for the backend (non-GPU) container drag in a different `transformers` version that could conflict if both containers ever share a base image or lockfile.
**Warning signs:** `ImportError`/`AttributeError` inside `qwen_tts`'s internal `AutoModel.register(...)` calls, or HF Transformers API-shape errors (e.g., missing/renamed methods) at model load time.

### Pitfall 4: `torchaudio` and `torch` must come from the same ROCm wheel index
**What goes wrong:** Installing `torchaudio` via a plain `pip install torchaudio` (default PyPI index) inside a container whose `torch` came from the `rocm7.2` wheel index can pull in a CPU-only or version-mismatched `torchaudio` build, causing subtle failures or CPU fallback with no clear error.
**Why it happens:** `torch` and `torchaudio` are versioned and built together per-backend (cpu/cuda/rocm); PyPI's default index serves the CPU/CUDA builds under the same package name.
**How to avoid:** Always pass the same `--index-url https://download.pytorch.org/whl/rocm7.2` when installing `torchaudio`, or prefer starting from the `rocm/pytorch` base image (which typically bundles a matching `torchaudio` already, reducing what needs a fresh pip install).
**Warning signs:** No hard error — just GPU underutilization or a suspiciously CPU-bound `torchaudio` decode step; verify with `torchaudio.get_audio_backend()`/checking `import torch; torch.cuda.is_available()` (ROCm PyTorch reports this as `True` for ROCm devices) inside the running container.

### Pitfall 5: SELinux is Enforcing on this host — verify device labels, don't reflexively disable labeling
**What goes wrong:** Podman GPU passthrough guides often suggest `--security-opt label=disable` as a blanket fix for SELinux-related device-access denials, discarding SELinux protection unnecessarily.
**Why it happens:** Generic guides don't know the specific device labels on the target host.
**How to avoid:** This host's device nodes already carry the correct, container-aware SELinux types confirmed via `ls -Z`: `/dev/kfd` is `hsa_device_t` and `/dev/dri/renderD128` is `dri_device_t` — both are types the standard `container-selinux` policy already permits for `--device` passthrough (unlike volume mounts, `--device` doesn't require relabeling). Try passthrough with SELinux left Enforcing first; only reach for `label=disable` if `ausearch -m avc -ts recent` shows a genuine denial against these specific device types.
**Warning signs:** `Permission denied` opening `/dev/kfd`/`/dev/dri/renderD128` from inside the container despite `--device` being passed and host-side permissions (`crw-rw-rw-`/`crw-rw----` + `--group-add keep-groups`) looking correct — check `ausearch`/`journalctl -t setroubleshoot` before disabling labeling.

## Code Examples

### FastAPI upload endpoint (ING-01)
```python
# Source: FastAPI official docs pattern (https://fastapi.tiangolo.com/tutorial/request-files/), HIGH confidence — standard, well-established API
from fastapi import FastAPI, UploadFile, File

app = FastAPI()

@app.post("/projects")
async def create_project(file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8")
    # -> chunk_paragraphs(text) -> per-chunk TTS calls -> ffmpeg join -> return audio
    ...
```

### ffmpeg concat demuxer join (GEN-04)
```bash
# Source: standard ffmpeg concat-demuxer usage, matches CLAUDE.md guidance — HIGH confidence
# list.txt contains lines like: file 'chunk_000.wav'
ffmpeg -f concat -safe 0 -i list.txt -c copy output.wav
# For MP3 output where inputs are WAV (re-encode needed, not a stream copy):
ffmpeg -f concat -safe 0 -i list.txt -c:a libmp3lame output.mp3
```

### Podman rootless GPU passthrough (DEPL-01)
```bash
# Source: verified against this actual dev host's device nodes/SELinux labels this session
podman run --rm \
  --device /dev/kfd:/dev/kfd \
  --device /dev/dri:/dev/dri \
  --group-add keep-groups \
  -p 8001:8001 \
  localhost/qwen-ebook-tts:dev
# This host's /dev/kfd is world-rw (crw-rw-rw-) and /dev/dri/renderD128 is world-rw;
# card1 (the display device, not needed for compute) is root:video crw-rw----.
# --group-add keep-groups is still the portable/correct flag to include even though
# this particular host's render node permissions are already permissive.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `HSA_OVERRIDE_GFX_VERSION` spoofing as the default/only path for unsupported APU targets | Native support landing in sufficiently recent ROCm/rocBLAS builds (e.g., Fedora 42+, ROCm 7.1+) for some previously-unsupported RDNA3 APU targets including reports for gfx1103 | Ongoing through 2026, not a single clean cutover — evidence is mixed and host-dependent | The override-based workaround CLAUDE.md documents for gfx1151/Strix Halo is one valid path but should not be assumed as the *only* or even *first* path to try for gfx1103 specifically |

**Deprecated/outdated:** None specific to this phase's stack — `qwen-tts` is too new (Jan 2026) to have a deprecated predecessor within this project's context; the "deprecated" pattern to watch is treating `HSA_OVERRIDE_GFX_VERSION` as gospel across all unsupported APU targets rather than architecture-specific evidence.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `HSA_OVERRIDE_GFX_VERSION=11.0.0` causes GPU page faults on gfx1103 specifically (vs. working on gfx1151) | Common Pitfalls, Summary | If this specific single-source claim is wrong or outdated, the plan may over-index on avoiding the override path when it would actually work fine; mitigated by recommending "try native first, override only as tested fallback" either way |
| A2 | Fedora 42+/ROCm 7.1+ userspace provides native gfx1103 support without any override | Summary, Common Pitfalls | If this is overstated (e.g., only applies to Ollama's specific patched build, not stock ROCm/rocBLAS), the "try native first" recommendation may waste spike time before falling back to the override path — the plan should timebox the native attempt |
| A3 | Official `rocm/pytorch` Ubuntu-based images omit gfx1103 Tensile GEMM kernels, requiring a manual kernel-file patch | Common Pitfalls #2 | If newer `rocm/pytorch` tags (e.g., the confirmed `rocm7.2.4` tag) have since folded in gfx1103 Tensile kernels, this adds unneeded complexity to the plan; the smoke-test step recommended in Pitfall 2 is designed to detect whether this gap is actually present before building the workaround |
| A4 | `qwen-tts`'s README default `attn_implementation="flash_attention_2"` is unsafe/unavailable on ROCm and must be overridden to `"sdpa"` | Project Constraints, Pattern 1 | This is CLAUDE.md's existing documented decision (carried forward, not newly researched this session) — if a ROCm-compatible flash-attention fork is in fact usable, sticking to `sdpa` merely leaves some performance on the table, not a correctness risk |

## Open Questions

1. **Does this specific Bazzite/Fedora-Atomic host's kernel-bundled amdgpu/KFD driver version support gfx1103 well enough for compute (not just display), independent of what ROCm userspace lands inside the container?**
   - What we know: `/dev/kfd` and `/dev/dri/renderD128` already exist on this host with no ROCm packages installed — confirming the kernel driver is active and KFD is exposed. Kernel is `7.0.9-ogc3.2.fc44` (Bazzite's custom kernel, Fedora 44-based).
   - What's unclear: Whether this exact kernel build includes the amdgpu KFD compute-queue support needed for gfx1103, as distinct from just display support (a card can render a desktop over `/dev/dri` while still lacking working KFD compute queues).
   - Recommendation: The very first plan task on the GPU side should be a minimal `rocminfo`-equivalent smoke test (from inside a ROCm-userspace container with passthrough) that confirms the GPU is detected as a *compute* agent, before attempting to load any TTS model weights.

2. **Is the internal TTS-container HTTP boundary (backend container -> TTS container over a shared Podman pod network) the right shape for Phase 1, or is a single combined container acceptable given this is a "spike"?**
   - What we know: DEPL-01 and CLAUDE.md both describe the TTS service as isolated in its own GPU-scoped container as a permanent architectural requirement, not a Phase-3-only refinement.
   - What's unclear: Whether the discuss-phase session intended this two-container split to be built *in Phase 1* or whether a single-container spike (GPU passthrough directly on the FastAPI container) would satisfy D-08's "real deployed container" bar for this phase, with the isolation split deferred.
   - Recommendation: Build the two-container split now — CONTEXT.md's D-05 explicitly frames Phase 1 as "the real app skeleton rather than throwaway code," and DEPL-01 is one of this phase's five in-scope requirements, so the isolation property should be verified now rather than assumed satisfiable later.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| AMD GPU (Radeon 780M, gfx1103) | GEN-01 (GPU-scoped TTS) | Yes (confirmed via `lspci`: `HawkPoint1 [1002:1900]`) | RDNA3, gfx1103 | None — this is the phase's hardware target per D-07/D-08 |
| `/dev/kfd`, `/dev/dri/renderD128` | Podman GPU passthrough (DEPL-01) | Yes | kfd: `hsa_device_t`; renderD128: `dri_device_t` (both world-rw) | None needed |
| ROCm userspace (`rocminfo`/`rocm-smi`) on host | Optional — only needed if testing outside a container | No (not installed; confirmed via `which`) | — | Not required if ROCm userspace lives entirely inside the `rocm/pytorch`-based TTS container, which is the recommended path — avoids needing to layer packages onto this host's immutable (rpm-ostree/Bazzite) base system at all |
| Podman | DEPL-01 | Yes | `5.8.4` | None |
| ffmpeg | GEN-04 | Yes (host); must also be installed inside the backend container image via `apt-get install -y ffmpeg` | `8.1.2` (host) | None |
| Python | Backend/tooling | Yes | `3.14.6` (host); containers should pin `3.12` per CLAUDE.md/qwen-tts's tested range | Containers control their own Python version regardless of host version |
| `uv` | D-11 tooling | Not confirmed installed on this host in this session (not checked) | — | Install via project setup step if missing; not a blocker, standard single-binary install |
| SELinux | DEPL-01 (container device access) | Enforcing | — | Device types already correctly labeled for container passthrough (see Pitfall 5); no fallback needed unless a genuine AVC denial appears |

**Missing dependencies with no fallback:**
- None identified — the one open risk (gfx1103 compute-queue support) is a *capability* uncertainty, not a missing tool/dependency.

**Missing dependencies with fallback:**
- Host ROCm userspace (rocminfo/rocm-smi) — not installed, but the recommended architecture (ROCm entirely inside the TTS container) avoids needing it on this immutable-base host at all.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|-------------------|
| V2 Authentication | No | Explicitly out of scope project-wide (Tailscale network membership is the access boundary per PROJECT.md/DEPL-02); no auth layer to build in this phase |
| V3 Session Management | No | No sessions/cookies in a curl-driven upload endpoint |
| V4 Access Control | No | Single-user tool, no multi-tenant boundary to enforce |
| V5 Input Validation | Yes | Validate uploaded file is actually text (reject/limit non-UTF-8 or absurdly large uploads) before chunking; validate `speaker`/`language` values, though `qwen-tts` itself already validates these against `get_supported_speakers()`/`get_supported_languages()` and raises `ValueError` |
| V6 Cryptography | No | No secrets/crypto operations in this phase's scope |
| V12 File and Resources | Yes | Uploaded `.txt` files should be size-capped (e.g., reject multi-hundred-MB uploads) and written to a fixed, non-user-controlled upload directory with a generated filename — never trust the client-supplied filename for path construction |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Path traversal via client-supplied upload filename (`../../etc/passwd`-style) | Tampering | Never use `UploadFile.filename` directly to build a server-side path; generate a server-side filename/UUID and store the original name only as metadata |
| Unbounded upload size causing memory/disk exhaustion | Denial of Service | Enforce a max content-length at the FastAPI/ASGI server level (uvicorn/reverse-proxy config) before the file is fully read into memory |
| Command injection via chunk text passed into a shell-invoked `ffmpeg`/subprocess call | Tampering | Always call `subprocess.run([...])` with an argument list (never `shell=True` / string-interpolated commands); this app's ffmpeg join operates on filenames it generates itself, not raw user text, so the main exposure to guard is filenames, not chunk content |

## Sources

### Primary (HIGH confidence)
- Downloaded and directly inspected `qwen_tts-0.1.1-py3-none-any.whl` (PyPI) — confirmed API signatures, exact dependency pins, speaker list
- `pip index versions` for `qwen-tts`, `torch`, `fastapi`, `python-multipart`, `transformers`, `accelerate`, `uvicorn`, `librosa`, `soundfile`, `sox`, `onnxruntime` — run directly this session
- `curl https://download.pytorch.org/whl/rocm7.2/torch/` and `.../rocm6.4/torch/` — confirmed actual available ROCm wheel filenames/versions
- Docker Hub API query for `rocm/pytorch` tags — confirmed `rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1` exists
- `lspci`, `ls -Z`, `getenforce`, `podman --version`, `ffmpeg -version`, `cat /etc/os-release` run directly on this dev host
- [ROCm compatibility matrix (AMD official docs)](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) — confirmed gfx1103 absent from all listed officially-supported architectures
- [FastAPI request files docs](https://fastapi.tiangolo.com/tutorial/request-files/) — `UploadFile` pattern
- `slopcheck 0.6.1` run against all recommended packages this session — all `OK`

### Secondary (MEDIUM confidence)
- [MIOpen gfx1103 precompiled convolution databases issue](https://github.com/ROCm/rocm-libraries/issues/6335) — hipBLASLt merged for gfx1103, MIOpen convolution kernel gap documented
- [johnsonfarmsus/ollama-rocm-gfx1103-ubuntu](https://github.com/johnsonfarmsus/ollama-rocm-gfx1103-ubuntu) — documents Ubuntu rocBLAS omitting gfx1103 Tensile kernels and the Fedora-kernel-extraction workaround
- [tinycomputers.io Qwen3-TTS on AMD Strix Halo](https://tinycomputers.io/posts/qwen-tts-on-amd-strix-halo.html) — concrete `sdpa`/bf16/env-var setup for the analogous (but architecturally distinct) gfx1151 target
- Bazzite documentation and GitHub issues (`ublue-os/bazzite` #1044, #1488) on ROCm-in-container status for this OS family

### Tertiary (LOW confidence)
- WebSearch summaries describing gfx1103 "now working natively" on Fedora 42+/ROCm 7.1+/`ollama-rocm` 0.13.0-2 — plausible, consistent with the direction of ROCm's gfx1103 support work, but not independently confirmed against an official ROCm release note; flagged in Assumptions Log (A2)
- WebSearch summary of `HSA_OVERRIDE_GFX_VERSION=11.0.2` causing a full system hard lock on gfx1103 — single-source, not independently reproduced; flagged in Assumptions Log (A1)

## Metadata

**Confidence breakdown:**
- Standard stack (application layer): HIGH — verified directly against the downloaded `qwen-tts` package, live PyPI/PyTorch wheel indices, and this actual host
- Architecture: HIGH for the two-container isolation pattern (directly required by DEPL-01/CLAUDE.md); MEDIUM for exact internal HTTP contract shape (Claude's discretion within the locked constraint)
- GPU/ROCm enablement: LOW-MEDIUM — this is the phase's acknowledged, explicit risk; evidence found this session is real but contradictory across sources, and none of it is host-specific (no source tested this exact Bazzite kernel + this exact GPU)
- Pitfalls: MEDIUM-HIGH — sourced from multiple independent community reports plus direct host inspection, but gfx1103-specific evidence remains thinner than the gfx1151 precedent

**Research date:** 2026-07-09
**Valid until:** 14 days (ROCm/gfx1103 community-support landscape is moving quickly; re-check before acting on any GPU-specific claim if this research is more than ~2 weeks old)
