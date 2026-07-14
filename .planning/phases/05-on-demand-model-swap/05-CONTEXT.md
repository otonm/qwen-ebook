# Phase 5: On-Demand Model Swap - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

User can pick between two Qwen TTS model sizes — 1.7B ("Higher quality") and 0.6B ("Faster") — per project, and the app safely swaps the resident model in VRAM on demand (only one loaded at a time), warning the user that the 0.6B checkpoint silently drops free-text voice-instruction steering. Segments generated after a swap must reflect the newly selected model; no stale cache hits across models.

Out of scope (per REQUIREMENTS.md v1.1 / ROADMAP.md Phase 5): a third model size or arbitrary model list; the unified yellow/red/green generate/stop/play button (Phase 7); output format/filename/download (Phase 6); process-level force-kill beyond what Phase 4 already built.

</domain>

<decisions>
## Implementation Decisions

### Swap trigger UX
- **D-01:** Picking a model from the Config Panel dropdown fires an **explicit load immediately** (research's dedicated `POST /model/{id}/load` endpoint), not a lazy swap deferred to the next Generate click. The dropdown shows a blocking spinner/disabled state for the duration of the swap (tens of seconds per STACK.md's swap-latency estimate) so the user always knows exactly when the swap happened. `/synthesize`'s own implicit-load-if-needed path (per ARCHITECTURE.md) stays as a safety net only, not the primary UX.
- **D-02:** If the explicit load fails (OOM, download error, checkpoint missing), show an inline error and **revert the dropdown to whichever model is still actually resident** — per STACK.md's swap sequence, the old model is only `del`'d after the new one loads successfully, so the prior model should still be usable. Do not leave the project in a "no model loaded" limbo state on a failed swap.

### 0.6B steering-limitation warning
- **D-03:** The "0.6B ignores voice-instruction steering" warning is a **persistent inline note under the model dropdown**, always visible whenever 0.6B is the active selection — not a one-time dismissible toast. No dismiss state to track; it's an honest, permanent fact about the current selection.
- **D-04:** While 0.6B is active, the per-segment **Voice Instructions fields in the table are grayed out / disabled** (not merely left editable with a warning) — reinforces that edits currently have no effect. This is a deliberate reversal of the initially-recommended "stay editable" option; the user wants the disabled state to be explicit rather than relying on the warning text alone.

### Existing segments after a swap
- **D-05:** A model swap **proactively invalidates every segment in the project** — this is a deliberate reversal of the initially-recommended "leave as-is" option. The user wants it obvious that a full re-generate pass is recommended after switching models, not a silent state where old-model audio keeps playing indistinguishably from current-model audio.
- **D-06:** The invalidation **reuses the exact same mechanism GEN-03 already uses for a per-row edit** (clear cached audio, revert status to "pending") — just triggered project-wide by the swap instead of per-row by an edit. No new status value, no new UI state; segments behave identically to any other stale row today. Smallest diff, and it composes cleanly with whatever Phase 7 later builds on top of the stale/pending state.

### Speaker preset parity across checkpoints
- **D-07:** If a character's assigned voice preset doesn't exist under the newly selected model's speaker list (STATE.md flags this as unverified — parity between 1.7B/0.6B speaker lists needs confirming once weights are downloaded), **silently fall back to that model's own default speaker** for the mismatched character rather than blocking generation or erroring. Keeps the swap itself always successful; a spike should still confirm whether the two checkpoints' speaker lists actually differ at all before this fallback path needs to be exercised.

### Claude's Discretion
- Default model for both new projects and projects that predate this migration: default to 1.7B (today's baseline model) unless the researcher/planner finds a strong reason otherwise — preserves existing behavior with zero surprise for already-generated audio, and matches `cache_key.py`'s existing hardcoded `TTS_MODEL_VERSION` pointing at the 1.7B checkpoint.
- Whether a one-time cache-key version bump is needed to force-invalidate pre-migration cached audio (PITFALLS.md's suggestion, since old cache keys computed without a model component can't be trusted post-fix) — planner's call based on how `compute_cache_key`'s signature actually changes.
- Exact spinner/disabled-state visual treatment for D-01's blocking load state, and exact wording of D-02's error message and D-03's persistent warning note.
- Whether the swap-in-progress state should also disable the whole Config Panel or just the model dropdown + Generate controls (must at minimum block Generate/Preview via the existing single-flight lock per ARCHITECTURE.md).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 5 research (already complete — HIGH confidence, verified against the production `qwen-tts==0.1.1` wheel)
- `.planning/research/ARCHITECTURE.md` §"Capability 2 — On-Demand Model Swap (1.7B / 0.6B)" — where model choice lives (`Project.tts_model` DB column, not a request param or pure global), the `ensure_loaded`/`_engine_state` module design, the explicit `/model/{id}/load` endpoint + implicit safety-net split, and why the swap must route through the existing `try_claim_generation` lock
- `.planning/research/PITFALLS.md` §Pitfall 4 ("Model swap breaks the load-once invariant... cache doesn't know a swap happened") and §Pitfall 5 ("Assuming `del model; torch.cuda.empty_cache()` fully reclaims VRAM — zero headroom for fragmentation") — the two concrete traps this phase must avoid, plus the anti-pattern table entries on lines ~228-245 (never skip wiring `TTS_MODEL_VERSION` into the cache key; only call `empty_cache()` on actual swaps, not every generation)
- `.planning/research/STACK.md` §"v1.1 Addendum" → "(b) Loading/unloading between the two model sizes without leaking VRAM" — the concrete 7-step swap sequence (acquire lock → del old model → gc.collect + empty_cache → from_pretrained new checkpoint → re-apply the D-02(Phase-4) StoppingCriteria monkeypatch to the fresh instance → re-derive DEFAULT_SPEAKER → release lock), the `MODEL_CHOICES` dict recommendation (no generic registry for two hardcoded ids), and the confirmed-from-source finding that the 0.6B checkpoint silently sets `instruct = None` regardless of caller input
- `.planning/REQUIREMENTS.md` — CFG-04, CFG-05 (locked requirements for this phase); Out of Scope table (no 3rd model size, no WAV)
- `.planning/ROADMAP.md` §Phase 5 — success criteria and the dependency note (this phase reuses Phase 4's `tts_service` engine-state module and single-flight lock)
- `.planning/STATE.md` §Blockers/Concerns — the two still-open Phase 5 items this discussion partially resolved: VRAM fragmentation baseline (needs a real-hardware 10+-swap test with `torch.cuda.mem_get_info()` logging as an exit criterion, per PITFALLS.md §Pitfall 5) and speaker-list parity (needs `get_supported_speakers()` checked once the 0.6B weights are downloaded — D-07 defines the fallback behavior if parity turns out incomplete)

### Phase 4 context (prior decisions this phase builds on)
- `.planning/phases/04-immediate-cancellation/04-CONTEXT.md` — the single-flight lock (`try_claim_generation`/`release_generation`) and label-keyed task registry this phase's model-load must claim through as just another labelled claimant (e.g. `"model-load:{model_id}"`), per ARCHITECTURE.md's explicit reuse recommendation

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/tts_service/model.py` — currently a module-level singleton (`model = Qwen3TTSModel.from_pretrained(MODEL_NAME, ...)` loaded once at import time, `MODEL_NAME` hardcoded to the 1.7B checkpoint). This is the file that becomes swappable; its existing `_cancel_event`/`StoppingCriteria` monkeypatch (Phase 4) must be re-applied to each freshly-loaded model instance since the patch doesn't persist across `from_pretrained` calls.
- `backend/app/cache_key.py`'s `compute_cache_key(resolved_speaker, voice_instructions, text)` — currently takes a hardcoded `TTS_MODEL_VERSION` constant, not a parameter. Must thread the actual per-project model id through instead (straightforward signature change per ARCHITECTURE.md, not a redesign).
- `backend/app/generation_worker.py`'s `try_claim_generation(label)` / `release_generation()` / `_running_generations` label-keyed registry (built in Phase 4) — the swap endpoint claims this lock under its own label before touching the resident model, exactly like segment/preview/batch generation already do.
- Existing GEN-03 per-row invalidation logic (whatever code path currently clears a segment's cached audio + reverts status to "pending" on a text/voice/narrator edit) — D-06 says the model-swap invalidation reuses this exact mechanism, just looped over every segment in the project.

### Established Patterns
- `tts_service/model.py`'s own docstring: "Loaded ONCE at module import time... never reload per request... the documented anti-pattern to avoid" — this phase is the one deliberate, controlled exception to that invariant, gated entirely behind the single-flight lock so no in-flight synth call can ever race a swap (Pitfall 4).
- `frontend/src/components/ConfigPanel.tsx` currently hardcodes `TTS_MODEL_DISPLAY_NAME = "Qwen3-TTS-12Hz-1.7B-CustomVoice"` (marked `// CFG-01: only one TTS model is in scope for v1 (D-17)`) — this phase replaces that fixed display with the actual dropdown + swap UX.

### Integration Points
- New `POST /model/{model_id}/load` on `tts_service/server.py` (per ARCHITECTURE.md) plus a matching backend endpoint (e.g. `POST /projects/{id}/model`) the Config Panel calls when the user picks a model — this is the D-01 explicit-load trigger.
- `Project.tts_model: str` — new SQLModel column (default = today's 1.7B model id per Claude's Discretion above), source of truth for "what this project wants," feeds into `compute_cache_key(..., model_id)`.
- `tts_service`'s `/healthz` and `/synthesize` already check a `_ready` flag (per PITFALLS.md §Pitfall 4's fix) — the swap must flip this to `False` for its duration so any request during the swap window gets a clean `503`, not a call against a half-torn-down model.

</code_context>

<specifics>
## Specific Ideas

No specific visual/copy examples given beyond the D-01/D-02/D-03 behavioral requirements above — exact spinner styling, error copy, and warning-note wording are Claude's discretion.

</specifics>

<deferred>
## Deferred Ideas

- **Custom voice preset preparation ahead of model swaps** — raised during the Speaker preset parity discussion: the user wants to eventually plan for generating/preparing custom voice presets so a consistent voice is ready across model swaps, rather than relying on the silent-fallback-to-default behavior (D-07) whenever presets don't line up. This is a new capability (voice preset management/generation), not in Phase 5's scope of picking between two fixed, pre-existing models — candidate for a future phase or v2 planning.

### Reviewed Todos (not folded)
- **"Cast Review wizard stop control and layout"** (`.planning/todos/pending/2026-07-14-cast-review-wizard-stop-control-and-layout.md`) — surfaced during Phase 4 testing; a low-confidence keyword match (score 0.5) against Phase 5. On review, it's entirely about missing Stop controls in the Cast Review wizard and a layout issue, unrelated to model swapping — belongs with Phase 7's button-unification work or a dedicated follow-up phase, not Phase 5.

</deferred>

---

*Phase: 5-On-Demand Model Swap*
*Context gathered: 2026-07-14*
