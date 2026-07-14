# Qwen Ebook Narrator

## What This Is

A self-hosted web app that turns long text (ebooks, articles) into a multi-voice narrated audiobook using Qwen TTS. An LLM (accessed via OpenRouter) analyzes the source text, auto-detects the cast of characters (narrator plus speaking characters, inferred from context — names, ages, personalities), and splits the text into narration/dialogue segments with per-segment voice instructions. The user reviews and edits everything in a spreadsheet-like table before generating and joining the final audio file. Built for personal use: converting owned text into audio for commute/workout listening.

## Core Value

Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.

## Current Milestone: v1.1 Generation UX & Config Rework

**Goal:** Replace ambiguous status indicators with a single clear color-coded generate/stop/play control everywhere audio is generated, and give the user real control over model, output format, filename, and downloading the finished file.

**Target features:**
- Segment table trimmed to 3 columns (Narrator / Voice Instructions / Text) — separate Status badge column dropped, state now conveyed by button color
- One consistent yellow "Generate Preview" → red "Stop Generation" (kills the in-flight GPU call immediately) → green "Play" pattern, applied to: per-segment preview, per-character preview, and the Generate All batch flow. Any edit that invalidates audio reverts the control back to yellow.
- Config panel: switch between two Qwen TTS models (1.7B / 0.6B, load-on-demand — only one resident in VRAM at a time), pick output format (FLAC / MP3 / Opus — WAV dropped), and set the output filename
- Once all segments are generated and joined: a blue "Download" button plus a green "Play" to preview the joined file in-browser

## Requirements

### Validated

- [x] User can upload a plain text (.txt) file as the source for a new project — Validated in Phase 1
- [x] Long source texts are chunked on natural structural boundaries (paragraph), not arbitrary token counts — Validated in Phase 1
- [x] Generated segments are joined in order into a single output audio file (MP3 or WAV) — Validated in Phase 1 (proven with mock audio; real-audio join still pending Phase 1's GPU override, see below)
- [x] Text is analyzed by an LLM (via OpenRouter, default model `x-ai/grok-4.3`) which auto-detects the cast of characters (narrator + speaking characters) with inferred descriptions (age, personality, gender) from context — Validated in Phase 2
- [x] Text is split into narration/dialogue segments, each tagged with a suggested speaker and voice instructions (e.g. "narrates in a soothing voice", "gaining confidence") — Validated in Phase 2
- [x] User reviews and adjusts the auto-suggested cast via a wizard (rename, merge, edit descriptions, assign/preview a voice) before segments are generated — Validated in Phase 2
- [x] Voice assignment supports both preset voices (e.g. male/female narrator, stock characters) and LLM/context-derived voice instructions for characters without a good preset match — Validated in Phase 2
- [x] Main UI is a table (~70% width) with three editable columns: Narrator (dropdown of defined characters), Voice Instructions (free text), Text (free text) — Validated in Phase 3 (TBL-01/02), plus bulk multi-row select/reassign (TBL-03) and status-driven per-row generate/play controls (TBL-04)
- [x] Right-side panel (~30% width) holds config: input file, model, output format, output file, and live conversion progress — Validated in Phase 3 (CFG-01/02/03), including a Stop control and on-demand character-preview generation added during UAT gap closure
- [x] Each table row's audio segment is generated individually via Qwen TTS (self-hosted, running on the AMD GPU host) — Validated in Phase 3 (GEN-02), with a content-hash cache keyed on (resolved speaker, voice instructions, text, model version) so an unchanged row never re-synthesizes
- [x] Editing a row's text, voice instructions, or narrator invalidates its stale audio (clears it, marks pending) but does NOT auto-regenerate — regeneration is user-triggered only via the per-row or Generate All controls — Validated in Phase 3 (GEN-03). **Reversed from the original "auto-regenerate on edit" wording during Phase 3 UAT** (see 03-CONTEXT.md D-06) after the user found auto-fire-on-blur surprising; the invariant now holds project-wide including bulk-reassign/merge/voice-preset-edit paths (closed as code-review finding CR-01, commit `cdcdbf4`).
- [x] Projects (source text, character cast, segment table, generated audio) are saved and can be reopened later — single user, no accounts — Validated in Phase 3 (PERS-01/02): auto-save on every edit, a Project List landing screen, resumable batch generation, and a stuck-analyzing-screen recovery path for a stale/deleted project id
- [x] App is deployed via Podman on a VM with an AMD GPU (RX 9070 XT, 16GB VRAM), served over the user's Tailscale network (no public exposure, no auth needed beyond Tailscale) — Validated in Phase 3 (DEPL-02): Podman Quadlet systemd units, `tailscale serve` fronting a loopback-only backend, a persistent `/data` volume, and restart self-heal (`--exit-policy=continue`) all confirmed live on the production RX 9070 XT VM
- [x] User can upload an EPUB (.epub) source file, with chapter/reading-order text extracted and markup/footnotes stripped — Validated in Phase 2 (ING-02, plan 02-02): `epub_parser.py` (ebooklib + BeautifulSoup/lxml), spine-order extraction, footnote stripping, fail-fast on unrecoverable chapters, wired into `POST /projects`
- [x] User can pick between two Qwen TTS model sizes (1.7B / 0.6B) per project, with only one resident in VRAM at a time and a warning that 0.6B drops free-text voice-instruction steering — Validated in Phase 5 (CFG-04/CFG-05): `ensure_loaded(model_id)` swap engine (real-hardware-verified: 12 alternating swap cycles, zero VRAM fragmentation drift, 4.7-6.0s latency), `Project.tts_model` threaded through `compute_cache_key` so a swap can never serve stale cross-model audio, and a persistent D-03 warning note replacing the old hardcoded model display. A code review caught and fixed a real correctness gap before sign-off (CR-01, commit `d675fa4`): the generation path didn't reconcile tts_service's single resident model with the *current* project before synthesizing, so a swap in one project could silently produce audio under the wrong model for a different project.

### Active

- [ ] v1.1 Generation UX & Config Rework — see Current Milestone above; REQ-IDs pending REQUIREMENTS.md

### Out of Scope

- Multi-user accounts / login — single-user personal tool, Tailscale handles access control
- PDF input — only .txt and .epub for v1
- Audiobook-specific output (M4B, chapter markers) — plain MP3/WAV file for v1
- Real-time audio streaming/preview during generation — batch generate-then-download flow
- Public/cloud deployment — local VM + Tailscale only

## Context

- Personal project: the user wants to listen to ebooks/texts they own as multi-character narrated audio during commute/workouts.
- Deployment target: Podman container(s) on a VM with an AMD RX 9070 XT (16GB VRAM), 32GB RAM, 16-core CPU. Local dev/testing happens on the user's current (non-GPU-specified) system — GPU-dependent behavior (Qwen TTS inference) should degrade gracefully or be mockable in dev.
- Qwen TTS runs self-hosted on the AMD GPU host (ROCm), not via a cloud TTS API.
- Text analysis/character detection uses an LLM accessed via OpenRouter (cloud) — user already has an OpenRouter API key.
- Network exposure is via Tailscale (private mesh network), so no public-facing auth layer is needed.

**v1.0 shipped state (2026-07-12):** ~5,500 LOC (Python backend + TypeScript/React frontend) across 163 files, 3 phases / 17 plans / 39 tasks over 4 days. Live and verified end-to-end on the production RX 9070 XT VM at `https://tts.pigeon-bearded.ts.net` (Podman Quadlet units, restart-resilient, persistent `/data` volume). All 27 v1 requirements shipped and validated — no open v1 gaps.

**Known technical debt / open threads for v2 planning:**
- CAST-02 (cross-chunk cast reconciliation) is proven by a behavioral unit test and a real-Grok single-chunk smoke test, but never exercised against a real long book spanning multiple chunks through a real LLM call — worth a real-world validation pass if long-book casting quality is ever in question.
- Deferred v2 candidates (tracked in STATE.md Deferred Items pending the next milestone's requirements pass): LLM cost/usage visibility (ENH-01), "last good" audio fallback on a bad regenerate (ENH-02), audiobook-specific output/M4B+chapters (OUT-01), voice cloning from personal recordings (VOICE-01).

## Constraints

- **Hardware**: Deployment GPU is AMD RX 9070 XT, 16GB VRAM — Qwen TTS inference must run under ROCm within that VRAM budget.
- **Deployment**: Must run via Podman (not Docker) on the target VM.
- **Network**: Served as a Tailscale service — no public internet exposure, single trusted user/network.
- **External APIs**: Depends on OpenRouter (LLM gateway) availability/cost for text analysis; Qwen TTS is self-hosted so no per-request cloud TTS cost, but requires GPU inference infrastructure in the container.
- **Persistence**: Single-user with saved projects — needs some form of local storage (files/DB) for project state (text, cast, segments, generated audio), no multi-tenant data model needed.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LLM auto-suggests the character cast (vs. fully manual) | Reduces manual setup for each new text; user just reviews/tweaks | Phase 2: cast-detection wizard built and validated; user reviews/edits before segments generate |
| Invalidate the edited segment's cached audio, not the whole file — and don't auto-regenerate on edit | Fast iteration when tweaking voice instructions/text per character, without surprising auto-fired synthesis on every blur | Phase 3: content-hash cache (GEN-02) ships single-row regeneration; **reversed mid-Phase-3 UAT** from "auto-regenerate on edit" to "invalidate only, user triggers regeneration manually" (D-06/GEN-03) after the user found auto-fire-on-blur surprising in practice |
| Voice assignment mixes presets + context-derived instructions | Qwen TTS has limited presets; LLM-inferred character traits fill the gap for one-off characters | Phase 2: preset + free-text `instruct` steering both wired through the cast wizard and Config Panel, with on-demand preview generation added during Phase 3 UAT |
| Self-hosted Qwen TTS on AMD GPU (ROCm) rather than cloud TTS API | Avoids per-request cost, keeps generation local to the Tailscale network | Phase 1: code/model/server proven correct against the real `qwen-tts` API; dev GPU (Radeon 780M/gfx1103, unsupported) reproducibly crashes on actual synthesis, documented via a fallback ladder. Production RX 9070 XT VM re-verification (D-09) closed out 2026-07-10 (commit `1ce34aa`): real non-silent audio confirmed end-to-end, rootful Podman is the required invocation shape (rootless `--group-add keep-groups` does not grant `/dev/kfd` access on this Podman/crun combo, independent of GPU architecture) |
| Podman (not Docker) for deployment | User's existing infra preference | Phase 1: two-container Podman pod built and proven — GPU devices correctly isolated to the TTS container only, backend has none, network/error-boundary wiring confirmed working |
| Serve the built frontend from the backend container itself (multi-stage Containerfile + `StaticFiles` mount), not a separate static host | Every real-hardware check up to Phase 3 sign-off curl'd API routes directly, so nobody noticed the browser root URL 404'd until the user opened it | Post-sign-off fix (commit `63b705b`): one container serves both `/api/*` and `index.html`/JS/CSS, registered after all API routes so it only catches what no route claims; verified live through `tailscale serve` |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-14 after Phase 5 (On-Demand Model Swap) completion*
