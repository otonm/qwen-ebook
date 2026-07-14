# Phase 5: On-Demand Model Swap - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 8 (6 modified, 0 new backend files, 2 modified frontend files)
**Analogs found:** 8 / 8 (all modifications to existing files — the analog for each is the file itself, since this phase extends established in-file patterns rather than introducing new modules)

Note: RESEARCH.md's "Recommended Project Structure" confirms **no new files** this phase — every change is an addition to an existing module. Accordingly "closest analog" below is generally the surrounding code in the same file (the pattern to imitate when adding the new function/route/column), except for the two genuinely new call-sites where a sibling file supplies the pattern.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/tts_service/model.py` (singleton → `ensure_loaded`) | service (GPU engine state) | event-driven (swap) | same file's existing module-load block (lines 20-52, 134-157) | exact (in-file) |
| `backend/tts_service/server.py` (`POST /model/{id}/load`) | route | request-response | same file's `/cancel` and `/synthesize` routes (lines 88-152) | exact (in-file) |
| `backend/app/models.py` (`Project.tts_model` column) | model | CRUD | `Character.voice_version` / `Segment.generation_version` (existing versioned fields, lines 39, 57) | exact (in-file) |
| `backend/app/cache_key.py` (`compute_cache_key` signature) | utility | transform | same file, existing function (lines 29-37) | exact (in-file) |
| `backend/app/tts_client.py` (`load_model(model_id)` helper) | service (HTTP client) | request-response | same file's `cancel()` (lines 67-87) | exact (in-file) |
| `backend/app/main.py` (`POST /projects/{id}/model` handler + segment/preview invalidation loop) | route / controller | CRUD + event-driven | `patch_character` (407-444) + `regenerate_segment`'s claim/release (826-931) + `patch_segment`'s invalidation (747-806) | exact (composed from 3 in-file analogs) |
| `frontend/src/components/ConfigPanel.tsx` (Model `Select` + D-02/D-03 note) | component | request-response | `BulkReassignToolbar`'s `Select` usage (`SegmentTable.tsx` 399-417) + `CharacterPreviewRow`'s trigger/error pattern (41-181) | role-match |
| `frontend/src/components/SegmentTable.tsx` (`EditableTextCell` disabled prop) | component | request-response | same file, same function (318-366) | exact (in-file) |

## Pattern Assignments

### `backend/tts_service/model.py` — singleton to `ensure_loaded(model_id)`

**Analog:** this file's own module-level load block (lines 20-52) and the StoppingCriteria monkeypatch (lines 134-157) — both must be re-run per swap instead of once at import.

**Current one-shot load pattern** (lines 20-52):
```python
MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_SPEAKER: str | None = None
model = Qwen3TTSModel.from_pretrained(
    MODEL_NAME, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa",
)
_supported_speakers = model.get_supported_speakers()
_narrator_candidates = [s for s in _supported_speakers if "narrat" in s.lower()]
DEFAULT_SPEAKER = _narrator_candidates[0] if _narrator_candidates else _supported_speakers[0]
```
→ Wrap this exact body (checkpoint id parameterized via `MODEL_CHOICES`) inside `ensure_loaded(model_id)`. Extract the DEFAULT_SPEAKER derivation into a `_pick_default_speaker(supported)` helper so it can be re-called per swap (RESEARCH.md Pattern 1, lines 165-210, is the authoritative target shape — copy it verbatim, it already matches this file's naming/logging conventions).

**Monkeypatch re-application pattern** (lines 134-157):
```python
_original_talker_generate = model.model.talker.generate
_original_speech_tokenizer_decode = model.model.speech_tokenizer.decode
def _talker_generate_with_cancel(*args, **kwargs): ...
model.model.talker.generate = _talker_generate_with_cancel
model.model.speech_tokenizer.decode = _speech_tokenizer_decode_with_timing
logger.info("Patched model.model.talker.generate to honor _cancel_event (D-02 fix)")
```
→ This entire block currently runs once at import time against the module-global `model`. It must become a function (`_apply_stopping_criteria_patch(model_instance)`) called at the end of every `ensure_loaded()` swap — the patch does not survive a fresh `from_pretrained()` object (RESEARCH.md explicitly calls this out). Keep the two `_original_*` closures scoped inside the function so each swap captures the NEW instance's unpatched methods, not stale references to the old model's methods.

**Logging convention to preserve:** every existing state transition in this file logs at `logger.info` with an f-string (`f"Loading {MODEL_NAME}..."`, `f"Default speaker chosen: {DEFAULT_SPEAKER}"`) — per CLAUDE.md's logging convention, `ensure_loaded()` needs equivalent `logger.info(f"...")` lines around: swap start, `torch.cuda.mem_get_info()` before/after unload (Pitfall 2's observability recommendation), and swap completion.

---

### `backend/tts_service/server.py` — `POST /model/{model_id}/load`

**Analog:** `/cancel` (lines 141-151) for the fire-and-brief-response shape; `/synthesize` (95-138) for the `_ready`-flag discipline and broad-except-with-logging pattern.

**`_ready` flag gating pattern** (lines 88-98, `/healthz` + `/synthesize`'s guard):
```python
@app.get("/healthz")
async def healthz() -> Response:
    if not _ready:
        return Response(status_code=503, content="model not loaded")
    return Response(status_code=200, content="ok")
...
if not _ready or _model_module is None:
    return Response(status_code=503, content="model not loaded")
```
→ The new route must flip `global _ready`; `_ready = False` at swap start (so a racing `/synthesize` cleanly 503s instead of hitting a half-torn-down model — Pitfall 4/PITFALLS.md), `_ready = True` again in both the success and failure branches (D-02: failure leaves the OLD model still resident and ready).

**Broad-except-then-500 pattern** (lines 131-136):
```python
except Exception:
    logger.exception("synthesis failed")
    return Response(status_code=500, content="synthesis failed")
```
→ Copy directly for the load route's failure branch — `logger.exception("model swap failed")` then `Response(status_code=500, ...)`, exactly as RESEARCH.md's Code Examples section already shows (lines 365-386 of 05-RESEARCH.md) — that snippet is drop-in ready, cite it directly rather than re-deriving.

**`run_in_threadpool` offload pattern** (lines 109-116, `/synthesize`'s CR-02 comment + call):
```python
wav_bytes = await run_in_threadpool(
    _model_module.synthesize_wav, req.text, req.speaker, req.instruct
)
```
→ Same offload is mandatory for `ensure_loaded()` (GPU-bound, blocking) — `await run_in_threadpool(_model_module.ensure_loaded, model_id)`.

---

### `backend/app/models.py` — `Project.tts_model` column

**Analog:** `Character.voice_version` / `Segment.generation_version` (lines 39, 57) — the existing "versioned field with an inline comment explaining the invalidation contract" convention.

```python
class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    filename: str
    ...
    output_path: str | None = None
    # NEW: which TTS checkpoint this project uses — the source of truth
    # compute_cache_key reads, not a request param or global (RESEARCH.md
    # Anti-Pattern: "Treating model choice as purely global config").
    tts_model: str = "1.7b"
```
Match the existing terse, comment-justified field style — no separate migration file exists in this codebase (SQLite dev-mode `create_all`, per the absence of any `alembic`/migrations dir); confirm this before adding one.

---

### `backend/app/cache_key.py` — thread `model_id` through `compute_cache_key`

**Analog:** the file's own function (lines 29-37) — drop `TTS_MODEL_VERSION` constant, add a real parameter, per RESEARCH.md Pattern 2 (lines 212-230), which is the exact target diff:

```python
def compute_cache_key(
    resolved_speaker: str, voice_instructions: str, text: str, model_id: str
) -> str:
    payload = _FIELD_SEPARATOR.join(
        [resolved_speaker, voice_instructions, text, model_id]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```
Preserve the module docstring's rationale style (lines 1-11) — update it to say the model identity is now a live per-project value, not a hardcoded constant. Preserve the `if __name__ == "__main__":` self-check block (lines 40-47) — CLAUDE.md/Ponytail expects exactly this kind of minimal `assert`-based self-check for non-trivial logic; extend its 3 assertions to also cover a `model_id` change producing a different digest (mirrors the existing "different text -> different digest" assertion, same pattern, one more line).

**Only call site today:** `regenerate_segment` in `main.py` (around line 845-850, just past the `merge_instructions` call) — must pass `project.tts_model` where it currently passes nothing/the constant.

---

### `backend/app/tts_client.py` — `load_model(model_id)` helper

**Analog:** `cancel()` (lines 67-87) — same "mock no-ops, http POSTs to tts_service, unknown backend raises" three-way switch shape used by every function in this file.

```python
def cancel() -> None:
    if settings.TTS_BACKEND == "mock":
        return
    if settings.TTS_BACKEND == "http":
        try:
            httpx.post(f"{settings.TTS_SERVICE_URL}/cancel", timeout=...).raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(f"cancel() POST to tts_service failed (best-effort): {exc}")
        return
    raise ValueError(f"Unknown TTS_BACKEND: {settings.TTS_BACKEND!r}")
```
→ `load_model(model_id)` copies this exact three-way shape. Difference from `cancel()`: this call is NOT best-effort/fire-and-forget — a failure must propagate (raise) so `main.py`'s handler can apply D-02 (revert to prior model, surface the error), unlike `cancel()`'s intentional swallow-and-log. Mock backend: no-op (`TTS_BACKEND=mock` has no real model to swap, per CLAUDE.md's `TTS_BACKEND=mock` dev-without-GPU convention). Use a longer read timeout matching `synthesize()`'s `httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)` (line 59) — a real swap takes "tens of seconds" per STACK.md, same order of magnitude as a real synth call, not `cancel()`'s tight 2s timeout.

---

### `backend/app/main.py` — `POST /projects/{project_id}/model` handler

**Analog 1 — claim/release lock discipline:** `regenerate_segment`'s and the batch-generate route's `try_claim_generation`/`release_generation` usage (imports at lines 59, 62; used at 960, 1113).

**Analog 2 — PATCH-with-invalidation shape:** `patch_character` (407-444):
```python
old_preview_path: str | None = None
with Session(engine) as session:
    character = session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    ...
    if voice_changed:
        character.voice_version += 1
        old_preview_path = character.preview_audio_path
        character.preview_audio_path = None
    session.add(character)
    session.commit()
    session.refresh(character)
    result = _serialize_character(character)
if old_preview_path:
    Path(old_preview_path).unlink(missing_ok=True)
return result
```
→ Same "clear field inside the session, unlink the file AFTER commit/session-close" ordering must be reused for every invalidated segment (and, per RESEARCH.md Pitfall 4's recommendation, every character preview — folded into the same loop). Collect `(old_audio_path)` pairs while iterating inside the `with Session` block, unlink all of them after `session.commit()`, exactly like this analog does for a single row.

**Analog 3 — segment invalidation body:** `patch_segment` (779-793):
```python
if any_changed:
    segment.generation_version += 1
    segment.generation_status = "pending"
    segment.generation_error = None
    old_audio_path = segment.audio_path
    segment.audio_path = None
```
→ D-06 says the swap handler loops this exact body over every segment in the project (plus clearing `segment.cache_key = None` per RESEARCH.md's Pattern 3 snippet, lines 236-247, which is slightly more complete than `patch_segment`'s in-place version — prefer RESEARCH.md's `cache_key = None` addition since a swap, unlike a per-row edit, must also invalidate the stored cache_key, not just the audio file).

**Analog 4 — the full composed handler:** RESEARCH.md's own "Code Examples" §"`POST /projects/{id}/model` backend handler shape" (05-RESEARCH.md lines 323-363) is already written against this exact codebase's `try_claim_generation`/`_serialize_project`/`Session(engine)` conventions — treat it as the primary template, not just inspiration; it correctly composes Analogs 1-3 above. Cross-check the `SetModelRequest` body-validation style against `CharacterPatch`/`SegmentPatch`'s existing Pydantic model shapes (referenced near line 407, `patch.character_id`/`patch.voice_preset` optional-field pattern) for naming consistency.

**Open item from RESEARCH.md (Pitfall 4, Open Question 1):** whether to fold character `preview_audio_path` invalidation into this same handler. RESEARCH.md recommends yes (same loop, one more table) — if the planner adopts that, the per-character clearing block is a straight lift of `patch_character`'s `old_preview_path` clear (see Analog 2 above), just triggered by the swap instead of a voice PATCH.

---

### `frontend/src/components/ConfigPanel.tsx` — Model `Select` + D-02/D-03 note

**Binding source:** `.planning/phases/05-on-demand-model-swap/05-UI-SPEC.md` §"Component Contracts" §1 (lines 93-129) — this is the approved, exact JSX/Tailwind/copy contract; treat it as the primary analog, already written specifically for this file.

**Analog for the `Select` control itself:** `SegmentTable.tsx`'s `BulkReassignToolbar` (399-417) — same `Select`/`SelectTrigger`/`SelectContent`/`SelectItem`/`SelectValue` import set already in use elsewhere in the app, no new shadcn component needed (confirmed by UI-SPEC line 24, 28, 164).

**Analog for the trigger/error/loading-state local-state shape:** `CharacterPreviewRow` (41-181) in this same file — `isTriggeringPreview`/`error`/`setError` local state, `errorMessage(err, "fallback copy")` helper, and the `<p className="text-xs text-destructive" role="alert">{error}</p>` inline-error markup are the exact conventions the new `swapError` state and D-02 error rendering must match:
```tsx
const [error, setError] = useState<string | null>(null)
...
} catch (err) {
  setError(errorMessage(err, "Couldn't stop the preview."))
} finally {
  ...
  onRefresh()
}
```
→ The Model swap handler follows the identical shape: `setIsSwapping(true)`, `try { await loadModel(...); onRefresh() } catch (err) { setSwapError(errorMessage(err, "Couldn't switch models.")) } finally { setIsSwapping(false) }`.

**Existing hardcoded value being replaced** (line 20-22, 280):
```tsx
const TTS_MODEL_DISPLAY_NAME = "Qwen3-TTS-12Hz-1.7B-CustomVoice"
...
<ConfigField label="Model" value={TTS_MODEL_DISPLAY_NAME} />
```
→ Delete this constant and its `ConfigField` row entirely; UI-SPEC §1 supplies the exact replacement block (a `Select` + conditional warning `<p>` + conditional error `<p>`).

**`generationLocked` prop threading:** already a prop on `ConfigPanelProps` (line 188) and consumed by `CharacterPreviewRow`'s `disabled={... || generationLocked}` (line 142) and `Generate All`'s `disabled={isRunning}` (line 310, where `isRunning = isSelfRunning || generationLocked`, line 223) — per UI-SPEC's explicit instruction (line 128), do NOT add a second `isModelSwapping` prop; the existing `generationLocked` (driven by the backend's single-flight lock, which the model-load claims under its own label) already covers Generate/preview disabling for free.

---

### `frontend/src/components/SegmentTable.tsx` — `EditableTextCell` disabled prop

**Analog:** the function itself (318-366) — smallest possible diff, add one `disabled`/`title` prop pair to the existing `<Textarea>`.

**Binding source:** UI-SPEC §"Component Contracts" §2 (lines 130-149) — exact diff:
```tsx
<Textarea
  aria-label={`${label} for segment ${segment.order + 1}`}
  value={value}
  onChange={(e) => setValue(e.target.value)}
  onBlur={handleBlur}
  disabled={field === "voice_instructions" && project.tts_model === "0.6b"}
  title={
    field === "voice_instructions" && project.tts_model === "0.6b"
      ? "Voice instructions have no effect while Faster (0.6B) is active."
      : undefined
  }
  className="min-h-16 bg-background text-sm"
/>
```
No new CSS — `frontend/src/components/ui/textarea.tsx`'s existing `disabled:` variant (`disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50`) already covers the visual treatment (UI-SPEC line 148). `EditableTextCell` needs `project.tts_model` threaded down as a new prop from wherever it's called (line ~490) — the call site already passes `segment`/`field`/`label`/`onSegmentChange`; add `project` (or just `ttsModel: string`) alongside those, smallest-diff addition per UI-SPEC line 149.

---

## Shared Patterns

### Single-flight generation lock
**Source:** `backend/app/generation_worker.py` lines 64-79 (`try_claim_generation`/`release_generation`)
**Apply to:** `backend/app/main.py`'s new `POST /projects/{id}/model` handler — claim under label `f"model-load:{model_id}"` before calling `tts_client.load_model`, release in both success and failure paths (mirror the `try_claim_generation(f"segment:{segment_id}")` / `release_generation()` pairing used at lines 960-968).
```python
if not try_claim_generation(label):
    raise HTTPException(status_code=409, detail="Another generation is already in progress")
try:
    await run_in_threadpool(tts_client.load_model, body.model_id)
except Exception as exc:
    release_generation()
    raise HTTPException(status_code=502, detail=f"model load failed: {exc}") from exc
```

### Invalidate-then-unlink-after-commit ordering
**Source:** `backend/app/main.py`'s `patch_character` (407-444) and `patch_segment` (747-806)
**Apply to:** the swap handler's project-wide segment (and, if adopted, preview) invalidation loop — clear DB fields inside the `with Session(engine)` block, commit, THEN unlink files outside the session, exactly as both existing PATCH handlers already do. Never unlink before commit (a mid-transaction crash would leave the DB pointing at a deleted file).

### Inline destructive-vs-informational error styling
**Source:** every existing inline error in `ConfigPanel.tsx`/`SegmentTable.tsx` (`batchError`, `CharacterPreviewRow`'s `error`, `EditableTextCell`'s `error`) — `<p className="text-xs text-destructive" role="alert">{message}</p>`
**Apply to:** D-02's `swapError` message. D-03's persistent warning note is deliberately styled differently (`text-muted-foreground`, not `text-destructive` — per UI-SPEC's explicit color-contract reasoning, lines 70-72) — do not reuse the destructive-red pattern for the warning note, only for the actual failure message.

### `errorMessage(err, fallback)` client-error helper
**Source:** `frontend/src/api/client.ts`'s `errorMessage` (imported and used throughout `ConfigPanel.tsx`, e.g. line 256, 269)
**Apply to:** the new `loadModel`/model-swap API call's catch block, same as every other mutation in this file.

## No Analog Found

None — every file this phase touches is a modification to an existing module with a directly-applicable in-file or same-directory precedent.

## Metadata

**Analog search scope:** `backend/tts_service/`, `backend/app/`, `frontend/src/components/` — the exact directories RESEARCH.md's "Recommended Project Structure" names as touched by this phase.
**Files scanned:** `model.py`, `server.py`, `cache_key.py`, `models.py`, `tts_client.py`, `generation_worker.py`, `main.py`, `ConfigPanel.tsx`, `SegmentTable.tsx`
**Pattern extraction date:** 2026-07-14
