---
phase: 05-on-demand-model-swap
verified: 2026-07-14T12:46:32Z
status: passed
score: 12/12 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 5: On-Demand Model Swap Verification Report

**Phase Goal:** User can pick between two Qwen TTS model sizes per project, and the app safely swaps the resident model in VRAM on demand, warning about the smaller model's steering limitation.
**Verified:** 2026-07-14T12:46:32Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (merged from ROADMAP success criteria + all 3 plans' must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Calling `tts_service`'s `/model/{id}/load` swaps the resident checkpoint, only one model resident at a time | ✓ VERIFIED | `backend/tts_service/model.py::ensure_loaded` — `del model` + `gc.collect()` + `torch.cuda.empty_cache()` before `from_pretrained` of the new checkpoint; route wired in `server.py:154-180`. Real-hardware VRAM-cycle test (`test_model_swap_hardware.py`) already proven per prior execution; `model.py` untouched by the later review-fix commit, so that result still holds. |
| 2 | A fresh load re-applies Phase 4's StoppingCriteria cancel monkeypatch | ✓ VERIFIED | `ensure_loaded` calls `_apply_stopping_criteria_patch(new_model)` on every load (`model.py:203`); patch closures rebind to the fresh instance each time. |
| 3 | Repeated swap cycles leave free VRAM stable (no fragmentation drift) | ✓ VERIFIED | `backend/tts_service/tests/test_model_swap_hardware.py` exists, syntactically valid, gated on `torch.cuda.is_available()`; prior real-hardware run (10-12 cycles) reported zero drift per-model-id; code path unmodified since. |
| 4 | Unknown `model_id` rejected with 422, never reaches `from_pretrained` | ✓ VERIFIED | `ensure_loaded` raises `ValueError` before touching `from_pretrained`; `server.py`'s route returns 422 for `model_id not in MODEL_CHOICES`; `main.py`'s `set_project_model` independently validates too (422, defense in depth). |
| 5 | Each project remembers its chosen model and that id flows into the cache key so a swap can't serve stale cross-model audio | ✓ VERIFIED | `Project.tts_model: str = "1.7b"` (`models.py:30`); `compute_cache_key(..., model_id)` — differing `model_id` verified to differ digest by `__main__` self-check and unit tests; `regenerate_segment` passes `project.tts_model` into the cache key (`main.py:988-990`). |
| 6 | `POST /projects/{id}/model` claims the lock, triggers the swap, and invalidates every segment + character preview on success | ✓ VERIFIED | `main.py:355-461` — claims `model-load:{id}` via `try_claim_generation`, calls `tts_client.load_model` in a threadpool, on success loops all `Segment`s (clears `audio_path`+`cache_key`, bumps `generation_version`, sets `pending`) and all `Character`s (clears `preview_audio_path`), unlinks old files post-commit, releases lock in `finally`. |
| 7 | A failed load leaves the project row, cached audio, and previews untouched (D-02) and releases the lock | ✓ VERIFIED | Exception from `tts_client.load_model` raises `HTTPException(502)` before any DB mutation; `try/finally` (code-review WR-01 fix) guarantees `release_generation()` fires even on an unexpected exception later in the critical section. Confirmed by `test_failed_load_leaves_project_untouched_and_releases_lock` (passing). |
| 8 | A no-op swap request (same model already resident) does not destructively invalidate audio | ✓ VERIFIED | Code-review CR-02 fix: `set_project_model` returns early (before claiming the lock) when `project.tts_model == body.model_id`. Confirmed by `test_noop_swap_to_already_resident_model_does_not_invalidate` (passing) — asserts `load_model` never called, segment/character audio and `cache_key`/`generation_version` untouched. |
| 9 | Generation (segment, batch, preview) reconciles the resident tts_service model with the *current* project's `tts_model` before every synth call, not just at swap time | ✓ VERIFIED | Code-review CR-01 fix: `regenerate_segment` (`main.py:1010-1016`) and `_generate_preview` (`main.py:606-608`) both call `await run_in_threadpool(tts_client.load_model, model_id)` immediately before `synthesize`, no-op if already resident. `run_batch_generation` calls `regenerate_segment` per segment, so batch is covered too. Confirmed by `test_generate_segment_reconciles_resident_model_before_synth` (passing). |
| 10 | The project payload exposes `tts_model` so the UI can drive the dropdown | ✓ VERIFIED | `_serialize_project` includes `"tts_model": project.tts_model` (`main.py:255`, confirmed via grep). |
| 11 | Config Panel shows a Model dropdown with verbatim labels bound to project server state; picking a model fires the load immediately with a spinner, and reverts on failure with an inline error (CFG-04, D-01/D-02) | ✓ VERIFIED | `ConfigPanel.tsx` `Select` bound to `project.tts_model`, `onValueChange={handleModelChange}`, `disabled={isSwapping}`, spinner + "Switching model…" label while swapping, `swapError` rendered `text-destructive role="alert"` matching the D-02 copy contract verbatim; `handleModelChange` never mutates `project.tts_model` optimistically — the value is server state, so failure-revert is automatic on refetch. |
| 12 | While 0.6B is active a persistent, non-dismissible note warns steering is unsupported (CFG-05) | ✓ VERIFIED | `project.tts_model === "0.6b"` conditionally renders the exact UI-SPEC copy in `text-muted-foreground` with a `TriangleAlert` icon, no dismiss state/handler exists. REQUIREMENTS.md's locked CFG-05 text is "the UI warns the user that free-text voice-instruction steering is not supported" — satisfied by this note regardless of per-cell disabling (see Requirements Coverage below for the D-04 deferral assessment). |

**Score:** 12/12 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/tts_service/model.py::ensure_loaded` | swap machinery | ✓ VERIFIED | Present, matches Plan 01 exactly; `ruff check` clean |
| `backend/tts_service/model.py::MODEL_CHOICES` | 2-entry id→repo dict | ✓ VERIFIED | `{"1.7b": ..., "0.6b": ...}` |
| `backend/tts_service/server.py POST /model/{model_id}/load` | validated, `_ready`-gated route | ✓ VERIFIED | 422/503/500/200 branches all present |
| `backend/tts_service/tests/test_model_swap_hardware.py` | GPU-gated swap test | ✓ VERIFIED | File present, syntactically valid, GPU-gated |
| `backend/app/models.py::Project.tts_model` | default `"1.7b"` column | ✓ VERIFIED | Confirmed via grep |
| `backend/app/cache_key.py::compute_cache_key` (model_id param) | required param, `TTS_MODEL_VERSION` removed | ✓ VERIFIED | Confirmed via source + passing self-check |
| `backend/app/tts_client.py::load_model` | mock/http/unknown 3-way, raises on failure | ✓ VERIFIED | Confirmed via source + `test_tts_client_load_model.py` (5 tests passing) |
| `backend/app/main.py POST /projects/{project_id}/model` | lock-gated swap handler | ✓ VERIFIED | Confirmed, includes CR-01/CR-02/WR-01 fixes |
| `frontend/src/api/client.ts::setProjectModel` + `Project.tts_model` | mutation + type field | ✓ VERIFIED | Confirmed via grep |
| `frontend/src/components/ConfigPanel.tsx` Model Select + warning + error | UI surfaces | ✓ VERIFIED | Confirmed via source, matches UI-SPEC copy verbatim |
| `frontend/src/components/SegmentTable.tsx EditableTextCell disabled prop` (D-04) | disabled cells on 0.6B | ⚠️ NOT IMPLEMENTED (documented no-op, see below) | Voice Instructions column does not exist in current `SegmentTable.tsx` (removed in `fc9184a`, prior to this phase); confirmed by grep — only `field: "text"` is wired to `EditableTextCell`, no `voice_instructions` call site exists to disable |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `server.py` lifespan startup | `ensure_loaded(default)` | direct call | ✓ WIRED | `await run_in_threadpool(model_module.ensure_loaded, DEFAULT_MODEL_ID)` before `_ready = True` |
| `ensure_loaded` | `_apply_stopping_criteria_patch` | direct call | ✓ WIRED | Called on every successful load |
| `regenerate_segment` | `compute_cache_key` | `project.tts_model` param | ✓ WIRED | Confirmed at `main.py:988-990` |
| `regenerate_segment` / `_generate_preview` | `tts_client.load_model` | reconciliation call before synth (CR-01 fix) | ✓ WIRED | Confirmed at both call sites; batch generation routes through `regenerate_segment` |
| `_serialize_project` | `tts_model` field | dict key | ✓ WIRED | Confirmed |
| `set_project_model` | GEN-03's per-row invalidation pattern | project-wide loop | ✓ WIRED | Confirmed, extended to also clear `cache_key` and `Character.preview_audio_path` |
| ConfigPanel `Select` | `project.tts_model` (server state) | `value={project.tts_model}` | ✓ WIRED | D-02 revert-on-failure works automatically because no optimistic local state is used |
| `generationLocked` (existing lock hook, `useGenerationLock`) | Generate/preview controls | shared process-wide `try_claim_generation` lock | ✓ WIRED | Confirmed: `model-load:{id}` claims the same lock `useGenerationLock`'s `/generation-status` polling reflects, so Generate All/per-row/preview disable during a swap with no new prop |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backend unit test suite (model-swap + generation subset) | `uv run pytest tests/test_model_swap.py tests/test_generation.py -q` | 28 passed | ✓ PASS |
| Full backend test suite (regression check) | `uv run pytest -q` | 100 passed, 1 pre-existing unrelated failure (`test_upload_returns_valid_wav_with_multiple_chunks_joined`, a 201-vs-200 status assertion, confirmed pre-existing via `git stash` per Plan 02's SUMMARY and independently reproduced here), 1 skipped | ✓ PASS (no regression introduced) |
| `ruff check .` (backend) | `cd backend && uv run ruff check .` | "All checks passed!" | ✓ PASS |
| `npx tsc --noEmit` (frontend) | `cd frontend && npx tsc --noEmit` | no output / exit 0 | ✓ PASS |
| CR-01 regression test (reconciliation before synth) | `pytest -k test_generate_segment_reconciles_resident_model_before_synth` | pass (part of full run above) | ✓ PASS |
| CR-02 regression test (no-op swap doesn't invalidate) | `pytest -k test_noop_swap_to_already_resident_model_does_not_invalidate` | pass (part of full run above) | ✓ PASS |
| Live backend health/data check on deploy pod | `curl localhost:8000/healthz`, `curl localhost:8000/projects` | 200s, real project data returned | ✓ PASS |
| `qwen-ebook-tts` / `qwen-ebook-backend` containers running current code | `podman ps` | Both `Up 3 minutes` on `localhost/qwen-ebook-*:dev` images | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CFG-04 | 05-01, 05-02, 05-03 | User can choose between two Qwen TTS model sizes per project, loaded on demand, only one resident in VRAM | ✓ SATISFIED | All 3 plans' artifacts verified above; REQUIREMENTS.md traceability table already marks this `Complete` |
| CFG-05 | 05-03 | When 0.6B is selected, the UI warns the user that free-text voice-instruction steering is not supported | ✓ SATISFIED | Locked requirement text is specifically "the UI warns the user" — satisfied by the persistent D-03 warning note in `ConfigPanel.tsx`. The `05-CONTEXT.md` D-04 decision ("Voice Instructions fields... grayed out / disabled") was an *additional* UX reinforcement decided during phase discussion, not the literal text of CFG-05 itself. Since the Voice Instructions column doesn't currently exist in `SegmentTable.tsx` (removed pre-phase in `fc9184a`, return locked to Phase 7 / TBL-05), Plan 03's judgment that CFG-05 is satisfied by the warning note alone is sound against the requirement's actual locked wording — REQUIREMENTS.md's traceability table row (`CFG-05 \| Phase 5 \| Pending`) is simply a stale checkbox that was never re-ticked after Phase 5 completed, not evidence of an unmet requirement. |

**Note:** REQUIREMENTS.md itself (`Last updated: 2026-07-13`, before this phase's `2026-07-14` execution) still shows `CFG-05` as `[ ]`/`Pending` in both the requirement list and the traceability table, while `CFG-04` was updated to `[x]`/`Complete`. This is a documentation-sync gap, not a functional gap — recommend the checkbox and traceability row be updated to reflect Phase 5's actual delivery, but this does not block the phase goal, which this verification confirms is achieved in the codebase.

### Anti-Patterns Found

None. Scanned all phase-touched files (`backend/app/main.py`, `models.py`, `cache_key.py`, `tts_client.py`, `backend/tts_service/model.py`, `server.py`, `frontend/src/api/client.ts`, `frontend/src/components/ConfigPanel.tsx`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/stub patterns — zero matches.

### Code Review Findings — Fix Verification (not trusting the commit message)

All 4 findings from `05-REVIEW.md` (commit `d675fa4`) were independently re-verified against current source, not just the commit message:

| Finding | Fix Location | Verified |
|---------|--------------|----------|
| CR-01 (no resident-model reconciliation) | `regenerate_segment` (`main.py:1010-1016`), `_generate_preview` (`main.py:606-608`) | ✓ Both call `tts_client.load_model(model_id)` immediately before `synthesize`; `run_batch_generation` routes through `regenerate_segment` so batch is covered. Regression test passing. |
| CR-02 (no-op swap destructively invalidates) | `set_project_model` (`main.py:376-385`) | ✓ Early return before lock claim when `project.tts_model == body.model_id`. Regression test passing. |
| WR-01 (lock can wedge on unexpected exception) | `set_project_model` (`main.py:401-461`) | ✓ Post-load critical section now wrapped in `try/finally`, `release_generation()` in `finally`. |
| WR-02 (preview spinner can stick forever) | `ConfigPanel.tsx` (`CharacterPreviewRow`, lines ~83-91) | ✓ Poll-ceiling `setTimeout` now also calls `setIsTriggeringPreview(false)` and sets an error message. |

### Human Verification Required

None. Task 3's `checkpoint:human-verify` gate was already completed and approved by the human operator on the real RX 9070 XT deploy target (per `05-03-SUMMARY.md`), and the deploy pod has been rebuilt twice since (once for Plan 03's frontend changes, once for the review-fix commit) and is confirmed running and healthy at verification time (`podman ps`, live `curl` checks above). No new UI/runtime surface was introduced by the review-fix commit that wasn't already covered by that human-verify pass or by the new automated regression tests (CR-01/CR-02 are backend-only fixes covered by unit tests; WR-02 is a frontend-only fix whose logic was read directly and matches the intended behavior).

### Gaps Summary

No gaps. The phase goal — a per-project model swap that is safe, cache-correct across all generation paths, and honestly warns about the 0.6B steering limitation — is achieved in the current codebase. The two CRITICAL issues found by code review (cross-project cache misattribution, destructive no-op swap) and both WARNINGs (lock wedge, stuck spinner) are all fixed and covered by passing regression tests or direct source inspection, not just commit-message trust. The one documented deviation (D-04 per-cell disabling deferred to Phase 7/TBL-05) is legitimate — the target UI surface doesn't exist yet — and CFG-05's actual locked requirement text is independently satisfied by the Config Panel warning note alone.

---

*Verified: 2026-07-14T12:46:32Z*
*Verifier: Claude (gsd-verifier)*
