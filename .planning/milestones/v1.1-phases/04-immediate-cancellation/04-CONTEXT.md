# Phase 4: Immediate Cancellation - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Stopping a segment, character voice preview, or a running batch generation interrupts the in-flight GPU TTS call itself — not merely the queue of remaining work. Today, only the batch "Generate All" flow has a Stop control at all, and its own doc comment admits it "stops before the next segment — the segment currently generating may still finish." Per-segment (`POST /segments/{id}/generate`) and character preview (`POST /characters/{id}/preview`) have zero cancel UI or backend cancel path today. This phase makes all three genuinely interruptible and gives the two that currently lack any Stop control a minimal, functional one.

Out of scope (per REQUIREMENTS.md v1.1): process-level force-kill beyond `StoppingCriteria`; auto-download/auto-play on completion; a 4th "queued" button state; the full yellow/red/green button unification across all 4 call sites (that's Phase 7).

</domain>

<decisions>
## Implementation Decisions

### Cancellation promise
- **D-01:** "Stop" must achieve a **true kill** of the in-flight GPU call — not a UX-level decouple where the button goes idle while the orphaned `tts_service` call keeps running and is silently discarded on completion. This is a firmer bar than research's own "acceptable fallback" suggestion (PITFALLS.md's "best-effort + orphan-discard via `generation_version` guard") — that fallback is explicitly NOT pre-approved for this phase.
- **D-02:** The first spike of this phase is proving `StoppingCriteria` actually aborts a live ROCm decode loop promptly (STATE.md already flags this as MEDIUM confidence, unverified against real hardware). **If the spike shows it does NOT work** (doesn't abort, or aborts too slowly to call "immediate"), the researcher/planner must **stop and bring findings back to the user** rather than silently substituting the best-effort/orphan-discard fallback or any other weaker mechanism. Do not let this decision get made unilaterally downstream.

### Stopping UI state
- **D-03:** Every Stop control (segment, character preview, batch) shows a **distinct "stopping…" transient state** between the click and confirmed-stopped (i.e., while the global generation lock is still held per Pitfall 2's "hold until confirmed stopped" requirement) — not an instant optimistic flip to idle. This accurately reflects that a new generation genuinely cannot start yet during that window.

### Stop button scope for this phase
- **D-04:** Segment-row and character-preview Stop buttons added in this phase are **bare-bones/functional only** (e.g. plain "Stop" button, no color-state polish) — proving the backend interrupt is real is the goal, not the unified yellow/red/green component. The 4-call-site consolidation into a shared hook/component (PITFALLS.md Pitfall 10) is explicitly Phase 7's job, not pulled forward into this phase.
- **D-05:** Despite being bare-bones, each of the 3 states from D-03 must exist in some form: idle/generating/stopping — the "stopping…" state (D-03) is not optional polish, it's required to reflect actual backend semantics honestly.

### Copy update
- **D-06:** Update ConfigPanel's batch Stop caveat text now (currently: *"Stops before the next segment — the segment currently generating may still finish."*) since this phase makes that statement false. Leaving stale, inaccurate copy live between phases is misleading. Full copy ownership moves to Phase 7's unified button, but this interim fix ships in Phase 4.

### Claude's Discretion
- Exact wording of the updated caveat copy (D-06).
- Exact shape of the "stopping…" state's visual treatment (spinner variant, disabled styling, etc.) as long as it's visually distinct from both idle and actively-generating (D-03/D-05) — full styling consolidation is Phase 7's job, this just needs to be honest, not polished.
- Internal registry/task-handle design for making segment and character-preview generation addressable/cancellable (research already proposes generalizing `_running_generations` to a `label`-keyed dict reusing `try_claim_generation`'s existing label strings — planner should follow this unless a spike finds a reason not to).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 4 research (already complete)
- `.planning/research/ARCHITECTURE.md` §"Capability 1 — Immediate Cancel" — the `StoppingCriteria` + `threading.Event` design in `tts_service`, the label-keyed task registry generalization, and why no per-request cancellation token is needed (single-flight lock already guarantees one synth call app-wide)
- `.planning/research/PITFALLS.md` §Pitfalls 1-3 — the three concrete traps this phase must avoid: (1) cancel that only stops the queue not the in-flight call, (2) releasing the lock before the killed call is truly confirmed stopped (race risk), (3) segment/character generation having no addressable task handle today
- `.planning/research/PITFALLS.md` §"Anti-Pattern: Reaching for a task queue to solve cancellation" and §"Anti-Pattern: Rewriting the backend's HTTP client to async" — both explicitly ruled out; the fix is almost entirely inside `tts_service`
- `.planning/REQUIREMENTS.md` — GEN-06, GEN-07, GEN-08 (locked requirements for this phase); Out of Scope table (process-level force-kill, 4th button state, full unification)
- `.planning/ROADMAP.md` §Phase 4 — success criteria and dependency note (Phase 5 builds on the `tts_service` engine-state module and lock extended here)
- `.planning/STATE.md` §Blockers/Concerns — the unresolved-until-now "true kill vs UX-level immediacy" framing this discussion resolved as D-01/D-02

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `generation_worker.py`'s `_active_generation_label` global + `try_claim_generation`/`release_generation` — the existing single-flight lock this phase must extend (hold-until-confirmed-stopped), not replace
- `generation_worker._running_generations: dict[project_id, Task]` — today keyed only by `project_id` for the batch path; research proposes generalizing to a `label`-keyed dict reusing the exact `f"segment:{id}"` / `f"preview:{id}"` / `f"batch:{id}"` strings `try_claim_generation` already receives
- `main.py`'s `_spawn_claimed_generation` helper — already the pattern for turning a claimed generation into a tracked background task with guaranteed lock release via `add_done_callback`; character preview (`trigger_character_preview`) already uses this, segment generate does not yet (see Integration Points)
- `main.py`'s `generation_version` last-request-wins guard (used by both `regenerate_segment` and `_generate_preview`) — the exact mechanism that would back a fallback "orphan-discard" path if D-02's escalation is ever resolved that way by the user later

### Established Patterns
- `regenerate_segment`/`_generate_preview` broad `except Exception` + log + status="error" — deliberate pattern for fire-and-forget background tasks with no caller to propagate to; a cancellation path needs an equivalent clean reset-to-pending (not "error") for the stopped case
- `cancel_generation`'s existing `# ponytail:` comment in `main.py` (lines ~1007-1013) already documents today's ceiling and an upgrade path — this phase is that upgrade landing, the comment should be removed/rewritten once superseded

### Integration Points
- `POST /segments/{segment_id}/generate` (`main.py`) currently `await`s `regenerate_segment` synchronously inline in the request handler — no task object exists for a hypothetical `POST /segments/{id}/generate/cancel` to reach. Per PITFALLS.md Pitfall 3, this must become a fire-and-return-202 + poll/status contract (matching the batch and character-preview shape) before a segment-level cancel endpoint has anything to call `.cancel()` on. This is a bigger structural change than "add a button" — frontend's `generateSegment()` call site in `api/client.ts` changes from await-for-result to await-202-then-poll.
- `tts_service/server.py`'s `/synthesize` endpoint has no concurrency control of its own (bare `run_in_threadpool`) — the new `/cancel` endpoint and `_cancel_event`/`StoppingCriteria` machinery land here, per ARCHITECTURE.md's proposed `_engine_state` module (shared scaffold Phase 5's model-swap work will also extend)
- `frontend/src/components/SegmentTable.tsx`'s `GeneratePlayButton`, `CharacterCard.tsx`'s inline generate/preview controls, and `ConfigPanel.tsx`'s separate `CharacterPreviewControl` and batch Generate-All/Stop control are 4 independently-written implementations today (not 3) — this phase only touches the 2 that currently have no Stop button (segment row, character preview) plus the copy fix on the 3rd (batch); it does not touch `CharacterCard.tsx`'s wizard-side preview button, which stays out of scope per D-04

</code_context>

<specifics>
## Specific Ideas

No specific visual/copy examples given beyond D-06's requirement to fix the now-inaccurate batch caveat text — exact wording is Claude's discretion.

</specifics>

<deferred>
## Deferred Ideas

- Full 4-call-site shared hook/component unification (yellow/red/green states, consistent styling) — explicitly Phase 7, not pulled forward (D-04)
- `CharacterCard.tsx`'s wizard-side preview button getting its own Stop control — not raised as in-scope for Phase 4; if needed, it's part of Phase 7's unification pass
- Shrinking `/generation-status` poll interval now that stop should be sub-second (PITFALLS.md notes the old slower design masked poll lag that a fast stop would expose) — not discussed as a Phase 4 requirement; flagging here in case it surfaces as a rough edge during Phase 4 implementation/testing

### Reviewed Todos (not folded)
None — no pending todos matched this phase (`cross_reference_todos` found 0 matches).

</deferred>

---

*Phase: 4-Immediate Cancellation*
*Context gathered: 2026-07-13*
