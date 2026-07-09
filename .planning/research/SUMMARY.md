# Project Research Summary

**Project:** Qwen Ebook Narrator
**Domain:** Self-hosted ebook-to-audiobook narration web app (LLM text analysis + local multi-voice TTS + spreadsheet-style review UI)
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH

## Executive Summary

This is a personal, single-user tool that sits in a well-established (if niche) domain: LLM-driven cast detection + per-segment voice assignment + multi-voice TTS + audio join, matched closely by real open-source projects (VoxNovel, TTS-Story, audiobook-creator) and commercial tools (ElevenLabs, Play.ht). The research strongly validates the app's existing design: a FastAPI + SQLite/filesystem backend, a React/Vite + TanStack Table spreadsheet-style editable UI, xAI Grok for structured cast/segment extraction, and self-hosted Qwen3-TTS-1.7B-CustomVoice for synthesis. The single most load-bearing architectural decision, confirmed independently by both Features and Architecture research, is per-segment status plus content-hash tracking: persisting individual segment audio files keyed by a hash of (character, voice instructions, text, model/voice version), with Segment.status doubling as the job queue. This one data-model choice simultaneously satisfies "regenerate only the edited row," "resume an interrupted generation run," and "cheap rejoin" and should be designed in from day one, not retrofitted.

The recommended approach: run TTS as a separate, GPU-scoped Podman container behind a plain HTTP endpoint (never in-process with the web backend), keep GPU concurrency at 1 (single 16GB card, no meaningful parallel throughput gain), use a single in-process asyncio worker against a SQLite-backed queue (no Redis/Celery, total overkill at this scale), and chunk long-novel LLM analysis on structural boundaries (chapter/paragraph, not raw token counts) while always re-supplying the running cast list as context to prevent duplicate/renamed characters across chunks. Frontend and the TTS-on-ROCm spike can be built in parallel tracks from day one since neither blocks the other, and the GPU spike carries the most environment-specific risk in the whole project.

The key risks are concentrated in two areas: (1) ROCm/RDNA4 hardware risk, since RX 9070 XT (gfx1201) support is very new (ROCm 7.2, March 2026), community reports show model-variant-specific silent failures (voice-cloning "Base" checkpoints hang/produce nothing on AMD; the CustomVoice variant this app needs is reported working), and Podman GPU passthrough has several independently-required pieces (device flags, group membership, SELinux booleans) that are individually easy to get right and collectively easy to miss in a real deployment vs. an ad hoc test; and (2) multi-call TTS/LLM consistency risk, since voice timbre can drift across independently-generated segments for the same character (mitigated by a fixed seed plus byte-identical voice instructions per character, stored in the data model), and LLM cast detection on long novels will produce duplicate/renamed characters across chunks unless the resolved cast list is explicitly re-supplied as context on every chunk (mitigated by the cast merge/rename wizard already scoped as a requirement). Both risk areas should be de-risked early via smoke tests before the rest of the pipeline is built around them.

## Key Findings

### Recommended Stack

The stack cleanly splits into a GPU-free web/orchestration layer and a GPU-scoped inference microservice. Backend: FastAPI (native SSE for live progress, Pydantic schemas shared across Grok structured output / DB models / API responses) plus SQLModel/SQLite (single projects.db, audio referenced by filesystem path, never blob-stored) plus ebooklib/BeautifulSoup/lxml for EPUB parsing (defensive recover=True parsing, real-world EPUBs are often malformed) plus ffmpeg via subprocess (concat demuxer for joining same-codec segments). Frontend: React 19 + Vite + TanStack Table v8 + shadcn/ui + Tailwind v4, a client-rendered SPA fits this interactive, stateful editor with no SEO/SSR need. TTS: Qwen3-TTS-12Hz-1.7B-CustomVoice (Apache 2.0, HF Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) run via plain HF Transformers (qwen-tts pip package, attn_implementation="sdpa") on PyTorch ROCm 7.2, explicitly avoiding vLLM/vLLM-Omni (RDNA4 kernel support still experimental, FP8 silently falls back to FP32) and flash-attn (CUDA-only). LLM: xai-sdk against grok-4.3 (1M context, cheaper than 4.5, sufficient for cast/segment structured extraction). Deployment: Podman + Quadlets (systemd-managed units), not ad hoc podman-compose, for a persistent self-hosted service.

**Core technologies:**
- Qwen3-TTS-12Hz-1.7B-CustomVoice: self-hosted multi-voice TTS, preset + free-text instruction steering matches the app's exact voice-assignment design, confirmed working on AMD/ROCm (unlike the Base/voice-cloning variant)
- FastAPI + SQLModel + SQLite: backend orchestration + persistence, async, native SSE, one dependency for both ORM and shared Pydantic schemas
- React 19 + Vite + TanStack Table + shadcn/ui: spreadsheet-style editable table UI, headless table engine is the standard for custom editable data grids, no heavier/paid grid library needed
- xai-sdk + Grok structured outputs: schema-guaranteed JSON for cast detection and segmentation, avoids manual JSON-parsing fragility
- ffmpeg (subprocess, concat demuxer): reliable, fast segment joining, avoid pydub (unmaintained, adds overhead)
- Podman + Quadlets, GPU device flags scoped only to the TTS container: matches the project's Podman constraint and the "TTS as isolated GPU service" architecture pattern

### Expected Features

The domain has a clear, consistent shape across every competitor surveyed (VoxNovel, TTS-Story, audiobook-creator, ElevenLabs, Play.ht): LLM cast detection, segmentation, human review/correction, per-character voice assignment, batch generation with progress, join. This project's Active requirements in PROJECT.md already match the correct table-stakes set; research adds confidence, not new scope, plus flags one architecturally load-bearing pattern (content-hash caching) that isn't clearly documented anywhere in the competitor set but is essential for this app's stated "regenerate only the edited row" requirement.

**Must have (table stakes):**
- .txt/.epub upload, LLM cast detection with age/gender/personality inference (chunked, with cross-chunk continuity for long texts)
- LLM segmentation into narration/dialogue with suggested speaker + voice instructions per row
- Cast review/merge wizard before segment generation, every competitor with this step exists specifically because misattribution is common; competitors without it (audiobook-creator) cite it as a known gap
- Editable segment table, per-row TTS generation, content-hash-based caching so edits only regenerate the changed row, ordered audio concatenation, project save/reopen, progress indicator

**Should have (competitive differentiators, already implicit in this project's design):**
- Unified single-table editing (Narrator + Voice Instructions + Text in one grid) vs. competitors' split wizard/hidden-text approaches
- Free-text voice instructions blended with presets (avoids needing large voice libraries or cloning)
- Segment-level content-hash caching (more rigorous than competitors' undocumented "regenerate this line" features)
- Fully local/self-hosted TTS with zero per-request cost, Tailscale-only exposure, a genuine differentiator vs. every commercial competitor's metered cloud model

**Defer (v2+):**
- Voice preview and bulk row reassignment (P2, add once the core loop is validated, cheap to add later)
- Cost/usage visibility for LLM spend (P2, nice-to-have)
- Chapter markers/M4B export, voice cloning from personal recordings, PDF input, all explicitly already Out of Scope in PROJECT.md; research confirms these are correctly deferred, not gaps

### Architecture Approach

A clean two-container split: a thin, GPU-free FastAPI backend (project CRUD, EPUB parsing, Grok orchestration, job queue, ffmpeg joining) talking over the internal Podman network to a separate, GPU-scoped TTS microservice (Qwen TTS resident in VRAM, single synchronous HTTP endpoint, concurrency capped at 1). The job queue is not a separate system; Segment.status (pending, queued, generating, complete, error, stale) IS the queue, consumed by one in-process asyncio worker, durable across restarts (resume generating to queued on startup) with zero extra infrastructure (no Redis/Celery). "Regenerate one segment" and "generate all" are the same code path, enqueue N segment IDs vs. one. Persistence is SQLite for structured state plus filesystem for text/audio blobs, one directory per project, bind-mounted outside both container images so project data survives rebuilds.

**Major components:**
1. Frontend SPA (React), editable segment table + cast wizard + config sidebar + live progress (poll first, SSE if needed)
2. Backend/Orchestrator (FastAPI, GPU-free), upload/parsing, Grok analysis client with chunk+reconcile logic, job queue worker, ffmpeg joiner, all project/character/segment persistence
3. TTS Inference Service (separate Podman container, ROCm, GPU device flags scoped only here), loads Qwen TTS once, exposes one synthesis endpoint, concurrency=1
4. Persistence layer, SQLite (metadata/state) + filesystem (source text, per-segment audio, final joined output), never audio blobs in the DB

### Critical Pitfalls

1. Podman/ROCm GPU passthrough works in an ad hoc test but silently fails in the real deployed container/Quadlet: device flags (/dev/kfd, /dev/dri), --group-add keep-groups, and the SELinux container_use_devices boolean must all be baked into the actual deployment unit from day one and verified from inside the real deployed container, not just a manual podman run test.
2. Qwen TTS ROCm compatibility is not uniform across model variants: the Base/voice-cloning checkpoint has reported silent failures on consumer AMD GPUs; pin and smoke-test the exact CustomVoice checkpoint on the actual RX 9070 XT (real audio bytes out, not just GPU utilization) before building the review UI around it.
3. Voice timbre drift across independently-generated segments for the same character: mitigate by storing a fixed per-character seed and byte-identical voice-instruction text in the data model from the start (not per-row re-derivation); QA this across a full long book, not just short preview clips.
4. LLM re-identifies the same character under different names across chunks of a long novel: always re-supply the resolved cast list as context on every subsequent chunk; treat the already-planned cast merge/rename wizard as the essential second line of defense, not optional polish.
5. Per-segment persistence is required, not optional, from day one: a whole-job-in-memory generation loop with no per-segment state loses all progress on any single failure and directly blocks the "regenerate one row" requirement; design the status/audio-path persistence model once, serving both resumability and single-row regeneration.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Foundation, Ingestion & Frontend Shell
**Rationale:** Data model (Project/Character/Segment) is the foundation everything else depends on. File upload/parsing has no GPU or LLM dependency and is fully testable standalone. The frontend table/sidebar shell can be built against fixture/mocked data as soon as the API contract is defined, decoupling UI iteration from the riskiest backend pieces.
**Delivers:** Project CRUD API, SQLite schema, .txt/.epub upload + parsing to plain text/chapters, frontend table + sidebar shell rendering mock segment/character data.
**Addresses:** Ebook/text upload (table stakes), project persistence scaffold.
**Avoids:** Building UI atop unstable backend APIs; nothing GPU-dependent yet so no ROCm risk introduced here.

### Phase 2: TTS Service Spike (parallel track, start early)
**Rationale:** This is the highest-risk, most environment-specific component (newest-generation consumer GPU + ROCm 7.2 + Podman rootless device passthrough all stacked) and nothing else in the pipeline strictly blocks on it, de-risk it in parallel with Phase 1/3 rather than discovering GPU issues late.
**Delivers:** Standalone ROCm container serving Qwen3-TTS-1.7B-CustomVoice via a minimal HTTP endpoint; confirmed real audio bytes out on the actual RX 9070 XT; GPU passthrough verified from inside the real deployed container (not just an ad hoc test); a mock TTS backend (TTS_BACKEND=mock) wired in for GPU-less local dev.
**Avoids:** Pitfall 1 (GPU passthrough silently failing in real deployment), Pitfall 2 (model-variant-specific silent ROCm failures).

### Phase 3: LLM Analysis Pipeline
**Rationale:** Depends only on Phase 1's data model and parsing; fully testable independently of TTS. Produces the real Character/Segment data the frontend needs to move off fixtures. Chunking strategy and cast continuity must be designed in from the start, retrofitting cross-chunk reconciliation after the fact is expensive.
**Delivers:** xAI Grok integration with structured-output cast detection + segmentation; chapter/paragraph-aware chunking with running cast-list context passed to every chunk; reconciliation pass; cast review/merge wizard wired to real analysis output.
**Addresses:** LLM cast detection with inferred traits, text segmentation with suggested speaker/voice instructions, cast review step (all table-stakes P1 features).
**Avoids:** Pitfall 4 (cross-chunk character duplication), Pitfall 5 (mid-scene chunk splits breaking speaker attribution).

### Phase 4: Generation Pipeline (Queue, TTS Integration, Joining, Regeneration)
**Rationale:** Depends on Phase 2 (TTS service exists) and Phase 3 (segments exist to generate). This is where the data-model decision from Features/Architecture research (content-hash caching, segment status as queue) becomes real, build it as one queue-a-segment primitive from the start so "generate all" and "regenerate this row" are the same code path, not two.
**Delivers:** Single async worker consuming the SQLite-backed segment queue; per-segment status persistence (pending/queued/generating/complete/error/stale) with resume-on-restart; TTS client HTTP integration with per-segment timeout; ffmpeg concat joining (validated specifically against the "edit row 50 of 200, rejoin" scenario, not just a fresh uniform batch); regenerate-single-segment wired to the same primitive.
**Uses:** Qwen3-TTS-1.7B-CustomVoice, FastAPI async worker, ffmpeg concat demuxer, SQLModel/SQLite.
**Implements:** Job Queue component, Audio Joiner component, TTS Client boundary.
**Avoids:** Pitfall 3 (voice drift, fixed seed per character built into this phase's data model), Pitfall 6 (audio join clicks/format mismatch), Pitfall 7 (no resumable/partial-failure model).

### Phase 5: Progress UI, Deployment & Polish
**Rationale:** Live progress and Podman/Tailscale deployment are the final integration layer; deployment scaffolding (Quadlets, GPU device scoping) can be sketched earlier but final validation belongs after the pipeline works locally end-to-end.
**Delivers:** Per-row status badges + aggregate progress (polling first, SSE upgrade if polling proves too chatty), Podman Quadlet units with GPU device flags scoped only to the TTS container, Tailscale-served deployment, disk-space/VM sizing validated against the actual ROCm image + model weights + a full generated project.
**Addresses:** Live conversion progress panel (already scoped requirement).
**Avoids:** Pitfall 8 (ROCm image bloat/disk exhaustion, validate VM storage headroom here), UX pitfalls around opaque progress and unfed rejoin feedback.

### Phase Ordering Rationale

- Data model comes first because every other component (parsing output, LLM output, TTS job state, joining) writes into it, Features research explicitly identifies content-hash/per-segment-audio persistence as "the single most load-bearing architectural decision," so it must be correct before anything else is built on top.
- The TTS/ROCm spike is pulled forward into its own early, parallel phase specifically because Architecture and Pitfalls research both independently flag it as the highest-risk, most environment-specific piece of the whole project, waiting until "generation pipeline" phase to discover GPU passthrough or model-variant issues would be expensive to unwind.
- LLM analysis is sequenced before the generation pipeline because segments must exist before they can be queued for TTS, but it does not depend on the TTS spike being complete, hence the parallel-track structure in the build order.
- Generation pipeline (queue + TTS integration + joining + regeneration) is deliberately one phase, not split, because Pitfalls research shows these are the same data model serving two needs (resumability and single-row regeneration), splitting them risks retrofitting one onto the other.
- Deployment/progress UI is last because it's the integration/validation layer over an already-working local pipeline, though its scaffolding (Quadlet skeletons) can be drafted incrementally alongside earlier phases per Architecture's suggested build order.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (TTS Service Spike):** ROCm 7.2/RDNA4 (gfx1201) support is very recent and fast-moving; qwen-tts package is under 6 months old with frequent breaking changes; exact decode_window_frames/inference-param defaults that avoid the known ROCm slowdown bug are not clearly documented, needs research-phase to pin exact working versions/params at implementation time.
- **Phase 3 (LLM Analysis Pipeline):** Cross-chunk character reconciliation strategy is a synthesized recommendation (MEDIUM confidence, general long-context/RAG pattern applied by analogy), not a directly-sourced, novel-specific benchmark, worth validating chunk-size/context-window assumptions against Grok's actual current limits and real book lengths before committing to a chunking approach.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Foundation, Ingestion & Frontend Shell):** FastAPI/SQLModel/EPUB parsing/React+TanStack Table are all HIGH-confidence, well-documented, standard patterns with official docs and working examples.
- **Phase 4 (Generation Pipeline):** Job-queue-as-status-column, ffmpeg concat demuxer, and the TTS-as-microservice pattern are all corroborated by multiple real reference implementations (Qwen3-TTS-Openai-Fastapi-Rocm, TTS-Story), standard, low-research-risk implementation.
- **Phase 5 (Deployment):** Podman GPU passthrough flags are documented in official Red Hat/AMD docs; the main risk is execution discipline (baking flags into Quadlets), not unknown patterns.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | HIGH on web framework/EPUB/xAI API choices (official docs, mature ecosystem); MEDIUM on Qwen TTS + ROCm 7.2/RDNA4 specifics since the model (qwen-tts package) and official gfx1201 support are both very recent (early-to-mid 2026) |
| Features | MEDIUM-HIGH | Grounded in multiple real open-source competitor projects (VoxNovel, TTS-Story, audiobook-creator) plus commercial tools; the content-hash caching pattern is a synthesized recommendation (not directly documented by any competitor) rather than sourced fact |
| Architecture | MEDIUM-HIGH | Grounded in real open-source projects of near-identical shape plus official Podman/ROCm docs; specific numeric tuning values (concurrency limits, timeouts) are LOW confidence and should be validated during implementation |
| Pitfalls | MEDIUM-HIGH | ROCm/Podman and audio-joining findings verified against official docs and GitHub issues (HIGH); Qwen3-TTS-specific quirks drawn from GitHub issues/community write-ups (MEDIUM, fast-moving project); LLM cross-chunk consistency findings are MEDIUM (general structured-output/long-context research applied by analogy, not novel-specific benchmarks) |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- Qwen3-TTS's exact hard input-length ceiling per synthesis call is not clearly documented (LOW confidence), validate empirically against the deployed model/checkpoint during Phase 2/4; defensively cap and sentence-split oversized segments until confirmed.
- Safe/default inference parameters (e.g. decode_window_frames) that avoid the known ROCm CUDA-graph-capture slowdown bug are not pinned down, benchmark per-segment generation time early in Phase 2 and treat a 5-10x regression as a red flag requiring param investigation, not "just slow hardware."
- Cross-chunk character reconciliation strategy (Phase 3) is a synthesized best-practice, not directly sourced for this domain, validate against real book-length test cases and confirm whether Grok's actual current context window makes heavy chunking unnecessary for most novels before over-building the chunking machinery.
- CDI-based GPU passthrough (--device amd.com/gpu=...) vs. classic --device /dev/kfd --device /dev/dri flags: CDI exists but wasn't confirmed as more mature for this specific hardware; default to the classic flag pattern (HIGH confidence, official docs) and revisit CDI only if it proves necessary.
- qwen-tts pip package is new (about 7 releases since Jan 2026 debut) and likely to have breaking changes between minor versions, pin an exact version in the container image during Phase 2 rather than tracking latest, and re-verify compatibility before any dependency bump.

## Sources

### Primary (HIGH confidence)
- QwenLM/Qwen3-TTS GitHub repo (https://github.com/QwenLM/Qwen3-TTS) — model variants, install, usage
- Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice on Hugging Face (https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) — voice presets, instruct-steering, license
- ROCm compatibility matrix, AMD official docs (https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) — ROCm 7.2 RDNA4/gfx1201 official support
- How to configure AMD GPU for using in Podman containers on RHEL9, Red Hat (https://access.redhat.com/solutions/7073764) — GPU passthrough flags/groups
- FastAPI Server-Sent Events docs (https://fastapi.tiangolo.com/tutorial/server-sent-events/) and release notes (https://fastapi.tiangolo.com/release-notes/)
- xai-sdk-python GitHub repo (https://github.com/xai-org/xai-sdk-python) and xAI Structured Outputs docs (https://docs.x.ai/developers/model-capabilities/text/structured-outputs)
- ebooklib GitHub repo (https://github.com/aerkalov/ebooklib), SQLModel + FastAPI tutorial (https://sqlmodel.tiangolo.com/tutorial/fastapi/)
- TanStack Table Editable Data example (https://tanstack.com/table/latest/docs/framework/react/examples/editable-data), shadcn/ui Data Table docs (https://ui.shadcn.com/docs/components/radix/data-table)
- OpenAI TTS 4096-char limit (https://community.openai.com/t/tts-with-more-than-4096-characters/591842), Google Cloud TTS quotas (https://cloud.google.com/text-to-speech/quotas)

### Secondary (MEDIUM confidence)
- Running Qwen TTS on AMD Strix Halo, tinycomputers.io (https://tinycomputers.io/posts/qwen-tts-on-amd-strix-halo.html) — concrete ROCm setup working end-to-end
- Qwen3-TTS-12Hz-0.6B-Base not generating with AMD on Linux, Issue #93 (https://github.com/QwenLM/Qwen3-TTS/issues/93), AMD ROCm Voice Cloning Discussion #308 (https://github.com/QwenLM/Qwen3-TTS/discussions/308) — model-variant ROCm silent failure reports
- GitHub antonsokolskyy/Qwen3-TTS-Openai-Fastapi-Rocm (https://github.com/antonsokolskyy/Qwen3-TTS-Openai-Fastapi-Rocm), Xerophayze/TTS-Story (https://github.com/Xerophayze/TTS-Story) — real-world reference implementations of this exact architecture
- DrewThomasson/VoxNovel (https://github.com/DrewThomasson/VoxNovel), prakharsr/audiobook-creator (https://github.com/prakharsr/audiobook-creator) — competitor feature analysis
- Inconsistent speaking rate, Qwen3-TTS Issue #239 (https://github.com/QwenLM/Qwen3-TTS/issues/239) — voice drift/speaking-rate documentation
- ROCm/TheRock Issue #3077 (https://github.com/ROCm/TheRock/issues/3077) — decode_window_frames ROCm slowdown bug
- ROCm-docker Issues #120 (https://github.com/ROCm/ROCm-docker/issues/120) / #92 (https://github.com/ROCm/ROCm-docker/issues/92) — image size/inode exhaustion

### Tertiary (LOW confidence, needs validation)
- Qwen3-TTS exact max input length per call, not found in official docs, only inferred from long-form-capability claims (medium.com writeup)
- General RAG chunking-strategy sources applied by analogy to novel character-extraction (Weaviate, Firecrawl blogs), not domain-specific benchmarks
- CDI (amd.com/gpu=) GPU passthrough maturity vs. classic device flags, confirmed to exist, not verified as more mature for this hardware

---
*Research completed: 2026-07-09*
*Ready for roadmap: yes*
