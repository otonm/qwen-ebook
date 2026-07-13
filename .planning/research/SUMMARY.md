# Project Research Summary

**Project:** Qwen Ebook Narrator — v1.1 milestone (Generation UX & Config Rework)
**Domain:** Self-hosted ebook-to-audiobook narration web app; v1.1 scope is generation-control UX (immediate cancel, unified generate/stop/play button) plus a config panel rework (dual TTS model swap, FLAC/Opus output, editable filename/download)
**Researched:** 2026-07-13
**Confidence:** HIGH — this milestone's research is grounded directly in the existing codebase (verified by reading the installed `qwen-tts==0.1.1` wheel, `tts_service`, `generation_worker.py`, `audio_join.py`, frontend components) rather than greenfield domain survey. v1.0 stack/features research (still largely applicable) was MEDIUM-HIGH.

## Executive Summary

v1.1 is not new-feature work in the greenfield sense — it is a targeted hardening and UX-unification pass on an already-shipped pipeline. The milestone has four capabilities: (1) truly immediate cancellation of an in-flight Qwen3-TTS `generate()` call, (2) on-demand swap between the 1.7B and 0.6B CustomVoice checkpoints within the 16GB VRAM budget, (3) FLAC/Opus output added (WAV dropped) in the ffmpeg join step, and (4) an editable output filename with a dedicated download endpoint — all wrapped in a unified 3-state (yellow/red/green) generate/stop/play button replacing today's separate status-badge column and four independently hand-rolled button implementations.

The recommended approach reuses existing architecture almost entirely rather than introducing new infrastructure: no task queue, no WebSockets, no new abstractions. Cancellation is solved with a `threading.Event` + a monkeypatched/injected `StoppingCriteria` on the TTS process's inner `talker.generate()` call (verified necessary by reading the installed `qwen-tts` wheel — the outer `generate_custom_voice()` wrapper silently drops `stopping_criteria` kwargs), combined with converting per-segment/per-character generation from synchronous request/response into the same addressable-background-task pattern batch generation already uses. Model swap reuses the standard PyTorch `del` + `gc.collect()` + `torch.cuda.empty_cache()` pattern, gated by the existing single-flight generation lock, with the live model id threaded into the content-hash cache key (today hardcoded) to prevent silent stale-model cache hits. FLAC/Opus is an explicit format-dispatch table in `audio_join.py`, and the download endpoint reuses this project's own established discipline of server-generated UUID storage paths with user text used only for display/`Content-Disposition`, never for path construction.

The key risks are: (a) "immediate cancel" quietly regressing to today's best-effort "stops before next segment" if the lock is released before the underlying call is truly finished (a race that can double-run the GPU); (b) the 0.6B checkpoint silently dropping `instruct` voice-steering entirely — a real, verified behavioral difference the UI must surface, not just a speed/VRAM tradeoff; (c) ROCm VRAM fragmentation across repeated model swaps on a budget with limited headroom; and (d) reintroducing a path-traversal-class bug by using the new user-editable filename as an on-disk path, which the codebase has twice already explicitly guarded against elsewhere (T-03-01/T-03-06). All four are directly actionable — this research file names the exact fix for each.

## Key Findings

### Recommended Stack

v1.0's stack (FastAPI + SQLModel/SQLite, Qwen3-TTS-12Hz-1.7B-CustomVoice via the `qwen-tts` pip package on ROCm PyTorch, React+Vite+TanStack Table frontend, ffmpeg-via-subprocess join, OpenRouter for LLM analysis) is unchanged and confirmed correct for v1.1's needs — no new core dependency is required. The v1.1-specific additions all use stdlib/already-installed primitives: `transformers.StoppingCriteria`/`StoppingCriteriaList` (already pinned via `transformers==4.57.3`) for cancellation, stdlib `threading.Event`/`Lock` and `gc`/`torch.cuda.empty_cache()` for the model swap, and ffmpeg's built-in `flac` encoder plus `libopus` (confirm present in the deploy VM's ffmpeg build) for the new output formats.

**Core technologies for v1.1:**
- `transformers.StoppingCriteria` (pinned `transformers==4.57.3`) — per-token cancellation check inside the talker's real HF `generate()` loop; the only mechanism that interrupts inside `model.generate()` without killing the resident-model process
- A bound-method patch/injection on `model.model.talker.generate` in `tts_service/model.py` — bridges the outer `qwen-tts` wrapper's dropped `**kwargs` to the inner call that actually honors `stopping_criteria` (verified against the installed wheel, not assumed)
- `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` (same HF family, same `from_pretrained`/`generate_custom_voice` call shape as the 1.7B model already in use) — the second selectable checkpoint
- stdlib `del` + `gc.collect()` + `torch.cuda.empty_cache()` (ROCm build aliases `torch.cuda.*` to HIP transparently) — VRAM release pattern for swapping resident models
- ffmpeg native `flac` encoder + `libopus` — no new packages; extend the existing `codec_args` dispatch table in `audio_join.py`

### Expected Features

v1.0's feature research (LLM-driven cast detection + segmented multi-voice TTS + spreadsheet review + content-hash caching) remains the product's core value and is unaffected by v1.1. v1.1's own feature research is narrowly UX-pattern-focused: state-switch button legibility (NN/g), model-selector plain-language labeling, and export/download conventions (Carbon Design System).

**Must have (table stakes) for v1.1:**
- Unified 3-state (yellow=idle/stale, red=generating, green=complete) button reused identically across per-row, per-character-preview, and batch generate/stop/play — icon+color+text must agree (NN/g state-switch research: color- or icon-alone is the #1 confusion source)
- Synchronous click-time lock/disable on every generate-triggering control, not just relying on the existing app-wide `generationLocked` poll
- Any edit that invalidates cached audio visibly reverts the button to yellow (already backend-supported via GEN-03; this is now the *only* visual carrier of that state since the status badge column is dropped)
- Download button appears only once `project.output_path` exists, filename pre-filled from the project's configured value
- Stop control gives instant "Stopping…" visual feedback even though the actual backend abort may take up to one decode step

**Should have (differentiators):**
- Plain-language model-size labels ("Higher quality (1.7B)" / "Faster (0.6B)") rather than raw model IDs
- One consistent color-button vocabulary reused across all three scopes (not different controls per scope) — the differentiator is consistency, not novelty

**Defer (v2+):**
- True mid-inference hard-kill of the GPU call beyond what `StoppingCriteria` achieves — explicitly a harder backend problem, out of scope for this UX milestone
- Auto-download/auto-play on completion — anti-feature; keep user-triggered per existing GEN-03 "no auto-regenerate" precedent
- A 4th button state for "queued" — milestone explicitly wants 3 states; fold queued into yellow

### Architecture Approach

The app is a two-process/two-container topology (verified, not assumed): a CPU-only FastAPI backend and a separate GPU-owning `tts_service` FastAPI process communicating over HTTP (`httpx.post` + `run_in_threadpool`), both long-lived with a single resident model. v1.1's four capabilities integrate into this boundary without changing its shape — no new services, no task queue, no WebSocket migration. Cancellation and model-swap both live inside `tts_service`'s existing module-global pattern (mirroring the backend's own `_active_generation_label` single-flight lock, just moved one process over). FLAC/Opus and the download endpoint are fully independent of the TTS boundary, touching only `audio_join.py`/`config.py`/`main.py`.

**Major components (existing, extended by v1.1):**
1. `backend/app/generation_worker.py` — app-wide single-flight lock (`try_claim_generation`/`release_generation`); extended in v1.1 from a `project_id`-keyed task registry to a `label`-keyed one so per-segment/per-character cancel has an addressable task handle
2. `backend/tts_service/model.py` — holds the resident model as a module global; v1.1 adds `ensure_loaded(model_id)` load/unload logic plus a `threading.Event`-based cancel flag and the `StoppingCriteria` injection
3. `backend/app/cache_key.py` — content-hash cache key; `TTS_MODEL_VERSION` moves from a hardcoded constant to a live per-project value (`Project.tts_model`) so a swap correctly busts stale cross-model cache hits
4. `backend/app/audio_join.py` / `backend/app/config.py` — ffmpeg codec dispatch and the output-format allowlist; extended to an explicit `{flac, mp3, opus}` mapping with no catch-all fallback, WAV removed
5. Frontend `useGeneratePlayState` (new, to be extracted) — a single shared hook/component consumed by all 4 existing hand-rolled generate/play button implementations (`SegmentTable`, `CharacterCard`, `ConfigPanel`'s character-preview control, `ConfigPanel`'s batch control), replacing per-file duplicated state derivation

**Suggested build order (from Architecture research):** Capability 1 (cancel) first — it's the hardest unknown and the most architecturally invasive (per-segment generate must become a background task). Capability 2 (model swap) second, extending the same `tts_service` engine-state module. Capabilities 3 (codec) and 4 (download/filename) last — fully decoupled from 1/2, additive and mechanical, can ship together in one Config Panel phase.

### Critical Pitfalls

1. **Cancel that only stops the queue, not the in-flight GPU call** — the existing batch cancel already documents this exact limitation ("stops before the next segment... does not abort the in-flight one"). Naively reusing `task.cancel()` for per-segment/per-character cancel reproduces the same non-fix with a faster-looking UI. Avoid by making `tts_service`'s own generate loop genuinely interruptible via `StoppingCriteria`, not just cancelling the backend's wait.
2. **Releasing the global generation lock before the killed call has actually stopped** — opens a window for two concurrent `/synthesize` calls to race the single resident model (GPU errors, garbled audio). Avoid by holding the lock until the underlying HTTP call to `tts_service` is confirmed returned/aborted, not merely until `.cancel()` was requested; extend the existing `test_lock_releases_after_batch_cancel` test pattern to per-segment/per-character cancel.
3. **No addressable cancellable task handle for per-segment/per-character generation today** — only the batch path has a task registry; per-segment generate is awaited synchronously inline. Avoid by generalizing `_running_generations` to a `label`-keyed dict (reusing the exact `try_claim_generation` label strings already constructed) and converting per-segment generate to the same fire-then-202-poll contract batch/preview already use.
4. **Model swap breaks the "load exactly once, never reload" invariant and the cache doesn't know a swap happened** — silently serves stale audio from the wrong model as a false cache hit. Avoid by wiring the live model id into `compute_cache_key` and gating swap-in-progress behind the same lock plus a `_ready=False` window.
5. **VRAM fragmentation across repeated ROCm model swaps** on a 16GB budget with limited headroom — `del`+`empty_cache()` doesn't guarantee full reclaim. Mitigate with before/after VRAM logging (`torch.cuda.mem_get_info()`) and a documented container-restart fallback if fragmentation proves real on the actual RX 9070 XT hardware.
6. **User-editable output filename used as the on-disk path** — reopens a path-traversal/overwrite class of bug this codebase has twice already explicitly guarded against (T-03-01/T-03-06). Keep the on-disk path a server-generated UUID always; the user's name is `Content-Disposition`-display-only, via `FileResponse`'s built-in `filename=` support (never hand-formatted header strings).
7. **Four independently hand-rolled generate/play button implementations** (`SegmentTable`, `CharacterCard`, `ConfigPanel`'s two separate controls) multiplying drift if the 3-state rework is bolted onto each in place. Extract one shared hook/component first, then layer 3-state semantics on top — don't repeat the state derivation four times.

## Implications for Roadmap

Based on research, the milestone's four capabilities plus the button-consolidation prerequisite suggest the following phase structure. This maps closely to the "Suggested Build Order" in ARCHITECTURE.md and the "Phase to address" column in PITFALLS.md, both of which independently converge on the same sequencing logic (cancel is hardest/most invasive → do first; codec/download are decoupled/mechanical → do last).

### Phase 1: Immediate Cancellation (Capability 1)
**Rationale:** The one genuine technical unknown in this milestone (does `stopping_criteria` actually abort a live ROCm decode loop, not just the reference CUDA path) and the most architecturally invasive change — per-segment generate must become an addressable background task before any cancel endpoint has something to reach. Landing it first de-risks the milestone's hardest question early and gives Phase 2 a shared `tts_service` engine-state module to extend rather than build from scratch.
**Delivers:** `threading.Event`-based cancel flag + injected `StoppingCriteria` in `tts_service/model.py`; new `POST /cancel` on `tts_service`; `generation_worker._running_generations` generalized to a label-keyed registry; per-segment and per-character generate converted from synchronous await to the same fire-then-202-poll contract batch generation already uses; new `POST /segments/{id}/generate/cancel` and `POST /characters/{id}/preview/cancel` routes.
**Addresses:** FEATURES.md's "Stop control gives instant visual feedback" and "any edit invalidating audio visibly reverts to idle" table stakes.
**Avoids:** Pitfalls 1, 2, 3 (fake-immediate cancel, lock-released-early race, no task handle to cancel).

### Phase 2: On-Demand Model Swap (Capability 2)
**Rationale:** Mechanically well-understood (a standard PyTorch load/unload pattern) once Phase 1's `tts_service` engine-state module exists to extend — the open questions here (speaker-list parity across checkpoints, VRAM fragmentation, real swap latency) are spike-and-verify items on real hardware, not architecture risk.
**Delivers:** `Project.tts_model` DB column; `ensure_loaded(model_id)` load/unload function in `tts_service/model.py` gated by the existing single-flight lock; live model id threaded into `compute_cache_key` (replacing the hardcoded `TTS_MODEL_VERSION` constant); explicit `POST /model/{model_id}/load` endpoint plus a matching backend route the Config Panel calls; 0.6B `instruct`-drop surfaced as a warning in the model dropdown.
**Uses:** stdlib `del`/`gc.collect()`/`torch.cuda.empty_cache()`; the second HF checkpoint `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`.
**Implements:** the `_engine_state` module scaffold introduced conceptually in Phase 1, extended with resident-model tracking.
**Avoids:** Pitfalls 4 (stale cross-model cache hits) and 5 (VRAM fragmentation) — both explicitly require real-RX-9070-XT-hardware verification before considered done, not just mock-backend passing.

### Phase 3: Config Panel Output Options — Codec + Filename/Download (Capabilities 3 & 4)
**Rationale:** Fully decoupled from Phases 1–2 (no shared code with the TTS HTTP boundary) and mostly decoupled from each other; additive/mechanical/lower-risk, so sequenced last. Natural to ship both in one phase since both extend `Project` with new per-project settings columns in a single migration pass, and the download endpoint's Content-Type/extension logic is more naturally written once the codec set is final.
**Delivers:** Explicit `{flac, mp3, opus}` codec dispatch table in `audio_join.py` (no catch-all fallback), `_ALLOWED_OUTPUT_FORMATS` and `load_settings()`'s default updated together with deploy Quadlet config audited; `Project.output_filename` column; new `GET /projects/{id}/download` using `FileResponse`'s `filename=` support (server-generated UUID path, user text display-only).
**Addresses:** FEATURES.md's "output-format dropdown" and "editable output filename + download" table stakes.
**Avoids:** Pitfalls 6 (silent format mis-encode), 7 (stale WAV default breaking deploys), 8 (filename-as-path traversal/overwrite), 9 (hand-built Content-Disposition header).

### Phase 4: Unified Generate/Stop/Play Button (Capability 5 — the UX layer over Phases 1–3)
**Rationale:** Depends on Phase 1's backend contract change (per-segment generate flips from synchronous 200 to async 202+poll) — building this UI against today's synchronous shape would be wasted work. Also depends on Phase 2/3 only for the config-panel-specific controls (model dropdown, format dropdown, download button) it wires up alongside the color-button rework.
**Delivers:** One shared hook/component (`useGeneratePlayState` or equivalent) owning yellow/red/green derivation and click dispatch, consumed by all 4 existing call sites (`SegmentTable`, `CharacterCard`, `ConfigPanel`'s character-preview control, `ConfigPanel`'s batch control) — extraction happens *before* adding the new red state, not after. Status badge column removed from the segment table. Config panel model-size and output-format dropdowns wired to the new backend endpoints, disabled while `generationLocked`.
**Addresses:** FEATURES.md's entire v1.1 UX table-stakes list.
**Avoids:** Pitfall 10 (four divergent hand-rolled implementations drifting independently).

### Phase Ordering Rationale

- Cancel (Phase 1) must land first because it is both the hardest unresolved technical question and a structural prerequisite (addressable task handles) that Phases 2 and 4 build on.
- Model swap (Phase 2) reuses Phase 1's `tts_service` engine-state scaffold rather than inventing a second one — sequencing them adjacently avoids two separate locking/state-management designs in the same file.
- Codec/download (Phase 3) has zero shared code with the TTS HTTP boundary, so it can be built, tested, and reviewed independently of GPU-hardware verification — a good phase to de-risk in parallel with Phase 2's hardware validation if schedule pressure demands it, though the default sequential order above is simplest.
- The button rework (Phase 4) is deliberately last because it is the one place all three backend capabilities become visible to the user — building it against a stable, already-changed backend contract avoids redoing frontend work against a moving synchronous-vs-async API shape.

### Research Flags

Phases likely needing deeper research during planning (`--research-phase`):
- **Phase 1:** The `StoppingCriteria`-actually-aborts-a-live-ROCm-decode-loop claim is verified as reachable in the library's Python call chain (HIGH confidence, read from the installed wheel) but NOT yet verified against real GPU inference (MEDIUM confidence) — a short spike against the real deployment target should happen early in this phase, not be assumed.
- **Phase 2:** VRAM fragmentation behavior under repeated ROCm swap cycles has no established ground truth for this app's specific hardware (RX 9070 XT/gfx1201) — real-hardware measurement (`torch.cuda.mem_get_info()`/`rocm-smi`) is a required verification step, not a documentation lookup. Also verify `get_supported_speakers()` parity between the 1.7B and 0.6B checkpoints once the 0.6B weights are actually downloaded.

Phases with standard patterns (skip research-phase, patterns already well-documented in this research):
- **Phase 3:** ffmpeg codec dispatch and `FileResponse.filename=` are conventional, well-documented mechanisms; the main verification is a one-line `ffmpeg -codecs | grep -E 'opus|flac'` check on the deploy container, not open research.
- **Phase 4:** Standard React hook-extraction refactor; NN/g state-switch guidance is already synthesized above.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | v1.1-specific findings verified by directly reading the installed `qwen-tts==0.1.1` wheel's source in the production container image, not from docs/blogs; ffmpeg codec presence (MEDIUM) still needs a one-time confirmation on the deploy VM (no ffmpeg binary in the research sandbox) |
| Features | MEDIUM-HIGH | UX-pattern sources (NN/g, Carbon, uxpatterns.dev) are authoritative but general, cross-checked against direct codebase inspection of the actual existing button/lock/status code, which grounds them in this app's real constraints |
| Architecture | HIGH | Call boundary, cancel semantics, and the `stopping_criteria` hook's reachability are all verified directly against this repo's code and the installed `qwen_tts` wheel, not assumed from general HF/Transformers documentation |
| Pitfalls | HIGH | Grounded directly in this repo's existing code (generation_worker, tts_service, audio_join, frontend components) plus targeted, cross-checked web research on ROCm memory behavior and asyncio thread-cancellation limitations (a well-documented, non-project-specific Python limitation) |

**Overall confidence:** HIGH — this is unusually well-grounded research for a milestone research pass because three of the four research files verified claims by reading the actual installed library source and the actual current codebase, not by inferring from general documentation.

### Gaps to Address

- **`StoppingCriteria` abort latency on real ROCm hardware is unverified** (reachable in the call chain per the installed wheel, but not yet exercised end-to-end against live GPU inference) — treat as the first spike in Phase 1, not a solved problem.
- **`libopus` presence in the deploy container's ffmpeg build is unconfirmed** (no ffmpeg binary available in the research sandbox) — a one-line `ffmpeg -codecs` check should be the first step of Phase 3, before any codec-dispatch code is written.
- **VRAM fragmentation across repeated model swaps has no measured baseline on the RX 9070 XT** — Phase 2 should include an explicit real-hardware swap-cycle test (e.g. 10+ swaps in one session) with before/after `torch.cuda.mem_get_info()` logging as an exit criterion, not just "the code runs without an exception."
- **Speaker-list parity between the 1.7B and 0.6B CustomVoice checkpoints is unknown** — `get_supported_speakers()` may differ; verify once the 0.6B weights are downloaded, in Phase 2.
- **Whether the milestone's "click kills it immediately" copy can be literally true, or should be scoped to "UX-level immediacy" (fast disable/relabel/poll) with the true GPU-call kill flagged as a harder backend problem** — PITFALLS.md and ARCHITECTURE.md both flag this as a decision the team must make explicitly and document (not let it default silently), before Phase 1's button copy is finalized in Phase 4.

## Sources

### Primary (HIGH confidence)
- Direct inspection of the production container's installed `qwen-tts==0.1.1` source (`qwen_tts/inference/qwen3_tts_model.py`, `qwen_tts/core/models/modeling_qwen3_tts.py`)
- This repo, direct code read: `backend/app/generation_worker.py`, `backend/app/main.py`, `backend/app/tts_client.py`, `backend/app/cache_key.py`, `backend/app/config.py`, `backend/app/audio_join.py`, `backend/tts_service/model.py`, `backend/tts_service/server.py`, `backend/tests/test_generation_lock.py`, `deploy/qwen-ebook-tts.container`, `deploy/qwen-ebook-backend.container`, `frontend/src/components/{SegmentTable,CharacterCard,ConfigPanel}.tsx`, `frontend/src/hooks/useGenerationLock.ts`, `frontend/src/api/client.ts`
- [ROCm compatibility matrix (AMD official docs)](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) — RDNA4/gfx1201 support
- [OpenAI TTS 4096-character limit discussion](https://community.openai.com/t/tts-with-more-than-4096-characters/591842), [Google Cloud TTS quotas](https://cloud.google.com/text-to-speech/quotas) — official docs, v1.0 long-text handling context

### Secondary (MEDIUM confidence)
- [State-Switch Controls: The Infamous Case of the "Mute" Button — NN/G](https://www.nngroup.com/articles/state-switch-buttons/)
- [Carbon Design System — Export pattern](https://carbondesignsystem.com/community/patterns/export-pattern/)
- [Model Selector Pattern — UX Patterns for Developers](https://uxpatterns.dev/patterns/ai-intelligence/model-selector)
- [HIP out of memory when there appears to be plenty of memory available · ROCm/ROCm Discussion #2407](https://github.com/ROCm/ROCm/discussions/2407)
- [run_in_executor not stopping thread after task cancellation in asyncio · Issue #107505 · python/cpython](https://github.com/python/cpython/issues/107505)
- [FFmpeg Concat Guide: Demuxer, Filter, Protocol and API](https://renderio.dev/blogs/ffmpeg-concat-guide/)
- [Running Qwen TTS on AMD Strix Halo (tinycomputers.io)](https://tinycomputers.io/posts/qwen-tts-on-amd-strix-halo.html)

### Tertiary (LOW confidence, needs validation)
- ffmpeg `libopus`/`flac` flag names and recommended bitrate/`-application voip` settings — not run locally in this research pass (no ffmpeg binary in sandbox); verify against `ffmpeg -h encoder=libopus`/`encoder=flac` on the deploy VM before merging
- Qwen3-TTS's exact per-request max input length (v1.0 gap, still unresolved) — not blocking for v1.1's scope but remains an open item for future long-segment handling work

---
*Research completed: 2026-07-13*
*Ready for roadmap: yes*
