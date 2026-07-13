# Stack Research

**Domain:** Self-hosted ebook-to-audiobook narration web app (LLM text analysis + local multi-voice TTS + spreadsheet-style review UI)
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH (HIGH on web framework/EPUB/xAI API choices, MEDIUM on Qwen TTS+ROCm specifics due to the model and ROCm 7.2 RDNA4 support being very recent/fast-moving)

**Update (2026-07-10):** The LLM access layer described below (`xai-sdk` talking
directly to the xAI API) was replaced with a plain `httpx` call to OpenRouter's
OpenAI-compatible chat-completions endpoint, so any OpenRouter-supported model
can be used via a single `OPENROUTER_API_KEY` instead of an xAI-specific key.
The original xai-sdk research below is kept for historical rationale (why a
Grok-family model with a large context window was chosen for this task); the
`xai-sdk` rows/install command are superseded — see `backend/app/analysis_client.py`
and `CLAUDE.md`'s stack table for the current implementation.

**Update (2026-07-13, v1.1 milestone):** See the **"v1.1 Addendum"** section at
the end of this file for the new research needed for generation-control
(immediate cancellation) and config-panel (dual model swap, FLAC/Opus output)
capabilities. Everything above this addendum is unchanged v1.0 research.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Qwen3-TTS-12Hz-1.7B-CustomVoice** | latest (Apache 2.0, HF `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`) | Self-hosted multi-voice TTS engine | This is the actual open-weight "Qwen TTS" model. The **CustomVoice** variant is the one built for this app's exact need: 9 built-in premium voice presets (`model.get_supported_speakers()`) **plus** free-text `instruct` steering ("speak in an angry tone", "soothing narrator voice") layered on top of a preset — i.e. preset + instruction-derived voice, no reference-audio cloning required. Confirmed working on AMD/ROCm in community reports (see Pitfalls below) unlike the voice-cloning `Base` variant. 1.7B params, ~4-8GB VRAM in bf16 — comfortably fits the 16GB RX 9070 XT. HIGH confidence (verified via official GitHub repo + HF model card + community ROCm reports). |
| **Hugging Face Transformers via the `qwen-tts` pip package** | `qwen-tts` (PyPI, first released Jan 2026, currently ~0.1.x) on `transformers` | TTS inference runtime | The official, simplest way to run the model (`Qwen3TTSModel.from_pretrained(...)`). Do **not** reach for vLLM here even though "vLLM-Omni has day-0 support" — vLLM's ROCm/RDNA4 (gfx1201) kernel support is still experimental as of ROCm 7.2 (March 2026): FP8 paths silently fall back to FP32 dequant, bypassing RDNA4's matrix accelerators, and vLLM is built for high-throughput concurrent serving, which this single-user, one-segment-at-a-time app doesn't need. Plain Transformers with `attn_implementation="sdpa"` (not flash-attn, which is CUDA-only/needs a ROCm fork) is what community ROCm users report actually working. MEDIUM confidence. |
| **PyTorch (ROCm build)** | `torch` 2.8/2.9+`rocm7.2` (via `--index-url https://download.pytorch.org/whl/rocm7.2` or the `rocm/pytorch` container) | GPU tensor runtime for TTS | ROCm 7.2 (March 2026) is the first ROCm release with **official** RDNA4 support, explicitly listing RX 9070 / RX 9070 XT (LLVM target `gfx1201`). Earlier ROCm versions require the `HSA_OVERRIDE_GFX_VERSION` spoofing hack that community Qwen3-TTS/AMD guides used for older/APU targets (Strix Halo gfx1151) — not needed on 9070 XT with ROCm 7.2+. MEDIUM-HIGH confidence (ROCm compatibility matrix + multiple 2026 community sources agree). |
| **Python** | 3.12 | Backend + TTS runtime language | Explicitly the version the Qwen3-TTS repo recommends (`conda create -n qwen3-tts python=3.12`), matches the `rocm/pytorch:...py3.12...` container tags, and is current for FastAPI/async ecosystem. |
| **FastAPI** | 0.139.x (current as of July 2026) | Backend web framework / API + orchestration layer | Native async, first-class Pydantic validation (maps 1:1 onto the LLM structured-output schema and the segment/character data model), and — critically — **FastAPI now has built-in SSE support** (`fastapi.sse.EventSourceResponse`, added ~0.135) so live per-segment generation progress needs no extra dependency. One process can own: file upload, LLM (OpenRouter) API calls, EPUB parsing, the TTS generation queue, ffmpeg joining, and SQLite persistence — appropriate for a single-user self-hosted tool. HIGH confidence. |
| **React 19 + Vite** | React 19.x, Vite 6/7.x | Frontend SPA framework/build tool | This is an interactive, stateful editor app (editable table, live per-row status, dropdowns) — a client-rendered SPA is the right fit, and there's no SEO/SSR need for a private single-user Tailscale tool, so plain Vite+React beats Next.js in simplicity (no server-rendering infra to run/maintain in the container). HIGH confidence. |
| **TanStack Table v8 + shadcn/ui + Tailwind CSS v4** | `@tanstack/react-table` ^8.x, `tailwindcss` ^4.x | Spreadsheet-like editable table UI | TanStack Table is the current standard "headless" table engine for building custom editable, sortable data-grid UIs in React (its official docs even ship an "Editable Data" example); shadcn/ui (Radix-based, copy-into-repo components, not an npm black box) is the standard pairing for building a polished data-table + sidebar-form layout quickly with Tailwind v4. Avoids paid/heavier grid libs (AG Grid Enterprise, Handsontable) that are overkill for a 3-column editable table. HIGH confidence. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| ~~`xai-sdk`~~ (superseded, see 2026-07-10 update above) | — | — | — |
| OpenRouter (via `httpx`, no SDK) | REST API, `POST https://openrouter.ai/api/v1/chat/completions` | LLM gateway for character-cast detection and segment splitting | `Authorization: Bearer $OPENROUTER_API_KEY` + `response_format: {"type": "json_schema", "json_schema": {"schema": YourPydanticModel.model_json_schema(), "strict": true}}` gets schema-guaranteed JSON, same shape as xai-sdk's `.parse()`. No extra dependency — `httpx.AsyncClient` (already a project dependency for TTS) is enough; OpenRouter is a routing layer over many providers/models, not a single-vendor SDK. Default model `x-ai/grok-4.3` preserves the original 1M-context single-shot-analysis assumption (D-06); swappable via `OPENROUTER_MODEL` env var to any OpenRouter-supported model. |
| `sqlmodel` | latest (built on SQLAlchemy 2.x + Pydantic) | Project persistence (text, cast, segments, generation status) | One dependency gives you both the ORM/DB layer and request/response schema validation shared with FastAPI. SQLite file per deployment (not per-project) is enough at single-user scale — one `projects.db` with `Project`, `Character`, `Segment` tables; generated audio files referenced by path on disk, not blob-stored in the DB. |
| `ebooklib` + `beautifulsoup4` + `lxml` | `EbookLib` ^0.19, `beautifulsoup4` ^4.x | EPUB parsing → clean chapter text | `ebooklib` reads the EPUB2/3 container/spine/manifest and gives you the raw XHTML per chapter via `book.get_items_of_type(ebooklib.ITEM_DOCUMENT)`; BeautifulSoup (with the `lxml` parser, not the stdlib one, for resilience) strips it to clean text. Filter spine items by the book's actual reading order, not just filename heuristics, and be defensive — a meaningful fraction of real-world EPUBs have malformed XHTML (unclosed tags, duplicate `<body>`), so wrap chapter parsing in a try/recover path (`lxml`'s `recover=True`) rather than trusting every file to parse cleanly. |
| `ffmpeg` (system binary, called via `subprocess`) | current Debian/Ubuntu package (6.x+) | Joining per-segment audio into final MP3/WAV | Use the **concat demuxer** (`ffmpeg -f concat -safe 0 -i list.txt -c:a libmp3lame output.mp3` or `-c copy` for WAV-to-WAV with identical params) rather than the concat *filter* — it's the standard for joining many same-codec segments cheaply (no per-sample re-encode needed when formats match, which they will since every segment comes from the same Qwen3-TTS instance). Since all segments share sample rate/channels, concat demuxer is a correct and fast fit. Avoid `pydub` for the join step — it's effectively unmaintained (no meaningful release since 2021) and just shells out to ffmpeg anyway with extra overhead; calling ffmpeg directly avoids that indirection and an extra dependency for something this app needs to be reliable and fast. |
| `python-ffmpeg` / direct `subprocess` | — | ffmpeg invocation wrapper | Plain `subprocess.run([...])` with explicit argument lists is sufficient and more transparent/debuggable than adding `ffmpeg-python`'s graph-builder API for what is fundamentally one concat command and occasional format conversion. Skip `ffmpeg-python` unless the audio pipeline grows much more complex. |
| `fastapi.sse.EventSourceResponse` (built into FastAPI ≥0.135, no separate install) | — | Live generation progress to the frontend | One-directional server→client push (per-segment "queued/generating/done/error" status) is exactly what SSE is for; don't reach for WebSockets — there's no need for client→server real-time messages beyond normal REST calls, and SSE is simpler to reason about, auto-reconnects, and needs no extra library now that FastAPI ships it natively. If the FastAPI version pinned ends up <0.135, fall back to the `sse-starlette` package (mature, same API shape). |
| `pydantic` v2 | (pulled in by FastAPI/SQLModel) | Schema definitions shared across LLM output, DB models, and API responses | Define one `CharacterSuggestion` / `SegmentSuggestion` Pydantic schema and reuse it as: (a) the OpenRouter structured-output JSON schema, (b) the FastAPI response model, (c) the shape persisted via SQLModel. Avoids re-defining the character/segment shape three times. |
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
uv pip install "fastapi[standard]" sqlmodel ebooklib beautifulsoup4 lxml python-multipart  # httpx already required by fastapi[standard]; no separate LLM SDK

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
| Qwen3-TTS-1.7B-CustomVoice | Qwen3-TTS-0.6B-CustomVoice | Use the 0.6B variant if generation latency/throughput matters more than voice quality — it's faster and uses less VRAM, with headroom to spare either way on a 16GB card, so start with 1.7B for quality and only drop down if segment generation time becomes a bottleneck. **(v1.1: this tradeoff is now a first-class user-facing toggle — see the v1.1 Addendum below for the load/unload mechanics and a critical `instruct`-steering caveat on the 0.6B checkpoint.)** |
| HF Transformers (`qwen-tts` pkg) | vLLM-Omni | Revisit vLLM once ROCm/RDNA4 (gfx1201) kernel support matures past "experimental" (watch ROCm release notes past 7.2) — worthwhile *only* if you need much higher throughput (e.g. batch-generating many segments concurrently), which a single-user sequential-review workflow doesn't require. |
| FastAPI + SQLModel/SQLite | Node/Express or Django | Django is overkill (this app doesn't need its admin/ORM-migration machinery for ~3 tables); Node/Express would work but forces a second language boundary for no benefit — the TTS inference, ffmpeg orchestration, and EPUB parsing all want to live in Python next to `qwen-tts`/`torch` anyway. |
| React + Vite (SPA) | Next.js | Use Next.js only if you anticipate needing SSR/streaming HTML or plan to expose this beyond a private Tailscale single-user tool — neither applies here, and Next.js's server runtime adds an extra process/complexity for no real gain in this context. |
| React + TanStack Table | htmx + Alpine.js | A lightweight htmx-based UI is a legitimate alternative if you want to minimize frontend build tooling entirely — but the row-level interactivity (dropdowns bound to a dynamic character list, per-row async regenerate-and-rejoin, live status badges) is meaningfully easier to keep consistent client-side with React state than by round-tripping partial HTML swaps for every edit. |
| ffmpeg concat demuxer via subprocess | `pydub` | Use pydub only for quick prototyping/exploration in a notebook — not recommended for the production join path (unmaintained, adds overhead, no benefit over calling ffmpeg directly for a same-codec concat). |
| SSE (`fastapi.sse.EventSourceResponse`) | WebSockets | Switch to WebSockets only if you later want bidirectional real-time features (e.g. live collaborative editing, or the client cancelling/reordering the generation queue mid-stream in a chatty way) — not needed for one-way progress push to a single client. **(v1.1: instant cancellation is now a requirement — see the v1.1 Addendum; this is still solvable without WebSockets, see below.)** |

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
- Because the real `qwen-tts`/ROCm PyTorch stack can't run there, and the rest of the app (upload, LLM analysis, table editing, project persistence, ffmpeg join) has zero GPU dependency and should be fully testable without it

**If ROCm 7.2's gfx1201 support turns out to have rough edges at deploy time:**
- Fall back to `HSA_OVERRIDE_GFX_VERSION` spoofing (e.g. reporting as a nearby supported target) as a temporary workaround, the way community guides did for Strix Halo (gfx1151) before official support landed
- Because this is a known, documented escape hatch in the ROCm/PyTorch community for "GPU technically works but isn't in the officially-blessed list yet" situations — treat it as a fallback, not the default, since RX 9070 XT/gfx1201 is now officially listed as supported in ROCm 7.2

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `torch` (rocm7.2 wheel) | ROCm 7.2.x driver/userspace on host + `rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_2.10.0*` container base | Match the container's ROCm userspace version family to the host kernel driver; mismatches between container ROCm version and host driver are the most common source of "GPU not detected" issues reported in community threads. |
| `qwen-tts` pip package | `transformers` + `torch` versions it pins (check `pyproject.toml`/`requirements.txt` at install time — pin exact versions once you install, since this is a very new, fast-moving package as of early 2026) | Because `qwen-tts` had only ~7 releases since its Jan 2026 debut, expect breaking changes between minor versions; pin the exact version in the container image rather than tracking latest. **(v1.1: pinned to exactly `qwen-tts==0.1.1` / `transformers==4.57.3` / `accelerate==1.12.0` in the shipped `Containerfile.tts` — see the v1.1 Addendum for a behavior verified directly against this exact pin that would need re-checking on any version bump.)** |
| FastAPI ≥0.135 | Native `fastapi.sse.EventSourceResponse` | If pinning an older FastAPI (<0.135) for any reason, use `sse-starlette` instead — same conceptual API, mature and stable. |
| OpenRouter model slug `OPENROUTER_MODEL` | Any OpenRouter-listed model id (`x-ai/grok-4.3`, `x-ai/grok-4.5`, etc. — confirm current slugs/context windows/pricing at `openrouter.ai/x-ai` or the relevant provider page at implementation time) | `x-ai/grok-4.3` (1M context) is the default — it preserves this app's original single-shot-analysis assumption (D-06's ~50%-of-context safety margin over a full novel's text). Any other OpenRouter model that supports `response_format: json_schema` strict mode can be swapped in via the env var without a code change. |

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
- [xai-sdk-python GitHub repo](https://github.com/xai-org/xai-sdk-python) — install, `Client`/`AsyncClient`, Pydantic structured-output usage — HIGH confidence (historical — xai-sdk since superseded, see 2026-07-10 update above)
- [Structured Outputs — xAI Docs](https://docs.x.ai/developers/model-capabilities/text/structured-outputs) — `response_format`, `.parse()`, streaming limitation — HIGH confidence (historical)
- [Models — xAI Docs](https://docs.x.ai/developers/models) — current Grok model names/pricing/context windows (July 2026) — HIGH confidence (historical)
- [OpenRouter API Reference](https://openrouter.ai/docs/api-reference/overview) — chat-completions endpoint, `Authorization: Bearer` header, `response_format: json_schema` structured outputs — HIGH confidence (2026-07-10)
- [OpenRouter xAI model listing](https://openrouter.ai/x-ai) — `x-ai/grok-4.3` model slug, 1M context window — HIGH confidence (2026-07-10)
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

---

# v1.1 Addendum: Generation Control + Config Panel

**Scope:** New stack needed for (a) truly interrupting an in-flight `model.generate()` call, (b) load-on-demand swap between the 1.7B and 0.6B CustomVoice checkpoints within the 16GB VRAM budget, (c) FLAC/Opus output alongside the existing MP3 path.
**Researched:** 2026-07-13
**Confidence:** HIGH for (a) and (b) — verified by directly reading the production container's installed `qwen-tts==0.1.1` / `transformers==4.57.3` source (see below), not just docs/blogs. MEDIUM for (c) — well-established ffmpeg behavior, cross-checked across multiple sources but not run locally (no `ffmpeg` binary in this dev sandbox; verify once on the deploy VM where it already runs).

## Critical finding: `qwen-tts==0.1.1` silently drops `stopping_criteria` — plan around it, don't assume it works

Read directly from the production container image's installed wheel
(`/opt/venv/lib/python3.12/site-packages/qwen_tts/`, `rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1` base per `Containerfile.tts`):

- `Qwen3TTSModel.generate_custom_voice(**kwargs)` → `_merge_generate_kwargs(**kwargs)` → `self.model.generate(**gen_kwargs)`. This outer `generate()` (`Qwen3TTSForConditionalGeneration.generate`, `modeling_qwen3_tts.py:2022`) declares `**kwargs` in its signature but **never merges it into `talker_kwargs`** — the dict it actually forwards to the real HF generation call is hardcoded (`max_new_tokens`, `do_sample`, `top_k`, etc. only). Any extra kwarg passed through the public API (e.g. `stopping_criteria=StoppingCriteriaList(...)`) is silently swallowed. This is a bug/limitation in the pip package itself, not something you're doing wrong.
- The real per-token generation loop is `self.talker.generate(inputs_embeds=..., attention_mask=..., trailing_text_hidden=..., tts_pad_embed=..., **talker_kwargs)` at `modeling_qwen3_tts.py:2272`. `self.talker` is `Qwen3TTSTalkerForConditionalGeneration(Qwen3TTSTalkerTextPreTrainedModel, GenerationMixin)` — a genuine `transformers.GenerationMixin` subclass, so **its** `.generate()` *does* honor `stopping_criteria` exactly like any other HF causal LM.
- Consequence: the only way to get `StoppingCriteria`-based early stop working with this exact package version is to **monkeypatch the bound method on the loaded model instance** — wrap `model.model.talker.generate` (the inner talker, not the outer `Qwen3TTSModel` wrapper) so it injects `stopping_criteria=<your list>` into every call before delegating to the original. This is a small, self-contained ~10-line patch applied once at model-load time in `tts_service/model.py`; it does not require forking the package and survives package upgrades as long as `self.talker.generate(**talker_kwargs)`'s call shape doesn't change (pin `qwen-tts==0.1.1` exactly, as the project already does — re-verify this patch on any version bump).
- Also verified in the same file: `if self.model.tts_model_size in "0b6": instruct = None` (`qwen3_tts_model.py:799`) — **the 0.6B CustomVoice checkpoint silently disables free-text `instruct` voice steering entirely**, regardless of what the caller passes. This is a real UX regression when a user switches down to 0.6B: every segment's "Voice Instructions" text will simply have no effect. Surface this in the Config Panel (e.g. a warning next to the 0.6B option) — don't let it fail silently in the UI too.

## Recommended Stack

### (a) Immediate cancellation of an in-flight generate() call

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `transformers.StoppingCriteria` / `StoppingCriteriaList` | pinned `transformers==4.57.3` (already pinned in `Containerfile.tts`) | Check a cancel flag between autoregressive steps of the talker's HF `generate()` loop | `StoppingCriteria.__call__(input_ids, scores)` runs once per generated token/frame, not once per whole call — for a several-hundred-frame segment this bounds worst-case cancel latency to roughly one forward pass (tens of ms), which is what "immediately cancellable" actually requires. It's the only mechanism that can interrupt *inside* `model.generate()` without killing the process (and thus the resident model) |
| A bound-method monkeypatch on `model.model.talker.generate` in `backend/tts_service/model.py` | project code, no new dependency | Bridge the outer `qwen-tts` wrapper's dropped `**kwargs` to the inner real `GenerationMixin.generate()` that does honor `stopping_criteria` | Verified necessary above — passing `stopping_criteria=` through the public `generate_custom_voice()` API is silently a no-op with this package version |
| `threading.Event` (stdlib) | — | The actual cancel flag the custom `StoppingCriteria` checks each call | One global event is enough — the app already enforces a single global generation slot (`generation_worker.try_claim_generation`), so only one synth call is ever in flight at a time. No per-request id, no asyncio primitives needed inside `tts_service` (the synth call runs in a plain thread via `run_in_threadpool`, so a plain `threading.Event`, not `asyncio.Event`, is what the worker thread can actually see and clear cheaply) |
| A `POST /cancel` route added to `tts_service/server.py` | — | Lets the main backend's existing `/generate/cancel` reach across the HTTP boundary and flip the flag | The TTS container is a *separate* process/pod from the main backend (`Containerfile.tts` vs `Containerfile.backend`, talking over `TTS_SERVICE_URL`/httpx — confirmed in `app/tts_client.py`). The main backend's current cancel path (`app/main.py::cancel_generation`) only stops the *next* segment from starting; it cannot reach into the TTS container's in-flight thread at all today. This route is the missing link — reset the event to "not cancelled" at the start of every `/synthesize` call, set it on `/cancel`, and have the injected `StoppingCriteria` return `True` once set |

**What NOT to do for (a):**
- Don't reach for `asyncio.Task.cancel()` on the FastAPI side as the actual interrupt mechanism — it only ever cancels the *waiting*, not the blocking synchronous call already running in a threadpool worker thread on the other side of an HTTP call. This is exactly the limitation the existing `# ponytail:` comment in `app/main.py::cancel_generation` already documents; the fix has to live in `tts_service`, not in the main backend.
- Don't spawn a subprocess per synth call to get "real" killability. Because the model must stay resident to avoid the 1-2 minute reload cost (documented anti-pattern already called out at the top of `tts_service/model.py`), a fresh subprocess per call would mean reloading the model every time — that's strictly worse than the current architecture, not an upgrade.
- Don't add a task queue (Celery/RQ/etc.) for this. Single GPU, single user, one generation slot already enforced in-process — a queue adds infra (a broker) to solve a problem a `threading.Event` already solves.

### (b) Loading/unloading between the two model sizes without leaking VRAM

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | HF repo, same family as the currently-pinned 1.7B checkpoint | The second model size the milestone wants selectable | Confirmed to exist on the Hub (Apache-2.0, `QwenLM/Qwen3-TTS`) and to load through the exact same `Qwen3TTSModel.from_pretrained(...)` / `generate_custom_voice(...)` call shape as the 1.7B model already in `tts_service/model.py` — no new wrapper code needed, just a different `MODEL_NAME` |
| `del <old model/processor refs>; gc.collect(); torch.cuda.empty_cache()` (stdlib `gc` + `torch.cuda`, no new dependency) | — | Release the previously-loaded checkpoint's VRAM before loading the other one | This is the standard, well-documented PyTorch pattern (PyTorch forums, HF forums) for releasing a caching-allocator's held blocks back to the driver. `torch.cuda.*` calls transparently map to HIP on a ROCm PyTorch build (same public API, same semantics) — no ROCm-specific replacement API exists or is needed |
| A module-level `threading.Lock` around "swap model" + "synthesize" in `tts_service/model.py` | stdlib | Serialize model-swap against an in-flight synth call | The module currently holds `model` as a bare global reassigned at import time only; once it becomes swappable at runtime, a synth call reading `model` mid-swap (or a swap starting mid-synth) would segfault/produce garbage. Reuse the same single-flight discipline the main backend already has (`generation_worker.try_claim_generation`) — extend "swap model" to also require the global generation slot, so a model switch can never race a synth call |

**Concrete swap sequence** (what actually needs to happen in `tts_service/model.py`, informed by the module's current structure — it loads the model once at import time as a bare global):

1. Acquire the lock.
2. `del model` (drop the last reference to the `Qwen3TTSModel` wrapper — its inner `.model` holds the actual `nn.Module` weights).
3. `gc.collect()` then `torch.cuda.empty_cache()` — frees the caching allocator's now-unused blocks back to the driver.
4. `Qwen3TTSModel.from_pretrained(NEW_MODEL_NAME, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")` — identical kwargs to the existing load, just a different repo id.
5. Re-apply the `StoppingCriteria` monkeypatch from (a) to the freshly-loaded instance's `model.talker.generate` (it's a fresh object each load, the patch doesn't persist across `from_pretrained`).
6. Re-derive `DEFAULT_SPEAKER` from the new model's `get_supported_speakers()` — the 0.6B and 1.7B checkpoints are not guaranteed to expose an identical speaker list.
7. Release the lock.

**Known limitation to document, not solve:** `torch.cuda.empty_cache()` returns *unused cached* memory to the driver; it does not guarantee every byte is reclaimed if something still holds a stray reference (a common complaint on the PyTorch/HF forums). Practical mitigation: keep the reload sequence tight (no partial-init state held across the `del`/reload boundary) and, if VRAM ever visibly fails to fully release across repeated swaps in practice, add a `torch.cuda.memory_allocated()` / `memory_reserved()` log line around the swap so it's observable rather than guessed at — don't pre-build a leak-detection system for a problem not yet confirmed to occur (1.7B bf16 ≈ 3.4GB weights, 0.6B bf16 ≈ 1.2GB, both individually far under the 16GB budget with generous headroom, so a small amount of unreclaimed cache is very unlikely to matter here).

**What NOT to do for (b):**
- Don't keep both models resident simultaneously "for speed" — the milestone explicitly wants only one loaded at a time, and both models comfortably fit the 16GB budget individually so there's no forced tradeoff being made here, just the stated product requirement.
- Don't build a generic "model registry" abstraction for two hardcoded model ids. A `MODEL_CHOICES = {"1.7b": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice", "0.6b": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"}` dict plus the swap function above is the whole feature — add a real registry only if a third size ever ships.

### (c) FLAC and Opus output alongside the existing MP3 path

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| ffmpeg native `flac` encoder (`-c:a flac`) | whatever ffmpeg build already runs on the deploy VM (`audio_join.py` already shells out to system `ffmpeg`) | Lossless output format option | Built into every standard ffmpeg build (not an external lib like `libopus`/`libmp3lame`) — no new package to install in `Containerfile.backend` |
| `libopus` (`-c:a libopus`) | same ffmpeg build | Opus output format option | The de facto standard lossy codec for speech at low bitrate; standard ffmpeg builds bundle it (already true for `libmp3lame`, which the project depends on today, so the build almost certainly has `libopus` too — confirm with `ffmpeg -encoders \| grep opus` on the deploy VM before shipping, since this dev sandbox has no `ffmpeg` binary to check directly) |

**Recommended flags**, extending `audio_join.py`'s existing `codec_args` branch (currently `["-c", "copy"]` for wav / `["-c:a", "libmp3lame"]` for mp3):

```python
codec_args = {
    "flac": ["-c:a", "flac", "-compression_level", "8"],
    "opus": ["-c:a", "libopus", "-b:a", "48k", "-vbr", "on", "-application", "voip"],
    "mp3": ["-c:a", "libmp3lame"],  # unchanged
}[fmt]
```

- **FLAC** is lossless — no bitrate flag. `-compression_level` (0-12, ffmpeg's native flac encoder) trades encode time for file size only; `8` is a reasonable "small enough, still fast" default. Since this is a one-shot offline batch join (not real-time), `12` (max) is also safe if smaller files matter more than shaving a few seconds off the join step — not worth exposing as a user-facing setting for a single-user tool.
- **Opus**: `-application voip` switches libopus's internal mode toward speech intelligibility (SILK-leaning) rather than general audio fidelity — the right choice for narrated text, not music. `48k` mono/typical narration bitrate lands in the range multiple sources describe as "essentially indistinguishable from higher bitrates" for spoken word; `-vbr on` (already the libopus default) lets the encoder spend fewer bits on silence between segments.
- **Force the muxer explicitly, don't rely on the output filename's extension.** This milestone also adds a *user-editable output filename* — if a user types `"my_book"` (no extension) or `"my_book.mp3"` while FLAC is selected, ffmpeg's extension-sniffed muxer choice would silently produce the wrong container or fail outright. Add `-f flac` / `-f opus` / `-f mp3` explicitly to the ffmpeg invocation (matching the `fmt` param, independent of whatever `out_path`'s suffix is) so codec selection and container selection can never disagree with each other or with a user-supplied filename. Have the backend still append the canonical extension itself when building `out_path` from the user's filename — don't trust the client to get the extension right, but also don't depend on it being right.
- No changes needed to `audio_join.py`'s concat-demuxer/subprocess-argument-list approach (T-01-03's no-shell discipline) — this is purely a bigger `codec_args` lookup table plus the explicit `-f` flag, not a different join strategy.

**What NOT to do for (c):**
- Don't use ffmpeg's native experimental `opus` encoder (`-c:a opus`, no `lib` prefix) — it exists but is generally considered lower quality / less mature than `libopus` for the same bitrate; always prefer `libopus` explicitly.
- Don't drop WAV support from `audio_join.py`'s function signature/tests just because the milestone drops it from the *product's* selectable formats — leave the `"wav"` branch alone unless a later cleanup pass explicitly wants it gone; this milestone's actual requirement is adding FLAC/Opus and dropping WAV *from the UI*, not necessarily scrubbing every WAV code path.

## Alternatives Considered (v1.1)

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| Monkeypatched `StoppingCriteria` for (a) | Kill/restart the whole `tts_service` process (container) on cancel | Only if the monkeypatch route turns out to be fragile against a future `qwen-tts` upgrade — but a full process restart re-pays the 1-2 minute model load on every single cancel, which fails the "immediately usable again" half of the UX goal just as badly as not cancelling at all |
| Monkeypatched `StoppingCriteria` for (a) | Fork `qwen-tts` and patch `Qwen3TTSForConditionalGeneration.generate()` upstream in a vendored copy | Only worth it if the project needs other changes to the generation loop too — for cancellation alone, patching one bound method at load time is a far smaller footprint than vendoring and maintaining a fork |
| `del` + `gc.collect()` + `torch.cuda.empty_cache()` for (b) | `subprocess`-per-model-size, always running both as separate long-lived processes and routing by which is "warm" | Only makes sense if VRAM had headroom for both simultaneously (it does here) *and* switch latency needed to be near-zero — the milestone explicitly wants only one resident at a time, so this doesn't apply |
| `libopus` for (c) | AAC (`libfdk_aac` / native `aac`) | Not requested by this milestone (FLAC/MP3/Opus only) and typically not bundled as GPL-free in default ffmpeg builds the way libopus is — skip unless a future requirement asks for it |

## What NOT to Use (v1.1)

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| Celery / RQ / any task queue for cancellation or model-swap orchestration | Single GPU, single user, already-enforced single-flight generation slot in-process — a queue adds a broker dependency to solve a problem `threading.Event` + an existing lock already solve | The existing `generation_worker.try_claim_generation` pattern, extended with a `threading.Event`-based cancel flag |
| `pydub` for FLAC/Opus encoding | Already excluded project-wide per `CLAUDE.md` (unmaintained; project calls ffmpeg directly) | Extend `audio_join.py`'s existing `subprocess.run([...ffmpeg args...])` codec table |
| ffmpeg's native `opus` encoder (no `lib` prefix) | Lower quality/maturity than `libopus` at equivalent settings | `-c:a libopus` |

## Version Compatibility (v1.1)

| Package | Compatible With | Notes |
|---------|------------------|-------|
| `qwen-tts==0.1.1` | `transformers==4.57.3`, `accelerate==1.12.0` (exact pins already in `Containerfile.tts`) | The `stopping_criteria` monkeypatch's correctness depends on the exact call shape at `modeling_qwen3_tts.py:2272` (`self.talker.generate(inputs_embeds=..., attention_mask=..., trailing_text_hidden=..., tts_pad_embed=..., **talker_kwargs)`) — re-verify this line by re-reading the installed wheel before bumping `qwen-tts`'s version pin |
| `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | Same `qwen_tts.Qwen3TTSModel.from_pretrained()` / `generate_custom_voice()` call shape as the 1.7B checkpoint already in use | No `qwen-tts` package changes needed to add the second model — only a second `MODEL_NAME` constant and the swap logic in (b) |
| ffmpeg `libopus` | Standard ffmpeg builds (already relying on `libmp3lame` being present) | Confirm on the deploy VM with `ffmpeg -encoders \| grep -E "opus\|flac"` before shipping — this research could not run `ffmpeg` locally (no binary in the dev sandbox) |

## Sources (v1.1)

- Direct inspection of the production container's installed `qwen-tts==0.1.1` source (`/opt/venv/lib/python3.12/site-packages/qwen_tts/inference/qwen3_tts_model.py`, `qwen_tts/core/models/modeling_qwen3_tts.py`) — HIGH confidence, primary source (the actual code that runs in production), not a claim from documentation or search
- `backend/tts_service/model.py`, `backend/tts_service/server.py`, `backend/app/tts_client.py`, `backend/app/main.py`, `backend/Containerfile.tts` (this repo) — confirms the existing two-process/two-container architecture, the existing best-effort cancel's documented limitation, and the exact pinned versions
- WebSearch: "cancel interrupt Hugging Face transformers model.generate() ... StoppingCriteria" — LOW confidence per `classify-confidence` (unverified web), but consistent with and confirmed by the direct source read above
- WebSearch: "PyTorch del model torch.cuda.empty_cache gc.collect free GPU memory swap models VRAM leak" — LOW confidence, standard/well-known pattern, cross-checked across PyTorch Forums + HF Forums + GeeksforGeeks
- WebSearch: "ffmpeg libopus flac encoder recommended bitrate voice spoken word audiobook" and "ffmpeg -c:a libopus ... -application voip ... flac ffmpeg example command" — LOW confidence per `classify-confidence` (unverified web, and this sandbox has no `ffmpeg` binary to directly confirm flag names); cross-checked across ffmpeg's own codecs documentation description plus two independent Opus bitrate guides — verify flag names once against `ffmpeg -h encoder=libopus` / `encoder=flac` on the deploy VM before merging
- `https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` — confirms the second checkpoint's existence and Hub repo id

---
*v1.1 addendum researched: 2026-07-13*
