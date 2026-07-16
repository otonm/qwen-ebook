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

## Milestone: v1.1 — Generation UX & Config Rework

**Shipped:** 2026-07-16
**Phases:** 4 | **Plans:** 15 | **Tasks:** 37

### What Was Built
- True mid-flight GPU cancellation: StoppingCriteria patched directly into qwen-tts's talker.generate (its wrapper drops the kwarg), ~46ms decode abort on real ROCm hardware, exposed through an async 202+poll contract with a label-keyed task registry.
- On-demand 1.7B/0.6B model swap with zero measured VRAM drift over 10+ cycles, cache-key-aware so stale cross-model audio is structurally impossible.
- Output format (FLAC/MP3/Opus via one ffmpeg CODEC_TABLE), custom filename with sanitizing PATCH endpoint, blue Download button.
- One shared useGenerateStopPlay hook + GenerateStopPlayButton replacing four hand-rolled generate/play implementations; segment table trimmed to 3 editable columns; joined-output in-browser Play.

### What Worked
- Sequencing the hardest unknown first (Phase 4's real-hardware StoppingCriteria spike) — it changed the backend contract (sync 200 → async 202+poll) that all later phases built on, so nothing had to be reworked.
- Checkpoint-gated human-verify plans (04-04, 06-03, 07-05) caught real bugs during the plan itself (dead SSE reconnect, stuck "Stopping…" state, filename sanitizer truncation, batch mislabel) instead of after sign-off — the v1.0 lesson applied.
- Post-completion standard-depth code review on Phase 7 found 8 real findings (3 critical, including an unguarded model swap mid-generation); fixing once in the shared hook fixed every call site.
- Consolidate-then-harden: unifying four implementations into one shared hook meant subsequent review fixes and behavior changes landed in one place.

### What Was Inefficient
- The reviewer's suggested fix for one finding (WR-01) would itself have introduced a regression — the fixer traced it and implemented a corrected variant. Review suggestions are hypotheses, not patches; tracing before applying is mandatory.
- The 2026-07-14 todo (wizard Stop control/layout) was two-thirds absorbed by Phase 7 but nobody closed or updated the todo file, so it surfaced as a blocker at milestone close and needed archaeology to resolve. Todos touched by a phase should be reconciled at that phase's completion.
- MILESTONES.md accomplishments auto-extracted all 15 plan one-liners verbatim; needed manual condensation to be readable.

### Patterns Established
- Async 202 + label-keyed task registry + hold-lock-until-genuinely-stopped for any cancellable GPU work.
- Shared presentational-button + state-machine-hook pair for any multi-site UI control (status precedence: stopping > generating > ready > idle).
- Coverage blocks in SUMMARY.md frontmatter — 13 of 21 UAT deliverables auto-passed from automated verification refs, shrinking human UAT to the 8 genuinely visual/interactive checks.

### Key Lessons
1. Library wrappers can silently drop kwargs (qwen-tts dropped stopping_criteria) — verify the mechanism reaches the metal, not just that the call accepts the argument.
2. task.cancel() on a thread-pooled asyncio call does not stop the underlying work — a checked stop-request flag that the worker polls is the honest mechanism.
3. Optimistically clearing "in-flight" UI state on a failed stop request misrepresents reality; only confirmed completion should clear it (CR-02).
4. Fixed audio URLs are cached by browsers across regenerations — cache-bust with a version param or the user hears the previous take (WR-04).

### Cost Observations
- Model mix: not tracked this milestone (fixer/reviewer/auditor agents ran on sonnet per model_profile: balanced).
- Sessions: 2026-07-13 → 2026-07-16 (4 days).
- Notable: 164 files changed (~14.4k insertions); zero new runtime dependencies added across all four phases.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | ~4 days | 3 | Initial build — vertical-slice phases, orchestrator-run real-hardware checkpoints established as the pattern for GPU/sudo work |
| v1.1 | ~4 days | 4 | Riskiest-spike-first sequencing; checkpoint-gated human-verify plans inside phases; coverage-block SUMMARYs shrink human UAT |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|---------------------|
| v1.0 | not aggregated | not tracked | ebooklib, beautifulsoup4, lxml (EPUB parsing only) |
| v1.1 | not aggregated | not tracked | none — zero new dependencies |

### Top Lessons (Verified Across Milestones)

1. Real-browser/real-UI verification, not just API-level checks, catches gaps that matter to the actual user. (v1.0 lesson, applied in v1.1 via checkpoint-gated human-verify plans — caught 4 real bugs pre-sign-off.)
2. Verify a mechanism reaches the hardware, not just that the API accepts it — wrappers drop kwargs silently (v1.1).
