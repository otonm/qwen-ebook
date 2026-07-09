# Walking Skeleton — Qwen Ebook Narrator

**Phase:** 1
**Generated:** 2026-07-09

## Capability Proven End-to-End

> One sentence: the smallest user-visible capability that exercises the full stack.

A user can `curl` a `.txt` file to the FastAPI backend and receive back a single downloadable audio file whose speech was produced, chunk-by-chunk, by the self-hosted Qwen3-TTS model running under ROCm inside its own GPU-scoped Podman container on the local Radeon 780M (`gfx1103`).

Because Phase 1 has no frontend (CONTEXT.md D-05/D-06 defer all UI to Phase 2/3), the "one real UI interaction" of a normal Walking Skeleton is substituted with **one real HTTP-client (`curl`/Postman) interaction wired to the real upload → chunk → TTS → join → download path**.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Backend framework | FastAPI 0.139.0 + uvicorn 0.51.0 (Python 3.12) | CLAUDE.md stack; D-05 says this is the real app skeleton, not throwaway code. Async, Pydantic-native, becomes the Phase 2/3 backend. |
| Client (this phase) | `curl` / Postman — no browser | D-06 defers frontend to Phase 2/3; `frontend/` stays an empty placeholder (D-10). |
| TTS engine | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` via `qwen-tts==0.1.1` | CLAUDE.md primary model; D-04 single preset, no instruct-steering this phase. |
| GPU runtime | PyTorch ROCm (`rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1` base), `attn_implementation="sdpa"` | RESEARCH.md verified image + ROCm-safe attention (NOT the package README's flash_attention_2 default). Local target `gfx1103`; production target `gfx1201` (RX 9070 XT) re-verified post-release per D-09. |
| Container split | Two containers: CPU `backend` + GPU-scoped `tts_service` in one Podman pod | DEPL-01 requires the TTS service isolated in its own GPU-scoped container — a permanent architectural constraint, not a spike shortcut (RESEARCH.md Open Question 2 resolved: build the split now). |
| GPU passthrough | Rootless Podman `--device /dev/kfd --device /dev/dri --group-add keep-groups`, SELinux left Enforcing | RESEARCH.md verified this host's device labels (`hsa_device_t`, `dri_device_t`) are already container-passthrough-safe. |
| Storage | Local filesystem (`backend/uploads/`, `backend/output/`) | No DB needed for a single-shot spike (PERS-01 is Phase 3). |
| Audio join | `ffmpeg` concat demuxer via `subprocess.run([...])` (arg-list, never `shell=True`) | CLAUDE.md mandate; GEN-04; command-injection-safe. |
| Chunking | Python stdlib regex paragraph split + greedy merge to ~800 chars | D-01/D-02; no NLP library. Oversized single paragraphs split at sentence boundary. |
| Dev degradation | `TTS_BACKEND` env flag: `mock` (silent WAV, no GPU) \| `http` (real TTS container) | CLAUDE.md `TTS_BACKEND=mock` pattern; lets the whole pipeline be built/tested before the GPU risk is retired, and keeps Phase 2/3 testable on GPU-less dev machines. |
| Python tooling | `uv` deps/venv, `ruff` lint/format, `pytest` tests | D-11 / CLAUDE.md. |
| Directory layout | Pre-split monorepo: `backend/` + empty `frontend/` at repo root | D-10 — avoids a restructuring commit in Phase 2. |

## Internal TTS Contract (locked here; consumed by backend, implemented by tts_service)

- `POST /synthesize` on the TTS container — request JSON `{"text": str, "speaker": str}` (`speaker` optional, defaults to `TTS_DEFAULT_SPEAKER`); response `Content-Type: audio/wav` bytes on 200; JSON `{"detail": ...}` on 4xx/5xx.
- `GET /healthz` → `200` once the model is loaded and resident (used as a pod readiness gate).
- TTS container listens on port `8001`; backend on port `8000`. Backend reaches TTS via `TTS_SERVICE_URL` (default `http://localhost:8001`).

## Stack Touched in Phase 1

- [x] Project scaffold (FastAPI, `uv` `pyproject.toml`, `ruff`, `pytest`) — Plan 01
- [x] Routing — real `POST /projects` upload endpoint — Plan 01
- [x] Storage — real filesystem read (upload) AND write (joined output) — Plan 01
- [x] "UI" interaction — real `curl` upload wired to the full pipeline — Plan 01 (mock) → Plan 03 (real GPU)
- [x] GPU — real Qwen3-TTS synthesis inside a GPU-scoped Podman container — Plan 02
- [x] Deployment — two-container Podman pod, GPU passthrough, documented local full-stack run — Plan 03

## Out of Scope (Deferred to Later Slices)

> Explicit, to prevent future phases re-litigating Phase 1's minimalism.

- LLM cast detection / narration-dialogue segmentation (Phase 2 — CAST-01/02/03).
- Any web frontend / React / TanStack table (Phase 2/3).
- Per-segment character voices, free-text instruct-steering, VoiceDesign fallback (Phase 2/3 — D-03/D-04).
- Database / project persistence / save-reopen (Phase 3 — PERS-01/02).
- Content-hash caching, single-row regeneration, resumable batch status (Phase 3 — GEN-02/03/05).
- Tailscale-only exposure hardening (Phase 3 — DEPL-02).
- Re-verification on the production RX 9070 XT VM — tracked follow-up once the VM exists (D-09), NOT this phase's scope.

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering the decisions above:

- **Phase 2:** Upload `.epub` too; Grok auto-casts characters + segments text; review/voice-assignment wizard with instant previews.
- **Phase 3:** Full editable segment table, cached + resumable batch generation, single-row regenerate, project save/reopen, Tailscale-only deployment.

## Follow-up Gate (tracked, not in-scope)

- **Re-verify on target VM (RX 9070 XT / `gfx1201`) once available** — D-09. Phase 1 proves the bet on the local `gfx1103` APU; the target-hardware run is a fast sanity re-check, not a rebuild.
