<!-- GSD:project-start source:PROJECT.md -->
## Project

**Qwen Ebook Narrator**

A self-hosted web app that turns long text (ebooks, articles) into a multi-voice narrated audiobook using Qwen TTS. An LLM (xAI/Grok) analyzes the source text, auto-detects the cast of characters (narrator plus speaking characters, inferred from context — names, ages, personalities), and splits the text into narration/dialogue segments with per-segment voice instructions. The user reviews and edits everything in a spreadsheet-like table before generating and joining the final audio file. Built for personal use: converting owned text into audio for commute/workout listening.

**Core Value:** Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.

### Constraints

- **Hardware**: Deployment GPU is AMD RX 9070 XT, 16GB VRAM — Qwen TTS inference must run under ROCm within that VRAM budget.
- **Deployment**: Must run via Podman (not Docker) on the target VM.
- **Network**: Served as a Tailscale service — no public internet exposure, single trusted user/network.
- **External APIs**: Depends on xAI Grok API availability/cost for text analysis; Qwen TTS is self-hosted so no per-request cloud TTS cost, but requires GPU inference infrastructure in the container.
- **Persistence**: Single-user with saved projects — needs some form of local storage (files/DB) for project state (text, cast, segments, generated audio), no multi-tenant data model needed.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

Stack is decided and reflected in the code. This is a quick reference — the full
research writeup (rationale, alternatives, sources, confidence ratings) lives
in `.planning/` (`research/STACK.md`).

### Current stack

| Area | Choice | Notes |
|------|--------|-------|
| TTS model | Qwen3-TTS-12Hz-1.7B-CustomVoice (HF, Apache 2.0) | Preset + free-text `instruct` steering, no voice cloning. VoiceDesign variant is the fallback for description-only voices. |
| TTS runtime | `qwen-tts` pip pkg on `transformers`, `attn_implementation="sdpa"` | Pin exact versions — new, fast-moving package. |
| GPU runtime | PyTorch ROCm 7.2 build (`gfx1201` / RX 9070 XT) | Match container ROCm family to host driver. |
| Language | Python 3.12 | |
| Backend | FastAPI (>=0.135 for native SSE) | One process owns upload, Grok calls, EPUB parse, TTS queue, ffmpeg join, SQLite. |
| Persistence | SQLModel + one SQLite `projects.db` | `Project`/`Character`/`Segment` tables; audio referenced by path, not blobbed. |
| LLM | `xai-sdk` (AsyncClient), Grok `grok-4.3`, Pydantic structured output | One shared Pydantic schema across LLM output, DB, and API. |
| EPUB parse | `ebooklib` + `beautifulsoup4` + `lxml` (`recover=True`) | Filter by reading order; expect malformed XHTML. |
| Audio join | system `ffmpeg` via `subprocess`, concat demuxer | Not the concat filter, not pydub. |
| Progress push | `fastapi.sse.EventSourceResponse` | One-way server->client; not WebSockets. |
| Container | Podman + Quadlets (systemd units) | GPU passthrough: `/dev/kfd`, `/dev/dri`, `--group-add keep-groups`. |
| Tooling | `uv` (deps/venv), `ruff` (lint/format) | |
| Dev without GPU | `TTS_BACKEND=mock` returns a placeholder WAV | Gate the real `qwen-tts` import behind the flag. |

### What NOT to use

- **Qwen3-TTS Base (voice cloning)** as the default voice path — speaker-encoder path is unreliable on ROCm. Use CustomVoice.
- **vLLM / vLLM-Omni** — RDNA4 kernels still experimental; no throughput need for a single-user tool. Use plain Transformers + `sdpa`.
- **`flash-attn`** — CUDA-only. Use `attn_implementation="sdpa"`.
- **Docker / docker-compose** — project requires Podman. Use Podman + Quadlets.
- **Kubernetes** — out of scope. Use Podman + Quadlets.
- **Celery / Redis / any task queue** — one GPU, one user. Use an in-process asyncio worker + a `status` column in SQLite.
- **Multi-tenant auth** — Tailscale is the access boundary; no auth layer.
- **pydub** for the production join path — unmaintained; call ffmpeg directly.

Note: the stack markers are kept, so a future GSD project-sync could re-expand
this block from `research/STACK.md` and clobber the condensation. That is
acceptable for now; if it recurs, raise removing the `source:` marker with the
user rather than deciding it here.
<!-- GSD:stack-end -->

## Conventions

- **Lint gate (required):** After any major change to Python code, run
  `cd backend && uv run ruff check .` (strict: `E, F, I, UP, B` per
  `backend/pyproject.toml`). Apply `--fix` for auto-fixable issues, then fix
  any remaining warnings manually before committing — do not commit with
  outstanding ruff warnings.
