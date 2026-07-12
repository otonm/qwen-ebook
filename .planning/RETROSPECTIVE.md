# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-07-12
**Phases:** 3 | **Plans:** 17 | **Tasks:** 39

### What Was Built
- Upload-to-audio pipeline (.txt and .epub) chunked on structural boundaries, synthesized via self-hosted Qwen TTS on ROCm, joined via ffmpeg.
- LLM-driven cast detection (OpenRouter/Grok) with cross-chunk character reconciliation, plus a review wizard (rename/merge/edit/voice-assign, instant preview).
- Full editable segment table: bulk reassign, per-row and resumable batch generation with content-hash caching, live SSE progress, project save/reopen.
- Production deployment: Podman Quadlet units on the real RX 9070 XT VM, Tailscale-only exposure, persistent data volume, restart resilience.

### What Worked
- Vertical-slice phase structure (each phase ships a genuinely usable, if narrower, app) over a horizontal infra-then-features split — Phase 1 front-loaded the riskiest GPU/ROCm bet while still shipping a real upload-to-audio flow.
- Real-GPU/sudo checkpoints (production VM bring-up, crash-resume, concurrent-edit races) were run by the orchestrator directly against the actual hardware rather than mocked — caught the rootful-vs-rootless Podman GPU passthrough gap and a `sox` packaging bug that a mocked check would have missed.
- Content-hash caching (character + voice instructions + text + model version) kept regeneration cheap and made single-row edits fast to iterate on.
- Fail-fast EPUB parsing (reject the whole upload on an unrecoverable chapter) over silently skipping broken chapters — simpler to reason about and avoided silent partial-book bugs.

### What Was Inefficient
- Phase 3 was marked "complete" once, then needed a second gap-closure wave (4 more plans, 03-06..09) after UAT surfaced blockers: stale-analysis-stream recovery, generation-lifecycle races, and a persistent-volume gap — worth tightening UAT coverage earlier next time rather than after sign-off.
- Every real-hardware check up to Phase 3 sign-off verified API endpoints directly via curl; nobody drove the actual browser URL, so the frontend 404'd in production for a full day before the user noticed. A real-browser check should be part of any deployment verification that touches user-facing routes.
- The "auto-regenerate on edit" behavior (original GEN-03 wording) had to be reversed mid-Phase-3 after the user found auto-fire-on-blur synthesis surprising in practice — an assumption worth user-testing earlier, before it's built into the API contract.
- REQUIREMENTS.md checkboxes/traceability were only updated after Phase 1; Phase 2 and Phase 3 completions never went back to check them off, so 11 of 27 requirements looked "Pending" at milestone close despite being shipped and validated in PROJECT.md weeks earlier. Reconciled by hand during `/gsd-complete-milestone`.

### Patterns Established
- Orchestrator-run real-hardware checkpoints (GPU inference, sudo/systemd deploys) for anything a worktree-isolated executor agent structurally can't reach.
- SSE for one-way live progress (analysis streaming, batch generation progress) instead of WebSockets, matching the stack's "no bidirectional need" reasoning.
- In-memory-built binary test fixtures (EPUB) instead of committed binary blobs.

### Key Lessons
1. A verification pass that only exercises API endpoints can still ship a broken user-facing app — always include one real-browser/real-UI check for anything with a frontend route.
2. Don't lock in an "auto-fire" UX behavior (auto-regenerate, auto-save-and-send, etc.) without a real UAT pass first; users find silent automatic side effects surprising more often than expected.
3. Requirement-checkbox bookkeeping drifts silently if it's only done once (e.g. after Phase 1) — either update it every phase completion or don't rely on it as the milestone-close gate; verify against the code/PROJECT.md instead when in doubt.
4. Ring-fencing a known hardware limitation (dev iGPU can't run real inference) as an accepted spike finding, rather than blocking on it, kept Phase 1 moving — the real validation correctly happened later against production hardware (D-09).

### Cost Observations
- Model mix: not tracked this milestone.
- Sessions: work spanned 2026-07-09 to 2026-07-12 (4 days).
- Notable: two real-hardware checkpoints (production VM bring-up, frontend-serving fix) were caught and fixed *after* their respective phases were nominally signed off — both closed same-day once found.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | ~4 days | 3 | Initial build — vertical-slice phases, orchestrator-run real-hardware checkpoints established as the pattern for GPU/sudo work |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|---------------------|
| v1.0 | not aggregated | not tracked | ebooklib, beautifulsoup4, lxml (EPUB parsing only) |

### Top Lessons (Verified Across Milestones)

1. Real-browser/real-UI verification, not just API-level checks, catches gaps that matter to the actual user.
