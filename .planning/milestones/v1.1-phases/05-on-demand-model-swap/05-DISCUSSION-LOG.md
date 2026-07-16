# Phase 5: On-Demand Model Swap - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 5-On-Demand Model Swap
**Areas discussed:** Swap trigger UX, 0.6B warning UX, Existing segments after a swap, Speaker preset parity

---

## Swap trigger UX

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit load, blocking spinner | Picking the model fires the dedicated load endpoint right away; dropdown shows a spinner/disabled state for the swap, then settles. | ✓ |
| Lazy swap on next Generate | Selecting a model just updates the stored preference; the actual VRAM swap happens transparently on the next Generate click. | |
| You decide | Claude picks during planning. | |

**User's choice:** Explicit load, blocking spinner
**Notes:** None.

| Option | Description | Selected |
|--------|-------------|----------|
| Show error, revert dropdown to prior model | Inline error + dropdown snaps back to whichever model is still actually resident. | ✓ |
| Show error, leave selection but mark project 'no model loaded' | Dropdown keeps the picked model as intent; Generate blocked until retry. | |
| You decide | Claude picks the simplest failure-safe behavior during planning. | |

**User's choice:** Show error, revert dropdown to prior model
**Notes:** None.

---

## 0.6B warning UX

| Option | Description | Selected |
|--------|-------------|----------|
| Persistent inline note under the dropdown | Small always-visible text, no dismiss, no modal. | ✓ |
| One-time dismissible toast on selection | Toast pops on switching to 0.6B, then goes away. | |
| You decide | Claude picks the simplest honest treatment. | |

**User's choice:** Persistent inline note under the dropdown
**Notes:** None.

| Option | Description | Selected |
|--------|-------------|----------|
| Stay editable, warning is enough | Fields remain fully editable; the persistent warning sets expectations. | |
| Gray out / disable the fields while 0.6B is active | Fields become read-only/dimmed to reinforce they currently have no effect. | ✓ |
| You decide | Claude picks based on smaller diff. | |

**User's choice:** Gray out / disable the fields while 0.6B is active
**Notes:** User explicitly picked the non-recommended option — wants the disabled state to be explicit rather than relying on warning text alone.

---

## Existing segments after a swap

| Option | Description | Selected |
|--------|-------------|----------|
| Leave as-is, no forced change | Segment statuses/audio stay exactly as they were; old audio remains playable. | |
| Proactively mark all segments 'needs regeneration' | Every segment flips to a stale/pending-looking state the moment the swap completes. | ✓ |
| You decide | Claude picks based on Phase 5's actual scope. | |

**User's choice:** Proactively mark all segments 'needs regeneration'
**Notes:** User explicitly picked the non-recommended option — wants it obvious a full re-generate pass is recommended, not a silent state.

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse GEN-03's existing invalidation | Loop every segment, apply the identical clear-audio/status=pending transition an edit already triggers. | ✓ |
| New distinct status (e.g. 'stale-model') | New status value distinguishing swap-invalidation from edit-invalidation. | |
| You decide | Claude picks based on what the existing status enum supports. | |

**User's choice:** Reuse GEN-03's existing invalidation
**Notes:** None.

---

## Speaker preset parity

| Option | Description | Selected |
|--------|-------------|----------|
| Silent fallback to that model's default speaker | Mismatched character just uses the new model's default speaker instead of erroring. | ✓ |
| Block generation for that character with a clear error | Affected character's rows can't generate until a valid preset is picked. | |
| You decide | Claude picks after the spike verifies whether speaker lists actually differ. | |

**User's choice (free text):** "silent fallback. make a note to plan preset generation at a later point to have custom voices ready for use"
**Notes:** User confirmed silent-fallback behavior, and raised a related but out-of-scope idea (planning ahead for custom voice preset generation/preparation across model swaps) — captured under Deferred Ideas, confirmed back to user before proceeding.

---

## Claude's Discretion

- Default model for both new and pre-migration projects (default to 1.7B, preserving current behavior, unless research finds a strong reason otherwise).
- Whether a one-time cache-key version bump is needed to force-invalidate pre-migration cached audio.
- Exact spinner/disabled-state visuals, error message wording, and warning-note copy.
- Whether the swap-in-progress state disables the whole Config Panel or just the model dropdown + Generate controls.

## Deferred Ideas

- Custom voice preset preparation ahead of model swaps — planning/generating presets in advance so a consistent voice is ready across model swaps, rather than relying on silent fallback-to-default when presets don't line up. New capability, out of Phase 5's scope; candidate for a future phase or v2 planning.
- "Cast Review wizard stop control and layout" todo — reviewed (low-confidence keyword match against Phase 5) but not folded; unrelated to model swapping, belongs with Phase 7 or a dedicated follow-up phase.
