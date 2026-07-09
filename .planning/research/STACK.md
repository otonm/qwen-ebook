# Stack Research

**Domain:** Self-hosted ebook-to-audiobook narration web app (LLM text analysis + local multi-voice TTS + spreadsheet-style review UI)
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH (HIGH on web framework/EPUB/xAI API choices, MEDIUM on Qwen TTS+ROCm specifics due to the model and ROCm 7.2 RDNA4 support being very recent/fast-moving)

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Qwen3-TTS-12Hz-1.7B-CustomVoice** | latest (Apache 2.0, HF `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`) | Self-hosted multi-voice TTS engine | This is the actual open-weight "Qwen TTS" model. The **CustomVoice** variant is the one built for this app's exact need: 9 built-in premium voice presets (`model.get_supported_speakers()`) **plus** free-text `instruct` steering ("speak in an angry tone", "soothing narrator voice") layered on top of a preset — i.e. preset + instruction-derived voice, no reference-audio cloning required. Confirmed working on AMD/ROCm in community reports (see Pitfalls below) unlike the voice-cloning `Base` variant. 1.7B params, ~4-8GB VRAM in bf16 — comfortably fits the 16GB RX 9070 XT. HIGH confidence (verified via official GitHub repo + HF model card + community ROCm reports). |
| **Hugging Face Transformers via the `qwen-tts` pip package** | `qwen-tts` (PyPI, first released Jan 2026, currently ~0.1.x) on `transformers` | TTS inference runtime | The official, simplest way to run the model (`Qwen3TTSModel.from_pretrained(...)`). Do **not** reach for vLLM here even though "vLLM-Omni has day-0 support" — vLLM's ROCm/RDNA4 (gfx1201) kernel support is still experimental as of ROCm 7.2 (March 2026): FP8 paths silently fall back to FP32 dequant, bypassing RDNA4's matrix accelerators, and vLLM is built for high-throughput concurrent serving, which this single-user, one-segment-at-a-time app doesn't need. Plain Transformers with `attn_implementation="sdpa"` (not flash-attn, which is CUDA-only/needs a ROCm fork) is what community ROCm users report actually working. MEDIUM confidence. |
| **PyTorch (ROCm build)** | `torch` 2.8/2.9+`rocm7.2` (via `--index-url https://download.pytorch.org/whl/rocm7.2` or the `rocm/pytorch` container) | GPU tensor runtime for TTS | ROCm 7.2 (March 2026) is the first ROCm release with **official** RDNA4 support, explicitly listing RX 9070 / RX 9070 XT (LLVM target `gfx1201`). Earlier ROCm versions require the `HSA_OVERRIDE_GFX_VERSION` spoofing hack that community Qwen3-TTS/AMD guides used for older/APU targets (Strix Halo gfx1151) — not needed on 9070 XT with ROCm 7.2+. MEDIUM-HIGH confidence (ROCm compatibility matrix + multiple 2026 community sources agree). |
| **Python** | 3.12 | Backend + TTS runtime language | Explicitly the version the Qwen3-TTS repo recommends (`conda create -n qwen3-tts python=3.12`), matches the `rocm/pytorch:...py3.12...` container tags, and is current for FastAPI/async ecosystem. |
| **FastAPI** | 0.139.x (current as of July 2026) | Backend web framework / API + orchestration layer | Native async, first-class Pydantic validation (maps 1:1 onto Grok structured-output schemas and the segment/character data model), and — critically — **FastAPI now has built-in SSE support** (`fastapi.sse.EventSourceResponse`, added ~0.135) so live per-segment generation progress needs no extra dependency. One process can own: file upload, Grok API calls, EPUB parsing, the TTS generation queue, ffmpeg joining, and SQLite persistence — appropriate for a single-user self-hosted tool. HIGH confidence. |
| **React 19 + Vite** | React 19.x, Vite 6/7.x | Frontend SPA framework/build tool | This is an interactive, stateful editor app (editable table, live per-row status, dropdowns) — a client-rendered SPA is the right fit, and there's no SEO/SSR need for a private single-user Tailscale tool, so plain Vite+React beats Next.js in simplicity (no server-rendering infra to run/maintain in the container). HIGH confidence. |
| **TanStack Table v8 + shadcn/ui + Tailwind CSS v4** | `@tanstack/react-table` ^8.x, `tailwindcss` ^4.x | Spreadsheet-like editable table UI | TanStack Table is the current standard "headless" table engine for building custom editable, sortable data-grid UIs in React (its official docs even ship an "Editable Data" example); shadcn/ui (Radix-based, copy-into-repo components, not an npm black box) is the standard pairing for building a polished data-table + sidebar-form layout quickly with Tailwind v4. Avoids paid/heavier grid libs (AG Grid Enterprise, Handsontable) that are overkill for a 3-column editable table. HIGH confidence. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `xai-sdk` | latest (pip install `xai-sdk`, Python ≥3.10) | Official Python client for the Grok API | Use `client.chat.create(model="grok-4.3").parse(YourPydanticModel)` (or `response_format=YourPydanticModel` + `chat.sample()`) to get schema-guaranteed JSON for character-cast detection and segment splitting. Supports sync `Client` and `AsyncClient` — use `AsyncClient` inside FastAPI request handlers. |
| `sqlmodel` | latest (built on SQLAlchemy 2.x + Pydantic) | Project persistence (text, cast, segments, generation status) | One dependency gives you both the ORM/DB layer and request/response schema validation shared with FastAPI. SQLite file per deployment (not per-project) is enough at single-user scale — one `projects.db` with `Project`, `Character`, `Segment` tables; generated audio files referenced by path on disk, not blob-stored in the DB. |
| `ebooklib` + `beautifulsoup4` + `lxml` | `EbookLib` ^0.19, `beautifulsoup4` ^4.x | EPUB parsing → clean chapter text | `ebooklib` reads the EPUB2/3 container/spine/manifest and gives you the raw XHTML per chapter via `book.get_items_of_type(ebooklib.ITEM_DOCUMENT)`; BeautifulSoup (with the `lxml` parser, not the stdlib one, for resilience) strips it to clean text. Filter spine items by the book's actual reading order, not just filename heuristics, and be defensive — a meaningful fraction of real-world EPUBs have malformed XHTML (unclosed tags, duplicate `<body>`), so wrap chapter parsing in a try/recover path (`lxml`'s `recover=True`) rather than trusting every file to parse cleanly. |
| `ffmpeg` (system binary, called via `subprocess`) | current Debian/Ubuntu package (6.x+) | Joining per-segment audio into final MP3/WAV | Use the **concat demuxer** (`ffmpeg -f concat -safe 0 -i list.txt -c:a libmp3lame output.mp3` or `-c copy` for WAV-to-WAV with identical params) rather than the concat *filter* — it's the standard for joining many same-codec segments cheaply (no per-sample re-encode needed when formats match, which they will since every segment comes from the same Qwen3-TTS instance). Since all segments share sample rate/channels, concat demuxer is a correct and fast fit. Avoid `pydub` for the join step — it's effectively unmaintained (no meaningful release since 2021) and just shells out to ffmpeg anyway with extra overhead; calling ffmpeg directly avoids that indirection and an extra dependency for something this app needs to be reliable and fast. |
| `python-ffmpeg` / direct `subprocess` | — | ffmpeg invocation wrapper | Plain `subprocess.run([...])` with explicit argument lists is sufficient and more transparent/debuggable than adding `ffmpeg-python`'s graph-builder API for what is fundamentally one concat command and occasional format conversion. Skip `ffmpeg-python` unless the audio pipeline grows much more complex. |
| `fastapi.sse.EventSourceResponse` (built into FastAPI ≥0.135, no separate install) | — | Live generation progress to the frontend | One-directional server→client push (per-segment "queued/generating/done/error" status) is exactly what SSE is for; don't reach for WebSockets — there's no need for client→server real-time messages beyond normal REST calls, and SSE is simpler to reason about, auto-reconnects, and needs no extra library now that FastAPI ships it natively. If the FastAPI version pinned ends up <0.135, fall back to the `sse-starlette` package (mature, same API shape). |
| `pydantic` v2 | (pulled in by FastAPI/SQLModel/xai-sdk) | Schema definitions shared across LLM output, DB models, and API responses | Define one `CharacterSuggestion` / `SegmentSuggestion` Pydantic schema and reuse it as: (a) the Grok structured-output schema, (b) the FastAPI response model, (c) the shape persisted via SQLModel. Avoids re-defining the character/segment shape three times. |
| Podman + `podman-compose` (or a single Podman Quadlet/systemd unit) | Podman 5.x | Container orchestration on the VM | See Architecture section below — GPU passthrough works the same way with `podman run` or `podman-compose`; Quadlets (systemd-managed Podman units) are the modern rootless-friendly way to run a persistent self-hosted service and are worth using over ad hoc `podman run` for a long-lived service. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `uv` | Python dependency/venv management | Fast, single-binary, works cleanly for both a CPU-only dev environment and the ROCm container build; simpler than Poetry for a project with a somewhat unusual dependency (ROCm PyTorch wheel index). |
| `ruff` | Python lint/format | Standard, fast, replaces flake8+black+isort in one tool. |
| Local dev TTS mocking | Graceful GPU degradation | PROJECT.md notes dev happens on a non-GPU machine. Implement a `TTS_BACKEND=mock` env flag that returns a short silent/placeholder WAV instantly, so the full upload → analyze → edit → "generate" → join flow is testable without ROCm hardware. Gate the real `qwen-tts` import behind this flag so dev machines never need torch+ROCm installed at all. |

## Installation

```bash
# --- Backend (Python, inside the ROCm-capable container) ---
uv venv --python 3.12
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.2
uv pip install qwen-tts
uv pip install "fastapi[standard]" sqlmodel xai-sdk ebooklib beautifulsoup4 lxml python-multipart

# ffmpeg as an OS package inside the container image, not pip
# (Debian/Ubuntu base): apt-get install -y ffmpeg

# --- Frontend ---
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @tanstack/react-table
npx shadcn@latest init   # Tailwind v4 + shadcn components
npm install -D tailwindcss @tailwindcss/vite
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Qwen3-TTS-1.7B-CustomVoice | Qwen3-TTS-1.7B-VoiceDesign | Use VoiceDesign if you want to *generate a brand-new voice from a free-text description* for a character with no good preset match, rather than steering one of the 9 presets. Worth wiring in as a secondary path for characters the CustomVoice presets don't fit well — the app's spec ("LLM/context-derived voice instructions for characters without a good preset match") maps naturally onto VoiceDesign as a fallback alongside CustomVoice as the default. |
| Qwen3-TTS-1.7B-CustomVoice | Qwen3-TTS-0.6B-CustomVoice | Use the 0.6B variant if generation latency/throughput matters more than voice quality — it's faster and uses less VRAM, with headroom to spare either way on a 16GB card, so start with 1.7B for quality and only drop down if segment generation time becomes a bottleneck. |
| HF Transformers (`qwen-tts` pkg) | vLLM-Omni | Revisit vLLM once ROCm/RDNA4 (gfx1201) kernel support matures past "experimental" (watch ROCm release notes past 7.2) — worthwhile *only* if you need much higher throughput (e.g. batch-generating many segments concurrently), which a single-user sequential-review workflow doesn't require. |
| FastAPI + SQLModel/SQLite | Node/Express or Django | Django is overkill (this app doesn't need its admin/ORM-migration machinery for ~3 tables); Node/Express would work but forces a second language boundary for no benefit — the TTS inference, ffmpeg orchestration, and EPUB parsing all want to live in Python next to `qwen-tts`/`torch` anyway. |
| React + Vite (SPA) | Next.js | Use Next.js only if you anticipate needing SSR/streaming HTML or plan to expose this beyond a private Tailscale single-user tool — neither applies here, and Next.js's server runtime adds an extra process/complexity for no real gain in this context. |
| React + TanStack Table | htmx + Alpine.js | A lightweight htmx-based UI is a legitimate alternative if you want to minimize frontend build tooling entirely — but the row-level interactivity (dropdowns bound to a dynamic character list, per-row async regenerate-and-rejoin, live status badges) is meaningfully easier to keep consistent client-side with React state than by round-tripping partial HTML swaps for every edit. |
| ffmpeg concat demuxer via subprocess | `pydub` | Use pydub only for quick prototyping/exploration in a notebook — not recommended for the production join path (unmaintained, adds overhead, no benefit over calling ffmpeg directly for a same-codec concat). |
| SSE (`fastapi.sse.EventSourceResponse`) | WebSockets | Switch to WebSockets only if you later want bidirectional real-time features (e.g. live collaborative editing, or the client cancelling/reordering the generation queue mid-stream in a chatty way) — not needed for one-way progress push to a single client. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Qwen3-TTS **Base** model (voice cloning) as the primary/default voice path | Requires a reference audio clip + transcript per character (not what this app's design wants — preset + instruction, not cloning), and community reports show voice-cloning-specific code paths (the speaker encoder) are the part that's actually broken/unreliable on AMD/ROCm today (silent hangs reported on RX 7800 XT). CustomVoice, which this app needs anyway, is reported working. | `Qwen3-TTS-1.7B-CustomVoice` (+ `VoiceDesign` as a fallback for description-only voices) |
| vLLM / vLLM-Omni for the TTS serving path (on this hardware, today) | ROCm RDNA4 (gfx1201) kernel support in vLLM is still experimental as of ROCm 7.2 (March 2026) — FP8 paths silently fall back to full-precision dequant, undermining the whole point of using vLLM, and vLLM's value (high-throughput concurrent batching) doesn't apply to a single-user sequential workflow. | Plain HF Transformers via the `qwen-tts` package with `attn_implementation="sdpa"` |
| `flash-attn` (the CUDA package) | It's CUDA-only; installing it on a ROCm host will fail or silently do nothing useful. A ROCm fork exists but community Qwen3-TTS/AMD reports found `sdpa` attention sufficient and simpler. | `attn_implementation="sdpa"` (PyTorch's built-in scaled-dot-product-attention, ROCm-compatible) |
| Docker / `docker-compose` | Project constraint explicitly requires Podman, and Podman's rootless model + Quadlets are a better fit for a single trusted-network personal VM anyway (no privileged daemon). | Podman + Quadlets (systemd units) or `podman-compose` |
| Celery + Redis (or any distributed task queue) for the TTS generation queue | Massive overkill — there is exactly one GPU and one user, so generation is inherently a single sequential worker. Adding Redis/Celery means running and maintaining an extra service for zero real concurrency benefit. | An in-process asyncio background task/worker inside the FastAPI app, backed by a `status` column per segment row in SQLite so the queue state survives a restart |
| Building a full multi-tenant auth system | Explicitly out of scope per PROJECT.md — Tailscale is the access-control boundary. Adding OAuth/session auth is wasted surface area and complexity. | No auth layer; rely on Tailscale network membership |
| pydub for the production audio-join pipeline | Unmaintained since ~2021, wraps ffmpeg with extra overhead and less control over concat behavior (codec copy vs re-encode). | Direct `ffmpeg` subprocess calls using the concat demuxer |

## Stack Patterns by Variant

**If character voice needs a genuinely custom, non-preset voice (no built-in speaker fits):**
- Use `Qwen3-TTS-1.7B-VoiceDesign` for that character instead of CustomVoice
- Because VoiceDesign generates a voice from a free-text description rather than picking/steering one of the 9 fixed CustomVoice speakers — this directly matches the PROJECT.md requirement "LLM/context-derived voice instructions for characters without a good preset match"

**If dev/test happens on a non-ROCm machine (per PROJECT.md's stated dev environment):**
- Use a `TTS_BACKEND=mock` environment flag that swaps in a stub TTS function returning a placeholder WAV
- Because the real `qwen-tts`/ROCm PyTorch stack can't run there, and the rest of the app (upload, Grok analysis, table editing, project persistence, ffmpeg join) has zero GPU dependency and should be fully testable without it

**If ROCm 7.2's gfx1201 support turns out to have rough edges at deploy time:**
- Fall back to `HSA_OVERRIDE_GFX_VERSION` spoofing (e.g. reporting as a nearby supported target) as a temporary workaround, the way community guides did for Strix Halo (gfx1151) before official support landed
- Because this is a known, documented escape hatch in the ROCm/PyTorch community for "GPU technically works but isn't in the officially-blessed list yet" situations — treat it as a fallback, not the default, since RX 9070 XT/gfx1201 is now officially listed as supported in ROCm 7.2

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `torch` (rocm7.2 wheel) | ROCm 7.2.x driver/userspace on host + `rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_2.10.0*` container base | Match the container's ROCm userspace version family to the host kernel driver; mismatches between container ROCm version and host driver are the most common source of "GPU not detected" issues reported in community threads. |
| `qwen-tts` pip package | `transformers` + `torch` versions it pins (check `pyproject.toml`/`requirements.txt` at install time — pin exact versions once you install, since this is a very new, fast-moving package as of early 2026) | Because `qwen-tts` had only ~7 releases since its Jan 2026 debut, expect breaking changes between minor versions; pin the exact version in the container image rather than tracking latest. |
| FastAPI ≥0.135 | Native `fastapi.sse.EventSourceResponse` | If pinning an older FastAPI (<0.135) for any reason, use `sse-starlette` instead — same conceptual API, mature and stable. |
| `xai-sdk` | Grok model names `grok-4.3` / `grok-4.5` / `grok-4.20-*` (as of July 2026 — this API's model lineup moves fast, confirm current names against `docs.x.ai/developers/models` at implementation time) | `grok-4.3` (1M context, $1.25/$2.50 per 1M tokens) is the better fit for this app's cast-detection/segmentation task over full ebook text — cheaper than `grok-4.5` and its 1M context window comfortably covers a full novel's text in one call; use `grok-4.5` only if `grok-4.3`'s output quality proves insufficient for character detection nuance. |

## Sources

- [QwenLM/Qwen3-TTS GitHub repo](https://github.com/QwenLM/Qwen3-TTS) — model variants, install, usage, Python version — HIGH confidence
- [Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice on Hugging Face](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) — voice preset list, instruct-steering, license, code example — HIGH confidence
- [Qwen3-TTS-12Hz-0.6B-Base not generating with AMD on Linux · Issue #93](https://github.com/QwenLM/Qwen3-TTS/issues/93) — confirms CustomVoice works on AMD where Base's speaker-encoder path hangs — MEDIUM confidence (single user report, but specific and technical)
- [Support for AMD GPUs (ROCm) in Qwen3-TTS Voice Cloning · Discussion #308](https://github.com/QwenLM/Qwen3-TTS/discussions/308) — confirms voice-cloning-specific ROCm gap, no maintainer response yet — MEDIUM confidence
- [Running Qwen TTS on AMD Strix Halo (tinycomputers.io)](https://tinycomputers.io/posts/qwen-tts-on-amd-strix-halo.html) — concrete ROCm setup (env vars, `sdpa`, bf16, 8-10GB peak VRAM, `qwen-tts` CustomVoice working end-to-end on AMD) — MEDIUM confidence (community blog, but detailed and consistent with official docs)
- [ROCm compatibility matrix (AMD official docs)](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) — ROCm 7.2 official RDNA4/gfx1201 support — HIGH confidence
- [rocm/pytorch Docker Hub](https://hub.docker.com/r/rocm/pytorch) — current image tags (`rocm7.2.4_ubuntu24.04_py3.12_pytorch_2.10.0...`) — HIGH confidence
- [Run ROCm Docker containers — AMD ROCm docs](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/how-to/docker.html) — `--device /dev/kfd --device /dev/dri` pattern — HIGH confidence
- [How to Run AMD GPU Containers with Podman (oneuptime.com)](https://oneuptime.com/blog/post/2026-03-18-run-amd-gpu-containers-podman/view) — rootless Podman `--group-add keep-groups` pattern — MEDIUM confidence
- [xai-sdk-python GitHub repo](https://github.com/xai-org/xai-sdk-python) — install, `Client`/`AsyncClient`, Pydantic structured-output usage — HIGH confidence
- [Structured Outputs — xAI Docs](https://docs.x.ai/developers/model-capabilities/text/structured-outputs) — `response_format`, `.parse()`, streaming limitation — HIGH confidence
- [Models — xAI Docs](https://docs.x.ai/developers/models) — current Grok model names/pricing/context windows (July 2026) — HIGH confidence
- [FastAPI Server-Sent Events docs](https://fastapi.tiangolo.com/tutorial/server-sent-events/) — native `EventSourceResponse` since ~0.135 — HIGH confidence
- [FastAPI release notes / PyPI](https://fastapi.tiangolo.com/release-notes/) — current version 0.139.0 (July 2026) — HIGH confidence
- [ebooklib GitHub repo](https://github.com/aerkalov/ebooklib) — EPUB parsing API — HIGH confidence
- [SQLModel + FastAPI official tutorial](https://sqlmodel.tiangolo.com/tutorial/fastapi/) — session-per-request pattern, SQLite `check_same_thread=False` — HIGH confidence
- [TanStack Table docs — Editable Data example](https://tanstack.com/table/latest/docs/framework/react/examples/editable-data) — HIGH confidence
- [shadcn/ui Data Table docs](https://ui.shadcn.com/docs/components/radix/data-table) — TanStack Table + shadcn pairing — HIGH confidence
- FFmpeg concat demuxer vs filter/pydub comparison (multiple 2026 community sources cross-checked) — MEDIUM confidence

---
*Stack research for: self-hosted ebook-to-audiobook narration web app*
*Researched: 2026-07-09*
