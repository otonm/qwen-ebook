---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Generation UX & Config Rework
current_phase: 7
current_phase_name: Unified Generate/Stop/Play Button & Trimmed Segment Table
status: executing
stopped_at: Phase 7 UI-SPEC approved
last_updated: "2026-07-15T19:54:37.478Z"
last_activity: 2026-07-15
last_activity_desc: Phase 06 complete, transitioned to Phase 7
progress:
  total_phases: 7
  completed_phases: 3
  total_plans: 10
  completed_plans: 10
  percent: 43
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-13)

**Core value:** Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.
**Current focus:** Phase 6 — Config Panel — Output Format, Filename & Download

## Current Position

Phase: 7 — Unified Generate/Stop/Play Button & Trimmed Segment Table
Plan: Not started
Status: Ready to execute
Last activity: 2026-07-15 — Phase 06 complete, transitioned to Phase 7

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 22
- Average duration: - min
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 03 | 9 | - | - |
| 04 | 4 | - | - |
| 05 | 3 | - | - |
| 06 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap (v1.1): Kept research's proposed 4-phase structure (Phases 4-7) rather than compressing further under "coarse" granularity — each phase has 2-5 requirements, a distinct observable user outcome, and a real technical boundary (cancellation risk / model-swap hardware risk / decoupled output mechanics / UI consolidation layer), so 4 phases (the upper bound of coarse's 2-4 range) was judged not over-fragmented.
- Roadmap (v1.1): Phase 4 (Immediate Cancellation) sequenced first — hardest unknown (StoppingCriteria on real ROCm hardware) and a structural prerequisite (addressable per-segment/per-character task handles) that Phases 5 and 7 build on.
- Roadmap (v1.1): Phase 6 (Config Panel output/filename/download) marked as technically independent of Phases 4-5 (no shared code with the TTS HTTP boundary) but sequenced after them per research's default milestone build order, not a hard dependency.
- Roadmap (v1.1): Phase 7 (unified button) deliberately last — depends on Phase 4's sync-to-async backend contract change plus the model/format/download controls Phases 5-6 add, so it's built against a stable backend rather than a moving API shape.

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 4 (from research): `StoppingCriteria` is verified reachable in the `qwen-tts` call chain by reading the installed wheel (HIGH confidence) but NOT yet verified to actually abort a live ROCm decode loop on real hardware (MEDIUM confidence) — treat as the first spike in Phase 4, not an assumed solved problem.
- Phase 5 (from research): VRAM fragmentation across repeated ROCm model swaps has no measured baseline on the RX 9070 XT (16GB) — Phase 5 should include a real-hardware swap-cycle test (10+ swaps) with before/after `torch.cuda.mem_get_info()` logging as an exit criterion.
- Phase 5 (from research): Speaker-list parity between the 1.7B and 0.6B CustomVoice checkpoints is unverified — check `get_supported_speakers()` once the 0.6B weights are downloaded.
- Phase 6 (from research): `libopus` presence in the deploy VM's ffmpeg build is unconfirmed (no ffmpeg binary in the research sandbox) — run `ffmpeg -codecs | grep -E 'opus|flac'` on the deploy container before writing codec-dispatch code.
- Cross-cutting (from research): whether "click kills it immediately" can be literally true (true GPU-call kill) or should be scoped to "UX-level immediacy" (fast disable/relabel/poll, with the true kill flagged as a harder backend problem) is a decision the team must make explicitly in Phase 4 and carry into Phase 7's button copy, not let default silently.
- Carried from v1.0: CAST-02 (cross-chunk cast reconciliation) is proven by a behavioral unit test and a real-Grok single-chunk smoke test, but never exercised against a real long book spanning multiple chunks through a real LLM call — still open if long-book casting quality is ever in question.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260709-vde | Simplify CLAUDE.md: remove cruft now that Phase 1 is built | 2026-07-09 | 08769f9 | [260709-vde-simplify-claude-md-remove-cruft-now-that](./quick/260709-vde-simplify-claude-md-remove-cruft-now-that/) |
| 260709-vlc | Prepare deploy tooling for bringing up the production RX 9070 XT VM (Debian 13, Tailscale SSH) | 2026-07-09 | a8d4461 | [260709-vlc-prepare-deploy-tooling-for-bringing-up-t](./quick/260709-vlc-prepare-deploy-tooling-for-bringing-up-t/) |
| 260713-dye | Rework the presets feature: 5 fixed voice presets the LLM casts/adapts per character, merged with per-segment delivery instructions at TTS time (tasks 1-4 done; human-verify checkpoint pending) | 2026-07-13 | 517a081 | [260713-dye-rework-the-presets-feature-5-fixed-voice](./quick/260713-dye-rework-the-presets-feature-5-fixed-voice/) |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | ENH-01: LLM cost/usage visibility | Deferred to v2 | Requirements definition |
| v2 | ENH-02: "Last good" segment audio fallback | Deferred to v2 | Requirements definition |
| v2 | OUT-01: Audiobook-specific output (M4B, chapter markers) | Deferred to v2 | Requirements definition |
| v2 | VOICE-01: Voice cloning from personal recordings | Deferred to v2 | Requirements definition |

## Session Continuity

Last session: 2026-07-15T15:00:30.479Z
Stopped at: Phase 7 UI-SPEC approved
Resume file: .planning/phases/07-unified-generate-stop-play-button-trimmed-segment-table/07-UI-SPEC.md
Next step: /gsd-plan-phase 4
