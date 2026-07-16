---
phase: 05-on-demand-model-swap
reviewed: 2026-07-14T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - backend/app/cache_key.py
  - backend/app/main.py
  - backend/app/models.py
  - backend/app/tts_client.py
  - backend/tests/test_model_swap.py
  - backend/tests/test_tts_client_load_model.py
  - backend/tts_service/model.py
  - backend/tts_service/server.py
  - backend/tts_service/tests/test_model_swap_hardware.py
  - frontend/src/api/client.ts
  - frontend/src/components/ConfigPanel.tsx
findings:
  critical: 2
  warning: 2
  info: 2
  total: 6
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-07-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the on-demand TTS model swap feature (CFG-04): `POST /projects/{id}/model`,
`tts_client.load_model`, `tts_service`'s `ensure_loaded`/`/model/{id}/load`, the
per-segment cache-key that now includes `model_id`, and the ConfigPanel model
Select UI. The single-flight-lock discipline, D-02 revert-on-failure path, and
VRAM-stability hardware test are all solid and well covered by tests. However,
the feature has a systemic design gap that undermines its own stated goal
("a swap in one project can't silently affect another's cache correctness"):
nothing in the generation path ever re-synchronizes the tts_service's globally
resident model with the *current* project's `tts_model` before synthesizing —
`tts_client.load_model` is called from exactly one call site in the whole
backend (`set_project_model`). Combined with a missing no-op guard on redundant
swaps, this is a correctness/data-loss risk that should block shipping as-is.

## Critical Issues

### CR-01: No resident-model reconciliation before generation — cache key can misrepresent which model actually produced the audio

**File:** `backend/app/main.py:935-964` (also `backend/app/generation_worker.py` batch loop, and `_generate_preview` at `backend/app/main.py:556-590`)
**Issue:**

`tts_service` holds exactly **one** resident model process-wide (`tts_service/model.py`'s `model`/`_loaded_model_id` globals). `Project.tts_model` is a **per-project** field, and the whole point of Phase 5 (per `models.py`'s own comment) is: "a swap in one project can't silently affect another's cache correctness." But `tts_client.load_model()` — the only function that actually changes which checkpoint is resident — is called from exactly one place in the entire backend:

```
$ grep -rn "load_model\|ensure_loaded" backend/app/ | grep -v test
backend/app/tts_client.py:90:def load_model(model_id: str) -> None:
backend/app/main.py:386:        await run_in_threadpool(tts_client.load_model, body.model_id)
```

`regenerate_segment` (main.py:935-964), `run_batch_generation` (generation_worker.py, which calls `regenerate_segment`), and `_generate_preview` (main.py:556-590) all call `tts_client.synthesize(...)` directly — none of them first ensure the resident model matches `project.tts_model`. They *do* read `project.tts_model` for the cache-key computation (`regenerate_segment` line 963: `model_id = project.tts_model if project else "1.7b"`), but the actual audio is produced by whatever checkpoint happens to be resident in `tts_service` at that moment — which may be a different project's model.

Concrete failure sequence:
1. Project A and Project B both default to `tts_model = "1.7b"`.
2. User opens Project A, switches its model to `"0.6b"` via the Config Panel. `POST /projects/A/model` swaps the tts_service-resident model to 0.6B and sets `Project A.tts_model = "0.6b"`.
3. User switches to Project B (still `tts_model = "1.7b"`, never touched) and clicks "Generate All".
4. `regenerate_segment` computes `cache_key` using `model_id = "1.7b"` (Project B's stored value) and writes that into `segment.cache_key`/DB — but the actual `synthesize()` call goes out to tts_service, which currently has **0.6B** resident (left over from step 2). Project B's segments are synthesized with the wrong (0.6B) model, no error is raised, and the persisted cache key falsely claims 1.7B was used.

This silently produces audio from an unrequested model and poisons the cache-key invariant the whole cache design (`cache_key.py`) depends on — a future no-op cache hit on Project B would "confirm" 1.7B was used when it wasn't.

**Fix:** Before synthesizing for any project (segment generate, batch generate, and character preview), reconcile the resident model with that project's `tts_model` — e.g. call `tts_client.load_model(project.tts_model)` (which is already a no-op in `tts_service.model.ensure_loaded` when the requested id is already resident) at the top of `regenerate_segment`/`_generate_preview`/`run_batch_generation`'s per-project entry point, inside the same generation-lock critical section:

```python
model_id = project.tts_model if project else "1.7b"
await run_in_threadpool(tts_client.load_model, model_id)  # no-op if already resident
cache_key = compute_cache_key(speaker, merged_instructions, segment.text, model_id)
```

---

### CR-02: `set_project_model` invalidates every segment and character preview even when swapping to the already-resident model

**File:** `backend/app/main.py:356-447`
**Issue:** `set_project_model` has no guard for `body.model_id == project.tts_model`. It always calls `tts_client.load_model` (a no-op on the tts_service side when already resident — see `tts_service/model.py:174-175`, "already resident — no-op, matches D-01's 'swap only on real change'"), but the *backend* endpoint unconditionally proceeds to bump `generation_version` on every segment, clear every `audio_path`/`cache_key`, and delete every character's `preview_audio_path` file (main.py:407-429) — regardless of whether anything actually changed.

This directly contradicts the "swap only on real change" principle the tts_service layer itself documents and enforces one layer down. A no-op swap request (e.g. a duplicate submit, a race between two rapid UI interactions, or a direct API call) wipes out every previously-generated segment's audio and every character preview for no reason, forcing a full, costly re-generation of the whole project.

Not covered by any existing test — `test_model_swap.py`'s `test_swap_invalidates_segments_and_previews` only exercises `"1.7b" -> "0.6b"` (a genuine change).

**Fix:**
```python
with Session(engine) as session:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.tts_model == body.model_id:
        # No-op swap — nothing to invalidate, nothing to load.
        return _serialize_project(project, ..., ...)
```
placed before the `try_claim_generation` call (so it doesn't even need the lock), or at minimum before the invalidation loop.

## Warnings

### WR-01: `set_project_model`'s critical section can permanently wedge the global generation lock

**File:** `backend/app/main.py:385-446`
**Issue:** Every other lock-holding code path in this file (`generate_segment`, `trigger_character_preview`, `generate_project`) releases the single-flight lock via a background task's `add_done_callback` (`_spawn_claimed_generation`, main.py:79-101), which asyncio guarantees to run whether the task succeeds, fails, or is cancelled. `set_project_model` instead runs synchronously in the request handler and calls `release_generation()` manually at each *known* exit point (load failure, project-not-found). It is not wrapped in `try`/`finally`, so any *unexpected* exception between the successful `load_model` call and the final `release_generation()` — a SQLite write conflict during `session.commit()`, an `OSError` from one of the `Path(path).unlink(missing_ok=True)` calls (e.g. a permission problem, or `path` unexpectedly pointing at a directory), or an error inside `_serialize_project` — leaves `_active_generation_label` permanently set. Since this is a single, process-wide lock, that failure mode blocks *every* generation action (segment generate, batch generate, character preview, and future swaps) app-wide until the backend process is restarted.

**Fix:** Wrap the post-load critical section in `try`/`finally`:
```python
try:
    with Session(engine) as session:
        ...
        result = _serialize_project(project, characters, segments)
    for path in old_paths:
        Path(path).unlink(missing_ok=True)
    return result
finally:
    release_generation()
```

### WR-02: Character preview "Generate" spinner can get stuck forever with no recovery path

**File:** `frontend/src/components/ConfigPanel.tsx:70-111`
**Issue:** `isGeneratingPreview = isTriggeringPreview && !hasPreview` drives both the spinner and the poll loop (lines 81-89). If preview generation genuinely fails server-side, `main.py`'s `_generate_preview` (lines 583-590) swallows the exception, logs it, and returns — leaving `preview_audio_path` `null` forever, with no error surfaced anywhere the client can observe. The poll loop's own ceiling (`GENERATION_POLL_CEILING_MS`, line 84) only does `clearInterval(interval)` in the `setTimeout` callback; it never resets `isTriggeringPreview`. Net effect: `isGeneratingPreview` stays `true` indefinitely, the "Generate preview" button is permanently replaced by a spinning `Loader2`+`Stop` pair, `onRefresh` polling has silently stopped, and there is no error message or way to retry short of a full page reload.

**Fix:** In the `setTimeout` callback (or via a ref-tracked "gave up" flag), also call `setIsTriggeringPreview(false)` and surface a timeout error, e.g.:
```tsx
const timeout = setTimeout(() => {
  clearInterval(interval)
  setIsTriggeringPreview(false)
  setError("Preview generation is taking too long — try again.")
}, GENERATION_POLL_CEILING_MS)
```
(requires lifting `setIsTriggeringPreview`/`setError` into the effect's closure, which they already are since it's the same component).

## Info

### IN-01: Cache-key field separator is not strictly collision-proof

**File:** `backend/app/cache_key.py:20-38`
**Issue:** The docstring claims the `\x1f` separator "avoids a crafted voice-instructions string containing a delimiter character... silently colliding two different (character, text) pairs." That's true for printable delimiters like `|`, but a single fixed separator with no length-prefixing is still not injective in general: if any field (e.g. `voice_instructions`, which the LLM/user fully controls) happens to contain a literal `\x1f`, the join can shift a byte-string boundary and produce the same payload for two semantically different `(resolved_speaker, voice_instructions, text, model_id)` tuples, causing a cache-hit false positive (stale audio served for different text/voice). Low real-world likelihood (control character, single-trusted-user app) but worth tightening given the stated invariant.
**Fix:** Length-prefix each field instead of relying purely on a delimiter, e.g. `"".join(f"{len(f)}:{f}" for f in fields)`, or hash each field independently and hash the concatenation of digests.

### IN-02: `MODEL_CHOICES` allowlist duplicated across two modules with different shapes

**File:** `backend/app/main.py:349` vs `backend/tts_service/model.py:29-32`
**Issue:** `main.py` defines `MODEL_CHOICES = {"1.7b", "0.6b"}` (a `set[str]`) purely for request validation; `tts_service/model.py` defines `MODEL_CHOICES: dict[str, str]` (id -> HF repo). Both are explicitly justified in comments as intentional defense-in-depth duplication across the process boundary, which is reasonable — but the two are structurally different types with the same name in two different modules, which is an easy source of confusion if a third model is ever added (must remember to update both, and the "size" contract of each isn't obviously the same). No fix required given the documented 2-model scope; flagging for awareness only.

---

_Reviewed: 2026-07-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
