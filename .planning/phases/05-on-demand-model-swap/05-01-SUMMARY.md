---
phase: 05-on-demand-model-swap
plan: 01
subsystem: infra
tags: [pytorch, rocm, qwen-tts, fastapi, model-swap, vram]

# Dependency graph
requires: []
provides:
  - "tts_service.model.ensure_loaded(model_id) — swaps the resident Qwen3-TTS checkpoint under a lock, deleting the old one before loading the new one"
  - "tts_service.model.MODEL_CHOICES — the two supported checkpoint ids (1.7b/0.6b) and their HF repos"
  - "POST /model/{model_id}/load on tts_service — allowlist-validated, _ready-gated swap route"
  - "Real-hardware VRAM swap-cycle test proving zero fragmentation drift over 10 cycles on the RX 9070 XT"
affects: [05-02-model-swap-orchestration, 05-03-model-swap-ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ensure_loaded(model_id) swap pattern: no-op check outside lock, re-check under lock, del+gc.collect+empty_cache, from_pretrained, re-apply per-instance patches, only then update module globals"
    - "Monkeypatch extraction into a function (_apply_stopping_criteria_patch) so a per-process patch survives repeated fresh from_pretrained calls, each capturing the new instance's own methods as closures"

key-files:
  created:
    - backend/tts_service/tests/test_model_swap_hardware.py
  modified:
    - backend/tts_service/model.py
    - backend/tts_service/server.py

key-decisions:
  - "D-07 fallback (unsupported speaker -> DEFAULT_SPEAKER) implemented as an explicit pre-check in synthesize_wav rather than relying on qwen-tts's own _validate_speakers ValueError — matches the plan's literal instruction; RESEARCH.md Pitfall 3 confirms the 1.7B/0.6B rosters are identical today so this never fires in practice, it's insurance against a future smaller checkpoint."
  - "VRAM-stability test compares free VRAM per model_id (own baseline) rather than across all swaps globally, since the two checkpoints have different resident footprints by design (~4.3GB vs ~2.3GB per RESEARCH.md) — a global baseline would false-positive on every swap between differently-sized checkpoints."
  - "Test file lives at backend/tts_service/tests/ (not backend/tests/) since tts_service is a separate GPU-only Python environment (own requirements.txt, only runs inside the Containerfile.tts image) — it cannot be collected by backend's uv-managed pytest run, and was executed inside the actual localhost/qwen-ebook-tts:dev container against the real RX 9070 XT instead."

requirements-completed: [CFG-04]

coverage:
  - id: D1
    description: "ensure_loaded(model_id) replaces the import-time singleton; importing tts_service.model no longer loads a model"
    requirement: "CFG-04"
    verification:
      - kind: other
        ref: "podman run localhost/qwen-ebook-tts:dev python -c \"import tts_service.model as m; assert m._loaded_model_id is None\" — printed 'OK: import check passed'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Repeated swap cycles leave free VRAM stable (no fragmentation drift) — closes STATE.md's Phase 5 exit criterion"
    requirement: "CFG-04"
    verification:
      - kind: other
        ref: "backend/tts_service/tests/test_model_swap_hardware.py::test_swap_cycle_vram_is_stable_and_single_model_resident — run inside the real GPU container (10 swaps, 3 tests passed in 72.98s)"
        status: pass
    human_judgment: false
  - id: D3
    description: "ensure_loaded rejects an unknown model_id with ValueError before it can reach from_pretrained (T-05-01); POST /model/{model_id}/load returns 422 for the same case"
    requirement: "CFG-04"
    verification:
      - kind: other
        ref: "test_model_swap_hardware.py::test_ensure_loaded_rejects_unknown_model_id (pass) + live curl POST /model/bogus/load -> 422 'unknown model_id 'bogus'', healthz stayed 200"
        status: pass
    human_judgment: false
  - id: D4
    description: "A fresh model load re-applies the Phase 4 StoppingCriteria cancel monkeypatch so cancellation still works after a swap"
    requirement: "CFG-04"
    verification:
      - kind: other
        ref: "test_model_swap_hardware.py::test_ensure_loaded_reapplies_cancel_patch_after_swap (pass) — asserts the fresh instance's patched talker.generate is a distinct bound method from the prior instance's"
        status: pass
    human_judgment: false
  - id: D5
    description: "POST /model/{model_id}/load flips _ready False during the swap and True in both success and failure branches; startup loads the 1.7B default via ensure_loaded"
    requirement: "CFG-04"
    verification:
      - kind: other
        ref: "live smoke test against localhost/qwen-ebook-tts:dev on the real RX 9070 XT: healthz 200 after 6s startup, POST /model/0.6b/load -> 200 in 4.9s (mem_get_info logged 7196MB -> 11308MB free after unload), healthz 200 after, real /synthesize call against the swapped 0.6B model returned a 203KB valid WAV"
        status: pass
    human_judgment: false

# Metrics
duration: 14min
completed: 2026-07-14
status: complete
---

# Phase 5 Plan 01: Model swap engine (ensure_loaded + load route) Summary

**`ensure_loaded(model_id)` swap machinery in `tts_service/model.py` plus a validated `POST /model/{model_id}/load` route, both proven live on the real RX 9070 XT with zero VRAM drift over 10 swap cycles.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-14T13:48Z
- **Completed:** 2026-07-14T14:02Z
- **Tasks:** 2/2 completed
- **Files modified:** 3 (2 modified, 1 created)

## Accomplishments
- Replaced `tts_service/model.py`'s import-time `Qwen3TTSModel.from_pretrained(...)` singleton with `ensure_loaded(model_id)` — a lock-guarded, no-op-if-already-resident swap function implementing the exact 7-step sequence from RESEARCH.md Pattern 1 (recheck-under-lock, del, gc.collect, empty_cache, from_pretrained, re-apply patch, re-derive DEFAULT_SPEAKER).
- Extracted the Phase 4 talker/speech_tokenizer StoppingCriteria monkeypatch into `_apply_stopping_criteria_patch(model_instance)` so it re-applies to every freshly loaded instance — verified the patched `talker.generate` is a genuinely new closure after each swap, not a stale reference.
- Added the D-07 defensive speaker fallback in `synthesize_wav`: a resolved speaker not in the resident model's `get_supported_speakers()` now falls back to `DEFAULT_SPEAKER` with a log line, instead of erroring.
- Wrote `backend/tts_service/tests/test_model_swap_hardware.py`, a GPU-gated pytest suite run against the real production RX 9070 XT container: 10 alternating swap cycles show zero free-VRAM drift (within a 64MB tolerance) per model_id, unknown-id rejection, and cancel-patch re-application — all 3 tests pass in ~73s.
- Added `POST /model/{model_id}/load` to `tts_service/server.py`: 503 if the service hasn't started, 422 on an unknown model_id (allowlist defense-in-depth, T-05-01), `_ready=False` for the swap's duration (T-05-02), `_ready=True` in both success and failure branches (D-02: a failed swap leaves the previously-resident model intact and the service usable).
- Updated `lifespan` to call `ensure_loaded("1.7b")` at startup instead of relying on model.py's old import-time load.
- Verified the whole flow live: rebuilt `localhost/qwen-ebook-tts:dev`, ran it with real `/dev/kfd`+`/dev/dri` passthrough on the production GPU, confirmed startup load, a rejected unknown-id swap, a real 0.6B swap (4.9s, VRAM logged), and a real `/synthesize` call against the swapped model returning valid audio.

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace the model.py singleton with ensure_loaded(model_id) + swap machinery** - `c8e65c5` (feat)
2. **Task 2: Add POST /model/{model_id}/load route + startup default load in server.py** - `798d06e` (feat)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `backend/tts_service/model.py` - import-time singleton replaced with `ensure_loaded(model_id)`, `MODEL_CHOICES`, `_pick_default_speaker`, `_apply_stopping_criteria_patch`, D-07 speaker fallback in `synthesize_wav`
- `backend/tts_service/server.py` - `lifespan` calls `ensure_loaded("1.7b")` at startup; new `POST /model/{model_id}/load` route
- `backend/tts_service/tests/test_model_swap_hardware.py` - GPU-gated real-hardware swap-cycle test (new file)

## Decisions Made
- D-07 fallback implemented as a literal pre-check (`if chosen_speaker not in model.get_supported_speakers(): chosen_speaker = DEFAULT_SPEAKER`) per the plan's explicit instruction, rather than relying on `generate_custom_voice`'s own validation-by-exception. Confirmed via RESEARCH.md Pitfall 3 that this doesn't currently change observable behavior (both checkpoints' rosters are identical) — it's forward-looking insurance, not a functional change today.
- The hardware test measures VRAM stability per-model-id (own baseline) rather than globally across all swaps, since 1.7B and 0.6B have genuinely different resident footprints by design — a global baseline would incorrectly flag every swap between different-sized checkpoints as "drift." This surfaced as a real test bug during execution (see Deviations) and was fixed before commit.
- `MODEL_CHOICES` kept as the flat 2-entry dict RESEARCH.md specifies — no generic model registry (explicit anti-pattern in RESEARCH.md, reaffirmed here).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] First draft of the VRAM-stability test compared free VRAM across differently-sized checkpoints**
- **Found during:** Task 1, first real-hardware pytest run
- **Issue:** The initial test tracked one running `free_after_unload_mb` list across all 10 swaps and compared every reading to swap-1's baseline. Since the 1.7B and 0.6B checkpoints have different resident footprints (~4.3GB vs ~2.3GB per RESEARCH.md), alternating between them produced a real ~1.9GB reading difference that the test misreported as "VRAM drift" — it was actually a false positive caused by comparing two different model sizes, not fragmentation.
- **Fix:** Restructured the test to track free-VRAM readings in a `dict[model_id, list[float]]`, comparing each model_id's readings only against that same model_id's own first reading. This correctly isolates "did repeated loads of the SAME checkpoint size leave stable free VRAM" from "these two checkpoints have different footprints," matching RESEARCH.md Pitfall 2's own methodology (which always measured free VRAM at the same point — immediately after unload — for a like-for-like comparison).
- **Files modified:** `backend/tts_service/tests/test_model_swap_hardware.py`
- **Verification:** Re-ran the full test suite inside the real GPU container — all 3 tests pass (10 swap cycles, zero drift within tolerance per model_id).
- **Committed in:** `c8e65c5` (Task 1 commit — fixed before the task was committed, not a separate commit)

---

**Total deviations:** 1 auto-fixed (1 bug, in test code written this session — not a bug in the shipped `ensure_loaded` swap machinery)
**Impact on plan:** No scope creep; the fix corrected the test's own measurement methodology to match RESEARCH.md's proven approach. The underlying `ensure_loaded` swap logic was correct on the first pass — the bug was entirely in how the test interpreted the readings.

## Issues Encountered
- `backend`'s `uv`-managed Python environment has no `torch`/`qwen_tts` installed (by design — `tts_service` is an isolated GPU-only dependency set per `CLAUDE.md`/`tts_service/requirements.txt`'s own header comment). The plan's `uv run pytest tts_service/tests/...` verify command as literally written cannot execute in that environment. Resolved by running the equivalent check inside the real `localhost/qwen-ebook-tts:dev` container (rebuilt from the current worktree code) with `/dev/kfd`+`/dev/dri` passthrough on the actual production RX 9070 XT — this is a stricter verification than the plan's literal command, not a weaker one, since it exercises the real GPU path end to end.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `ensure_loaded(model_id)` and `MODEL_CHOICES` are ready for Plan 02 (backend orchestration: `POST /projects/{id}/model`, cache-key threading, segment invalidation) and Plan 03 (Config Panel UI) to build against.
- The `POST /model/{model_id}/load` route's response contract (200/422/500/503) matches RESEARCH.md's drop-in shape exactly, so Plan 02's `tts_client.load_model()` helper can be written directly against it.
- Pitfall 4 (character preview audio not covered by segment invalidation) is still an open scope question for Plan 02 — not addressed in this plan, flagged here per RESEARCH.md's recommendation that the planner decide explicitly rather than this plan resolving it unilaterally.

---
*Phase: 05-on-demand-model-swap*
*Completed: 2026-07-14*
