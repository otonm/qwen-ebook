---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Generation UX & Config Rework
status: planning
last_updated: "2026-07-13T10:02:06.267Z"
last_activity: 2026-07-13
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-11)

**Core value:** Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.
**Current focus:** Phase 03 — editable-table-full-generation-pipeline-persistence-deployme

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-07-13 — Milestone v1.1 started

## Performance Metrics

**Velocity:**

- Total plans completed: 12
- Average duration: - min
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 03 | 9 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 03 P02 | 15 | 2 tasks | 4 files |
| Phase 03 P03 | ~4min+checkpoint | 4 tasks | 7 files |
| Phase 03 P04 | 10min | 2 tasks | 5 files |
| Phase 03 P05 | ~15min | 3 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: Vertical-slice (MVP) phase structure chosen over research's horizontal-leaning suggestion — Phase 1 front-loads the ROCm/Podman/Qwen-TTS GPU risk while still shipping a real upload-to-audio user flow, rather than a GPU-only infrastructure phase.
- Roadmap: Coarse granularity (config.json) produced 3 phases; DEPL-02 (Tailscale-only exposure) was folded into Phase 3 rather than given its own phase, to avoid a single-requirement phase.
- [Phase ?]: Bulk reassign only bumps generation_version to mark rows stale — it does not auto-trigger regeneration (batch regen is plan 03-03's scope)
- [Phase ?]: Radix Checkbox onCheckedChange passes a boolean, not a DOM event — wired via table.toggleAllRowsSelected(!!value)/row.toggleSelected(!!value) instead of the research pattern's getToggleXSelectedHandler()
- [Phase ?]: Batch loop reuses main.py's regenerate_segment (lazy in-function import) instead of duplicating cache-check/version-guard logic - one implementation for both per-row and batch call sites
- [Phase ?]: Task 4's real-GPU checkpoint (crash-resume + concurrent-edit-race) was run by the orchestrator directly on the production tts VM, automated via seeded throwaway projects + podman restart + TTS-container log inspection
- [Phase ?]: Project.created_at already existed from plan 03-01 — no schema change needed for plan 03-04's list endpoint
- [Phase ?]: Landing-with-no-project routing uses a separate in-memory LandingView state (list/upload) rather than overloading localStorage-backed projectId, so a mid-upload refresh lands back on the project list
- [Phase ?]: Task 3's production deployment was performed by the orchestrator directly on the tts VM over Tailscale SSH (sudo/systemd/tailscale access this executor agent lacks) — matches how 03-01's Task 4 real-GPU checkpoint was handled
- [Phase ?]: Open Question 2 from 03-RESEARCH.md is RESOLVED: tailscale serve on the host correctly reaches a Podman Quadlet pod port published to 127.0.0.1 only

### Pending Todos

None yet.

### Blockers/Concerns

- ~~Phase 1 (from research): ROCm 7.2/RDNA4 (gfx1201) support is very recent...~~ **RESOLVED 2026-07-10** (commit `1ce34aa`): the production RX 9070 XT VM (Debian 13, Tailscale hostname `tts`, real Navi 48/gfx1201 GPU) exists and the full D-09 re-verification checklist closed out against it — see `deploy/README.md` §"Production VM bring-up": `rocminfo`/on-device PyTorch matmul confirmed gfx1201 with no `HSA_OVERRIDE_GFX_VERSION`/`GPU_SECURITY_OPT` workarounds needed; rootless Podman GPU passthrough does NOT work on this Podman/crun combo (host GID mapping gap, not GPU-specific) — rootful (`sudo podman run --user 0:0`) does and is now `run-local.sh`'s default; a real end-to-end `POST /projects` returned a genuine non-silent WAV (24kHz, 21.4s, 96.5% non-zero samples). A `sox` packaging bug (missing transitive dependency of `qwen-tts`'s tokenizer) was found and fixed along the way. No pod is currently running on the VM (nothing persists a teardown) — `bash deploy/run-local.sh` re-brings it up on demand.
- ~~Phase 1 (from research): Podman GPU passthrough...~~ **RESOLVED**, see above — this is the same finding.
- Phase 2 (from research): Cross-chunk character reconciliation strategy is a synthesized best-practice (MEDIUM confidence), not a sourced novel-specific benchmark — validate chunk-size/context-window assumptions against Grok's actual limits and real book lengths before over-building chunking machinery. Partially addressed: 02-UAT.md's real-key Grok smoke test (2026-07-11) validated single-chunk prompt quality on a short passage; cross-chunk reconciliation itself is proven by a behavioral test (`test_run_analysis_multi_chunk_reconciles_duplicate_and_orders_segments_globally`) but not yet exercised against a real long book via a real LLM call — still open if that matters before Phase 3 sign-off.
- ~~Phase 3 (new): The real GPU pipeline works but was proven on a fresh single pass...~~ **PARTIALLY RESOLVED 2026-07-12** (03-01-SUMMARY.md Task 4): per-segment generate, content-hash cache-hit, and edit-triggered cache-bust are now verified against the real gfx1201 pod (non-silent WAV, 33ms cache-hit with zero extra `/synthesize` calls, cache-bust produces a different hash/key). Still open: resumable batch generation and concurrent/regenerate-while-batch-running behavior under real GPU inference — validate in 03-02 (batch generation plan), not just at sign-off.
- ~~Post-Phase-3 (found after sign-off): the backend never served the built frontend anywhere — every Task 4/Task 3 real-hardware check across 03-01/03-03/03-05 verified API endpoints directly (curl), so nobody noticed `https://tts.pigeon-bearded.ts.net/` 404'd for an actual browser until the user opened it.~~ **RESOLVED 2026-07-12** (commit `63b705b`): added a frontend build stage to `backend/Containerfile.backend` (multi-stage, `node:20-slim`) and mounted the built `dist/` via `StaticFiles(..., check_dir=False)` at `"/"` in `app/main.py`, registered after every API route so it only catches what no route claims. `deploy/run-local.sh`'s backend build now uses the repo root as context (not `backend/`) so the Containerfile can reach `frontend/`. Rebuilt and redeployed on the `tts` VM; verified root URL now serves `index.html` + JS/CSS bundles (200s) alongside working API routes, all through the real `tailscale serve` URL.

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

Last session: 2026-07-12T10:22:22.426Z
Stopped at: Phase 3 complete (v1 milestone done) — DEPL-02 verified on production tts VM via tailscale serve
Resume file: None
Next step: v1 milestone complete — /gsd-complete-milestone

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
