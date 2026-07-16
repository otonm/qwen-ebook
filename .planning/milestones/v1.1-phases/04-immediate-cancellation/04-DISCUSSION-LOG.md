# Phase 4: Immediate Cancellation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 4-Immediate Cancellation
**Areas discussed:** Cancellation promise/fallback, Stopping UI transient state, Stop button scope, Batch caveat copy

---

## Cancellation promise & fallback ceiling

| Option | Description | Selected |
|--------|-------------|----------|
| True kill is required | If the spike fails to prove prompt interruption on real hardware, that's a blocker — escalate back for a design change rather than shipping a weaker guarantee. | ✓ |
| Best-effort with orphan-discard fallback | Ship StoppingCriteria; if flaky/slow on ROCm, fall back to UI-goes-idle + orphaned result discarded via generation_version guard. Document the ceiling. | |
| Not sure — investigate during planning | Let the phase researcher/planner spike it first and bring back a recommendation. | |

**User's choice:** True kill is required.
**Notes:** Firmer than the recommended option. Follow-up question asked what should happen specifically if the spike proves this isn't achievable on real ROCm hardware.

---

## Spike-failure escalation path

| Option | Description | Selected |
|--------|-------------|----------|
| Pause and come back to me | Don't let the researcher/planner silently adopt the best-effort/orphan-discard fallback — stop and get explicit user decision. | ✓ |
| Auto-adopt the documented fallback | Fall back to best-effort + orphan-discard automatically without a checkpoint. | |

**User's choice:** Pause and come back to me.
**Notes:** Combined with the prior answer, this locks D-01/D-02 in CONTEXT.md — the fallback ceiling PITFALLS.md documents is explicitly NOT pre-approved for silent adoption.

---

## Stopping UI transient state

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct "stopping…" state | Transient state between click and confirmed-stopped, mirroring what the lock actually guarantees (Pitfall 2). | ✓ |
| Instant optimistic idle | Button flips to idle immediately regardless of backend confirmation; simpler but risks a confusing 409 window. | |

**User's choice:** Distinct "stopping…" state.
**Notes:** None.

---

## Stop button scope for Phase 4

| Option | Description | Selected |
|--------|-------------|----------|
| Bare-bones now, unify in Phase 7 | Minimum functional Stop control per call site now; Phase 7 owns the shared component and styling. | ✓ |
| Build the shared component now | Do the 4-call-site consolidation as part of Phase 4, expanding scope beyond the roadmap's current description. | |

**User's choice:** Bare-bones now, unify in Phase 7.
**Notes:** Matches the roadmap's explicit phase split (Phase 7 = "Unified Generate/Stop/Play Button & Trimmed Segment Table").

---

## Batch caveat copy

| Option | Description | Selected |
|--------|-------------|----------|
| Update it now | The underlying behavior becomes true in Phase 4; leaving stale copy live is misleading. | ✓ |
| Leave it for Phase 7 | Keep Phase 4 strictly backend + minimal buttons; defer all copy/UI polish. | |

**User's choice:** Update it now.
**Notes:** None.

---

## Claude's Discretion

- Exact wording of the updated batch caveat copy (D-06)
- Exact visual treatment of the "stopping…" state, as long as it's distinct from idle and generating (D-03/D-05)
- Internal task-registry design for segment/character-preview cancellation (research already proposes generalizing `_running_generations` to a label-keyed dict)

## Deferred Ideas

- Full 4-call-site shared hook/component unification (Phase 7)
- `CharacterCard.tsx`'s wizard-side preview button getting a Stop control (not raised as in-scope; possible Phase 7 item)
- Shrinking `/generation-status` poll interval now that stop should be sub-second (surfaced from PITFALLS.md, not discussed as a requirement — flagged for awareness during implementation)
