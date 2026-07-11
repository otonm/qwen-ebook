# Qwen Ebook Narrator

## What This Is

A self-hosted web app that turns long text (ebooks, articles) into a multi-voice narrated audiobook using Qwen TTS. An LLM (accessed via OpenRouter) analyzes the source text, auto-detects the cast of characters (narrator plus speaking characters, inferred from context — names, ages, personalities), and splits the text into narration/dialogue segments with per-segment voice instructions. The user reviews and edits everything in a spreadsheet-like table before generating and joining the final audio file. Built for personal use: converting owned text into audio for commute/workout listening.

## Core Value

Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.

## Requirements

### Validated

- [x] User can upload a plain text (.txt) file as the source for a new project — Validated in Phase 1
- [x] Long source texts are chunked on natural structural boundaries (paragraph), not arbitrary token counts — Validated in Phase 1
- [x] Generated segments are joined in order into a single output audio file (MP3 or WAV) — Validated in Phase 1 (proven with mock audio; real-audio join still pending Phase 1's GPU override, see below)

### Active

- [ ] User can upload a source text file (.epub) — .txt validated in Phase 1, .epub extraction remains open (Phase 2, ING-02)
- [ ] Text is analyzed by an LLM (via OpenRouter, default model `x-ai/grok-4.3`) which auto-detects the cast of characters (narrator + speaking characters) with inferred descriptions (age, personality, gender) from context
- [ ] Text is split into narration/dialogue segments, each tagged with a suggested speaker and voice instructions (e.g. "narrates in a soothing voice", "gaining confidence")
- [ ] User reviews and adjusts the auto-suggested cast via a wizard (rename, merge, edit descriptions, assign/preview a voice) before segments are generated
- [ ] Voice assignment supports both preset voices (e.g. male/female narrator, stock characters) and LLM/context-derived voice instructions for characters without a good preset match
- [ ] Main UI is a table (~70% width) with three editable columns: Narrator (dropdown of defined characters), Voice Instructions (free text), Text (free text)
- [ ] Right-side panel (~30% width) holds config: input file, model, output format, output file, and live conversion progress
- [ ] Each table row's audio segment is generated individually via Qwen TTS (self-hosted, running on the AMD GPU host) — code/wiring built and proven correct in Phase 1 (GEN-01); real audio generation on the production RX 9070 XT VM (Tailscale hostname `tts`) was verified 2026-07-10 (commit `1ce34aa`): a real end-to-end request returned a genuine non-silent WAV (24kHz, 21.4s, 96.5% non-zero samples), rootful Podman GPU passthrough confirmed as the working invocation shape. See `deploy/README.md` §"Production VM bring-up". No pod is left running between sessions — `bash deploy/run-local.sh` re-brings it up on demand; Phase 3 should re-confirm it still works before building the full generation pipeline on top.
- [ ] Editing a row's text or voice instructions after generation only regenerates that segment, then rejoins the full file (not a full regenerate)
- [ ] Projects (source text, character cast, segment table, generated audio) are saved and can be reopened later — single user, no accounts
- [ ] App is deployed via Podman on a VM with an AMD GPU (RX 9070 XT, 16GB VRAM), served over the user's Tailscale network (no public exposure, no auth needed beyond Tailscale) — two-container Podman pod with correct GPU isolation built and proven in Phase 1 (DEPL-01); the production RX 9070 XT VM exists and is reachable over Tailscale now (see above) — Phase 3 still owns actually serving the full app (not just the Phase 1 pod skeleton) from it long-term

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

## Constraints

- **Hardware**: Deployment GPU is AMD RX 9070 XT, 16GB VRAM — Qwen TTS inference must run under ROCm within that VRAM budget.
- **Deployment**: Must run via Podman (not Docker) on the target VM.
- **Network**: Served as a Tailscale service — no public internet exposure, single trusted user/network.
- **External APIs**: Depends on OpenRouter (LLM gateway) availability/cost for text analysis; Qwen TTS is self-hosted so no per-request cloud TTS cost, but requires GPU inference infrastructure in the container.
- **Persistence**: Single-user with saved projects — needs some form of local storage (files/DB) for project state (text, cast, segments, generated audio), no multi-tenant data model needed.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LLM auto-suggests the character cast (vs. fully manual) | Reduces manual setup for each new text; user just reviews/tweaks | — Pending |
| Regenerate only the edited segment, not the whole file | Fast iteration when tweaking voice instructions/text per character | — Pending |
| Voice assignment mixes presets + context-derived instructions | Qwen TTS has limited presets; LLM-inferred character traits fill the gap for one-off characters | — Pending |
| Self-hosted Qwen TTS on AMD GPU (ROCm) rather than cloud TTS API | Avoids per-request cost, keeps generation local to the Tailscale network | Phase 1: code/model/server proven correct against the real `qwen-tts` API; dev GPU (Radeon 780M/gfx1103, unsupported) reproducibly crashes on actual synthesis, documented via a fallback ladder. Production RX 9070 XT VM re-verification (D-09) closed out 2026-07-10 (commit `1ce34aa`): real non-silent audio confirmed end-to-end, rootful Podman is the required invocation shape (rootless `--group-add keep-groups` does not grant `/dev/kfd` access on this Podman/crun combo, independent of GPU architecture) |
| Podman (not Docker) for deployment | User's existing infra preference | Phase 1: two-container Podman pod built and proven — GPU devices correctly isolated to the TTS container only, backend has none, network/error-boundary wiring confirmed working |

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
*Last updated: 2026-07-09 after Phase 1 completion*
