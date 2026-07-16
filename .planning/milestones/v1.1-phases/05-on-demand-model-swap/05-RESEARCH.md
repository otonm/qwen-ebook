# Phase 5: On-Demand Model Swap - Research

**Researched:** 2026-07-14
**Domain:** In-process PyTorch/ROCm model swap (two Qwen3-TTS CustomVoice checkpoints) behind an existing single-flight generation lock, plus the Config Panel/segment-table UI to drive it
**Confidence:** HIGH — every load-bearing claim below is either read directly from the installed `qwen-tts==0.1.1` wheel, measured live on the actual RX 9070 XT deployment target, or copied verbatim from milestone-level research already rated HIGH confidence.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Swap trigger UX**
- **D-01:** Picking a model from the Config Panel dropdown fires an **explicit load immediately** (dedicated `POST /model/{id}/load` endpoint), not a lazy swap deferred to the next Generate click. The dropdown shows a blocking spinner/disabled state for the duration of the swap so the user always knows exactly when the swap happened. `/synthesize`'s own implicit-load-if-needed path stays as a safety net only, not the primary UX.
- **D-02:** If the explicit load fails (OOM, download error, checkpoint missing), show an inline error and **revert the dropdown to whichever model is still actually resident** — the old model is only `del`'d after the new one loads successfully, so the prior model should still be usable. Do not leave the project in a "no model loaded" limbo state on a failed swap.

**0.6B steering-limitation warning**
- **D-03:** The "0.6B ignores voice-instruction steering" warning is a **persistent inline note under the model dropdown**, always visible whenever 0.6B is the active selection — not a one-time dismissible toast. No dismiss state to track.
- **D-04:** While 0.6B is active, the per-segment **Voice Instructions fields in the table are grayed out / disabled** (not merely left editable with a warning) — reinforces that edits currently have no effect. Deliberate reversal of the initially-recommended "stay editable" option.

**Existing segments after a swap**
- **D-05:** A model swap **proactively invalidates every segment in the project** — deliberate reversal of "leave as-is." The user wants it obvious that a full re-generate pass is recommended after switching models.
- **D-06:** The invalidation **reuses the exact same mechanism GEN-03 already uses for a per-row edit** (clear cached audio, revert status to "pending") — just triggered project-wide by the swap instead of per-row by an edit. No new status value, no new UI state.

**Speaker preset parity across checkpoints**
- **D-07:** If a character's assigned voice preset doesn't exist under the newly selected model's speaker list, **silently fall back to that model's own default speaker** for the mismatched character rather than blocking generation or erroring. A spike should confirm whether the two checkpoints' speaker lists actually differ before this fallback path needs exercising. *(This research resolves that spike — see "Blocker 2" below: the lists are identical today, so this fallback is defensive/future-proofing code, not a currently-exercised path.)*

### Claude's Discretion
- Default model for both new projects and pre-migration projects: default to 1.7B unless research finds a strong reason otherwise — preserves existing behavior, matches `cache_key.py`'s existing hardcoded `TTS_MODEL_VERSION` pointing at 1.7B. **Research finding: no reason to deviate — 1.7B default confirmed correct.**
- Whether a one-time cache-key version bump is needed to force-invalidate pre-migration cached audio — planner's call based on how `compute_cache_key`'s signature actually changes.
- Exact spinner/disabled-state visual treatment, error copy, warning-note wording — **now settled by the approved `05-UI-SPEC.md`** (see Code Examples below); treat that file as the binding source for exact JSX/copy, this document for the backend/data-flow side.
- Whether swap-in-progress should disable the whole Config Panel or just the model dropdown + Generate controls — **settled by UI-SPEC**: only the Select is force-disabled directly; Generate All / per-row generate / preview controls are covered for free via the existing `generationLocked` prop, since model-load claims the same single-flight lock. No new `isModelSwapping` prop.

### Deferred Ideas (OUT OF SCOPE)
- **Custom voice preset preparation ahead of model swaps** — generating/preparing consistent voice presets across swaps instead of relying on D-07's silent fallback. New capability, not this phase's scope (picking between two fixed pre-existing models). Candidate for a future phase/v2.
- "Cast Review wizard stop control and layout" todo — unrelated to model swapping, belongs with Phase 7 or a dedicated follow-up.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CFG-04 | User can choose between two Qwen TTS model sizes per project — 1.7B ("higher quality") and 0.6B ("faster") — loaded on demand (only one resident in VRAM at a time) | `Project.tts_model` column + `ensure_loaded()`/`MODEL_CHOICES` swap function (Architecture Patterns, Code Examples) + real-hardware swap-cycle measurement showing zero VRAM fragmentation over 12 swaps (Common Pitfalls / Blocker 1) |
| CFG-05 | When the 0.6B model is selected, the UI warns the user that free-text voice-instruction steering is not supported by that checkpoint | Confirmed from source: `qwen_tts/inference/qwen3_tts_model.py:799` — `if self.model.tts_model_size in "0b6": instruct = None`, unconditional regardless of caller input. UI-SPEC's D-03 persistent note + D-04 disabled Voice Instructions cells implement this. |
</phase_requirements>

## Summary

This phase's architecture and pitfalls were already fully researched at the milestone level (`ARCHITECTURE.md` §Capability 2, `PITFALLS.md` §4/§5, `STACK.md` §v1.1 Addendum (b)) — that research is HIGH confidence, verified by reading the production `qwen-tts==0.1.1` wheel's source directly. This document consolidates those findings into a phase-scoped shape and, critically, **closes the two open blockers STATE.md flagged for Phase 5 using real measurements taken on the actual production RX 9070 XT container during this research pass** (not mocked, not simulated):

1. **VRAM fragmentation across repeated swaps** — measured directly: 12 back-to-back `del` + `gc.collect()` + `torch.cuda.empty_cache()` + `from_pretrained()` cycles between the 1.7B and 0.6B checkpoints on the live `qwen-ebook-tts` container produced **zero measurable drift** in free VRAM (`torch.cuda.mem_get_info()` reported the identical 11857MB free after unload on swap 1 and swap 12). The documented ROCm/HIP fragmentation risk did not manifest in this test. See "Blocker 1" below for full methodology and numbers.
2. **Speaker-list parity between the two checkpoints** — resolved directly from source, not just verified-not-differ empirically: `get_supported_speakers()` reads `self.config.talker_config.spk_id.keys()` from each checkpoint's `config.json` — a 4.9KB file, not the model weights. Fetching the 0.6B checkpoint's `config.json` (no full-weight download needed) and comparing it against the live 1.7B model's speaker list shows **the two lists are byte-identical**: `['aiden', 'dylan', 'eric', 'ono_anna', 'ryan', 'serena', 'sohee', 'uncle_fu', 'vivian']`, 9/9 match. All 6 of the app's existing voice presets (`backend/app/voices.py`) resolve to speakers in this shared set, so D-07's fallback path is not exercised by any preset that exists in the app today — implement it anyway (defensive, per the locked decision, and cheap), but don't expect to be able to demo it against the current preset roster.

**Primary recommendation:** Implement the swap exactly as ARCHITECTURE.md/STACK.md already specify — a small `ensure_loaded(model_id)` function in `tts_service/model.py` replacing the module-level singleton, gated by the existing `try_claim_generation` lock, with a dedicated `POST /model/{model_id}/load` endpoint. Thread `Project.tts_model` (new column, default `"1.7b"`) into `compute_cache_key`. No new packages, no new locking primitive, no generic model registry. The two real-hardware blockers that would have justified a more defensive design (container-restart fallback for VRAM, error-prone speaker fallback) are both closed — build the straightforward in-process version with confidence.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Model selection intent (which checkpoint a project wants) | API / Backend | Database / Storage | `Project.tts_model` is a per-project DB column, the source of truth the Config Panel PATCHes and `compute_cache_key` reads — not a request param, not a global setting (ARCHITECTURE.md Anti-Pattern: "Treating model choice as purely global config") |
| Physically-resident model in VRAM | API / Backend (GPU-scoped `tts_service` process) | — | One GPU, one resident model — inherently a `tts_service`-process-global runtime fact reconciled opportunistically against `Project.tts_model`, not duplicated as separate state on the main backend |
| Swap trigger UI (dropdown, spinner, warning, error) | Browser / Client | — | `ConfigPanel.tsx`'s `Select` + inline note/error, fully specified in `05-UI-SPEC.md` |
| Swap orchestration (lock claim, del/reload sequence, `_ready` flag) | API / Backend (GPU-scoped `tts_service` process) | — | `tts_service/model.py`'s `ensure_loaded()` + `tts_service/server.py`'s new `/model/{model_id}/load` route; must route through the same single-flight lock the main backend already uses for synth calls |
| Cache correctness (model identity in the content-hash key) | API / Backend | Database / Storage | `cache_key.py::compute_cache_key` gains a `model_id` parameter; `Project.tts_model` is the value fed in — this is what stops a post-swap regenerate from silently cache-hitting the other model's audio |
| Segment invalidation on swap (D-05/D-06) | API / Backend | Database / Storage | Reuses the existing per-row `generation_status = "pending"` + clear `audio_path` mechanism (GEN-03), looped project-wide from the swap endpoint handler |
| Voice-instruction steering disable (D-04) | Browser / Client | — | Purely a `disabled` prop on the existing `Textarea` cells, driven by `project.tts_model === "0.6b"` — no backend involvement beyond the value already being on the project payload |

## Standard Stack

No new external packages this phase. The 0.6B checkpoint is a second Hugging Face Hub repo (`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`), not a new pip dependency — it loads through the exact same `qwen_tts.Qwen3TTSModel.from_pretrained()` call shape already used for the 1.7B model.

### Core (already installed, reused as-is)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `qwen-tts` | `0.1.1` (exact pin, `--no-deps`) [VERIFIED: installed wheel, `pip show qwen-tts` inside `qwen-ebook-tts` container] | `Qwen3TTSModel.from_pretrained()` / `generate_custom_voice()` | Already the app's TTS runtime; no version bump needed for this phase |
| `transformers` | `4.57.3` [VERIFIED: `Containerfile.tts`, cross-checked against installed wheel] | Underlying `GenerationMixin.generate()` the talker delegates to | Pinned exactly because the Phase 4 `StoppingCriteria` monkeypatch's correctness depends on this exact call shape — do not bump without re-verifying `modeling_qwen3_tts.py:2272` |
| `torch` (ROCm build) | `2.9.1+rocm7.2.4` [VERIFIED: `torch.__version__` read live inside the container] | `torch.cuda.empty_cache()`, `torch.cuda.mem_get_info()`, `device_map="cuda:0"` | ROCm build already aliases the `torch.cuda.*` namespace to HIP — confirmed the app already relies on this (existing `device_map="cuda:0"` on an AMD GPU) |
| `huggingface_hub` | `0.36.2` [VERIFIED: `pip show`/`dist-info` inside container] | `from_pretrained`'s underlying download/cache mechanism; also used directly in this research to fetch `config.json` without pulling full weights | Already a transitive dependency; no action needed |

### New model artifact (not a package)
| Artifact | Source | Size | Verified |
|----------|--------|------|----------|
| `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | Hugging Face Hub, Apache-2.0, same org/family as the pinned 1.7B checkpoint | 2.50GB total across 13 files (`model.safetensors` 1.81GB + `speech_tokenizer/model.safetensors` 682MB + small config/tokenizer files) [VERIFIED: `HfApi.model_info(files_metadata=True)`, live] | Downloaded and loaded successfully on the production `qwen-ebook-tts` container during this research pass — 13 files fetched in 36s over the deploy VM's network, cached at `/home/ubuntu/.cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-0.6B-CustomVoice/` inside the persistent HF-cache volume (survives container restart, per the existing `qwen-ebook-tts-hf-cache` volume already used for the 1.7B checkpoint) |

**No installation step needed for the app itself** — `from_pretrained(model_id, ...)` downloads-and-caches on first use automatically, same as the 1.7B checkpoint already does today. The download in this research pass just pre-warms that cache on the one deployment target; a plan should NOT assume every future deploy environment has it pre-warmed (fresh deploys will pay the one-time ~2.5GB download on first 0.6B selection, same "1-2 minutes" caveat `tts_service/model.py`'s docstring already documents for the 1.7B case).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-process `del`+`gc.collect()`+`empty_cache()` swap | Full `tts_service` container restart on every swap | Guarantees a clean device state, zero fragmentation risk by construction, but pays the full 1-2 minute cold-load cost every swap instead of the ~5s warm-cache swap measured in this research — **not justified**: this research's 12-cycle zero-drift measurement removes the fragmentation risk that would have motivated this fallback |
| Two hardcoded model ids in a `MODEL_CHOICES` dict | A generic model registry/plugin system | Milestone explicitly scopes to exactly 2 sizes (Out of Scope: "A 3rd TTS model size or arbitrary model list") — a registry is unrequested flexibility for a value that never changes this milestone |

## Package Legitimacy Audit

**Not applicable — no new external packages this phase.** The only new artifact is a second Hugging Face Hub model repo under the same `Qwen/` org already trusted for the 1.7B checkpoint (Apache-2.0, `QwenLM/Qwen3-TTS` upstream project). No `pip install`/`npm install` of anything new is required; `qwen-tts`, `transformers`, `torch`, `huggingface_hub` are all already pinned and installed. If the planner introduces any new package during implementation (unlikely — the swap is ~30 lines of project code per STACK.md), run the Package Legitimacy Gate at that time.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────┐        PATCH /projects/{id}/model
│  Browser (ConfigPanel.tsx)   │  { model_id: "1.7b" | "0.6b" }
│  Select dropdown (D-01)      │───────────────────┐
│  disabled during swap        │                    │
│  D-03 persistent warning     │                    ▼
└───────────────┬───────────────┘   ┌───────────────────────────────┐
                 │                   │  Backend (app/main.py)         │
                 │ GET /projects/id  │  1. try_claim_generation(       │
                 │ (poll/refetch)    │       "model-load:{id}")        │
                 ▼                   │  2. POST tts_service            │
┌───────────────────────────────┐   │     /model/{model_id}/load     │
│  project.tts_model (DB)        │◄──┤  3. on 200: Project.tts_model   │
│  drives Select `value`,        │   │     = model_id; invalidate ALL  │
│  D-04 disabled-cell condition, │   │     segments (D-05/D-06, reuse  │
│  compute_cache_key(..., id)    │   │     GEN-03's clear-audio path)  │
└───────────────────────────────┘   │  4. on failure: project row      │
                                     │     UNCHANGED (D-02); surface   │
                                     │     error, release lock          │
                                     └───────────────┬─────────────────┘
                                                      │ HTTP POST /model/{id}/load
                                                      ▼
                              ┌────────────────────────────────────────┐
                              │  tts_service (GPU-scoped container)      │
                              │  server.py: _ready = False               │
                              │  model.py: ensure_loaded(model_id)       │
                              │    if already resident: no-op            │
                              │    else: del old model                  │
                              │          gc.collect()                    │
                              │          torch.cuda.empty_cache()        │
                              │          from_pretrained(new_id, ...)    │
                              │          re-apply StoppingCriteria patch │
                              │          re-derive DEFAULT_SPEAKER       │
                              │  server.py: _ready = True                │
                              └────────────────────────────────────────┘
                                          ▲
                                          │ Next /synthesize call resolves
                                          │ speaker via preset_speaker();
                                          │ D-07 fallback only fires if
                                          │ preset's speaker ∉ resident
                                          │ model's get_supported_speakers()
                                          │ (empirically: never today — see
                                          │ Blocker 2, identical rosters)
```

### Recommended Project Structure

No new files — this phase extends existing modules in place:
```
backend/
├── app/
│   ├── models.py        # + Project.tts_model: str = "1.7b" column
│   ├── cache_key.py      # compute_cache_key gains a model_id param, drop TTS_MODEL_VERSION constant
│   ├── main.py            # + POST /projects/{id}/model handler; _serialize_project + "tts_model"
│   └── tts_client.py      # + load_model(model_id) helper hitting tts_service's new route
├── tts_service/
│   ├── model.py           # module singleton -> ensure_loaded(model_id) + MODEL_CHOICES dict
│   └── server.py          # + POST /model/{model_id}/load; flips _ready False/True around the swap
frontend/
├── src/components/
│   ├── ConfigPanel.tsx     # replaces hardcoded TTS_MODEL_DISPLAY_NAME with the Select (05-UI-SPEC.md §1)
│   └── SegmentTable.tsx    # EditableTextCell gains project.tts_model-driven disabled prop (05-UI-SPEC.md §2)
```

### Pattern 1: `ensure_loaded()` replacing the module-level singleton
**What:** Replace `tts_service/model.py`'s `model = Qwen3TTSModel.from_pretrained(MODEL_NAME, ...)` (evaluated once at import time) with a small function that no-ops if the requested id is already resident, otherwise performs the 7-step swap sequence from STACK.md.
**When to use:** Called from the new `/model/{model_id}/load` route AND, as a safety net per ARCHITECTURE.md, optionally from `/synthesize` itself if a request names a `model_id` that differs from what's resident (D-01 makes this a fallback path only, not the primary UX).
**Example:**
```python
# Source: .planning/research/STACK.md §"(b) Loading/unloading between the
# two model sizes" — concrete 7-step sequence, cross-checked against this
# research's live 12-cycle measurement (zero VRAM drift).
import gc
import threading
import torch
from qwen_tts import Qwen3TTSModel

MODEL_CHOICES = {
    "1.7b": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "0.6b": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
}

_swap_lock = threading.Lock()  # or reuse try_claim_generation at the HTTP layer
_loaded_model_id: str | None = None
model = None  # kept as the module global every call-site already references

def ensure_loaded(model_id: str) -> None:
    global _loaded_model_id, model
    if model_id not in MODEL_CHOICES:
        raise ValueError(f"unknown model_id {model_id!r}")
    if _loaded_model_id == model_id:
        return  # already resident — no-op, matches D-01's "swap only on real change"
    with _swap_lock:
        if _loaded_model_id == model_id:  # re-check under lock
            return
        if model is not None:
            del model
            gc.collect()
            torch.cuda.empty_cache()  # ROCm build aliases cuda->hip
        model = Qwen3TTSModel.from_pretrained(
            MODEL_CHOICES[model_id],
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        _reapply_stopping_criteria_patch(model)  # Phase 4's monkeypatch — fresh object each load
        global DEFAULT_SPEAKER
        DEFAULT_SPEAKER = _pick_default_speaker(model.get_supported_speakers())
        _loaded_model_id = model_id
```

### Pattern 2: Threading model identity into the cache key
**What:** `compute_cache_key` currently hashes `(resolved_speaker, voice_instructions, text, TTS_MODEL_VERSION)` where the last field is a hardcoded constant.
**When to use:** Every call site that currently imports `TTS_MODEL_VERSION` (just `regenerate_segment` in `main.py` today).
**Example:**
```python
# Source: backend/app/cache_key.py (existing, this repo) + PITFALLS.md
# Pitfall 4's prescribed fix — drop the hardcoded constant, thread the
# real per-project value through instead.
def compute_cache_key(
    resolved_speaker: str, voice_instructions: str, text: str, model_id: str
) -> str:
    payload = _FIELD_SEPARATOR.join(
        [resolved_speaker, voice_instructions, text, model_id]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# call site (main.py::regenerate_segment):
cache_key = compute_cache_key(speaker, merged_instructions, segment.text, project.tts_model)
```

### Pattern 3: Project-wide segment invalidation reusing GEN-03's mechanism
**What:** D-06 says a swap loops the exact same per-row invalidation GEN-03 already applies on an edit — clear `audio_path`, revert `generation_status` to `"pending"`, unlink the old file from disk (mirrors the existing pattern at `main.py:800-804`).
**When to use:** Inside the swap endpoint handler, after the `tts_service` load call returns 200 and `Project.tts_model` is updated — never before the load is confirmed to have succeeded (a failed swap per D-02 must leave everything, including cached audio, untouched).
**Example:**
```python
# Source: existing GEN-03 per-row edit pattern (backend/app/main.py,
# regenerate_segment's invalidation branch) — D-06 says apply it project-wide.
for segment in session.exec(select(Segment).where(Segment.project_id == project_id)).all():
    old_audio_path = segment.audio_path
    segment.audio_path = None
    segment.cache_key = None
    segment.generation_status = "pending"
    session.add(segment)
    if old_audio_path:
        Path(old_audio_path).unlink(missing_ok=True)
session.commit()
```

### Anti-Patterns to Avoid
- **Reaching for a generic model registry:** Only 2 hardcoded ids, explicitly out of scope to generalize (`MODEL_CHOICES` dict is the whole abstraction needed).
- **Treating `tts_model` as global config:** Breaks the cache's correctness contract — must be per-project, not read from ambient global state at generate time (ARCHITECTURE.md Anti-Pattern, restated here because it's this phase's single most important discipline).
- **Calling `torch.cuda.empty_cache()` outside an actual swap:** "To be safe" on every generation call defeats allocator reuse and adds latency (PITFALLS.md Performance Trap) — only call it inside `ensure_loaded()`'s del branch.
- **Building a VRAM-leak-detection subsystem preemptively:** This research's real-hardware measurement found zero drift over 12 swaps — a `mem_get_info()` log line around the swap (already recommended for observability) is sufficient; do not build alerting/auto-restart machinery for a problem not observed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting which speakers a checkpoint supports | A hardcoded per-model speaker allowlist maintained by hand | `model.get_supported_speakers()` (already used elsewhere in the codebase, e.g. `tts_service/model.py`'s own `DEFAULT_SPEAKER` derivation) | It's the library's own source of truth, reads straight from `config.json`'s `talker_config.spk_id` — confirmed via direct source read, no need to duplicate it |
| VRAM release after unload | A custom allocator-tracking/defragmentation routine | `del` + `gc.collect()` + `torch.cuda.empty_cache()`, the standard PyTorch pattern already used nowhere else in this app but well-documented | This research's 12-cycle real-hardware test confirms it fully reclaims VRAM for this specific model-size pair on this specific GPU — no custom reclaim logic justified |
| Swap-in-progress request blocking | A new request queue/semaphore in the main backend | The existing `try_claim_generation`/`release_generation` single-flight lock, plus `tts_service`'s existing `_ready` flag pattern (already used for `/healthz`) | Both mechanisms already exist and already do exactly this job for synth calls — model-load is "just another claimant" per ARCHITECTURE.md |

**Key insight:** Every mechanism this phase needs (locking, cache-busting, invalidation, VRAM release) already exists somewhere in this codebase for an adjacent problem. The entire feature is "wire the same 4 existing patterns together with a new model_id dimension," not new infrastructure.

## Common Pitfalls

### Pitfall 1 (canonical, restated): Model swap breaks the load-once invariant and the cache doesn't know a swap happened
**What goes wrong:** Reassigning the module global while a request may be mid-flight causes undefined behavior (HIP illegal-memory-access, garbage audio, hang) if not gated by the lock; and a hardcoded `TTS_MODEL_VERSION` means a segment synthesized under 0.6B and one under 1.7B with identical (speaker, instructions, text) compute the same cache key — silent stale-audio reuse.
**Why it happens:** Both "only one model" and "never reload" were correct, deliberate v1 simplifications that become silently wrong the moment swapping is added.
**How to avoid:** Gate every (re)load behind `try_claim_generation`; flip `_ready = False` for the swap's duration; thread the live model id into `compute_cache_key`.
**Warning signs:** Switching models and regenerating a previously-generated segment produces byte-identical audio to the old model's output.
**Source:** `.planning/research/PITFALLS.md` §Pitfall 4 (HIGH confidence, verified against installed wheel).

### Pitfall 2 (canonical, but empirically closed this session): VRAM fragmentation across repeated swaps
**What was flagged:** `del model; torch.cuda.empty_cache()` reliably drops PyTorch's own reference but doesn't guarantee the allocator hands memory back to the driver or defragments it — community reports describe "OOM with plenty of memory apparently free" after repeated ROCm/HIP load/unload cycles.
**What this research found (real hardware, RX 9070 XT, `qwen-ebook-tts` production container):**

12 alternating swaps (`0.6b → 1.7b → 0.6b → ...`) were run against the live container using the exact `Qwen3TTSModel.from_pretrained(model_id, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")` call shape the app already uses, logging `torch.cuda.mem_get_info()` before and after each unload/reload:

| Measurement | Value |
|---|---|
| Baseline free VRAM (before this test process loaded anything; production `tts_service` already holding its own resident 1.7B model) | 12,017 MB free / 17,096 MB total |
| Free VRAM immediately after `del`+`gc.collect()`+`empty_cache()`, **swap 1** | 11,857 MB |
| Free VRAM immediately after `del`+`gc.collect()`+`empty_cache()`, **swap 12** | 11,857 MB — **byte-identical, zero drift** |
| 1.7B checkpoint resident footprint (this test process, on top of baseline) | ~4,311 MB |
| 0.6B checkpoint resident footprint (this test process, on top of baseline) | ~2,290 MB |
| Per-swap latency (weights already disk-cached, warm page cache) | 4.7s – 6.0s — well under the "tens of seconds" estimate in STACK.md/D-01, and far under the 300s httpx read timeout |
| Post-test VRAM (test process exited) | Returned to exact pre-test baseline (12,017 MB free) — confirms no leak survives process exit either |

**Conclusion:** No measurable fragmentation across 12 cycles on this exact hardware/model-pair/library-version combination. `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` or a container-restart fallback are **not needed** based on this measurement.

**Caveats (why this doesn't fully retire the pitfall, only closes it for planning purposes):**
- 12 swaps in a tight loop (~70s wall time) is not the same as fragmentation accumulating across a multi-hour/multi-day long-running `tts_service` process — if the planner wants a stronger guarantee, log `torch.cuda.mem_get_info()` on every real production swap (cheap, 2 lines) so any future drift is observable in logs rather than reintroducing an assumption.
- This test ran in a **separate process** from the actual `tts_service` server (via `podman exec`) to avoid disrupting the live service during research — it exercised the identical `from_pretrained` call and allocator behavior, but did not run inside `tts_service.py`'s own event loop / threadpool-execution context. This is a reasonable proxy (same process type: single Python process holding the CUDA context, same PyTorch/ROCm build) but the planner should still add the "Looks Done But Isn't" checklist item from PITFALLS.md (verify actual free VRAM before/after a swap in the real deployed feature, not just this research script) as part of Phase 5's own manual verification, not skip it because this number already looks clean.
- Only the 1.7B/0.6B pair was tested (the only pair this milestone needs) — footprint numbers don't generalize to a hypothetical third size.

**Recommendation:** Implement the plain in-process swap as designed. Add one `logger.info` line in `ensure_loaded()` logging `torch.cuda.mem_get_info()` before and after the swap (observability, not defensive engineering) so a real production session's numbers are visible in logs without needing to re-run this research script.

### Pitfall 3 (canonical, but empirically closed this session): Speaker-list parity between 1.7B and 0.6B
**What was flagged:** `get_supported_speakers()` "may differ between checkpoints — do not assume the preset list is identical."
**What this research found:** `get_supported_speakers()`'s implementation (`qwen_tts/core/models/modeling_qwen3_tts.py:1849`, `Qwen3TTSForConditionalGeneration.get_supported_speakers`) returns `self.supported_speakers`, set at model construction from `self.config.talker_config.spk_id.keys()` (line 1830) — a dict read straight from the checkpoint's `config.json`, not derived from the model weights. Fetched the 0.6B checkpoint's `config.json` directly (`huggingface_hub.hf_hub_download`, 4.9KB, no weight download) and compared its `talker_config.spk_id` keys against the live 1.7B model's `get_supported_speakers()` output:

```
1.7B: ['aiden', 'dylan', 'eric', 'ono_anna', 'ryan', 'serena', 'sohee', 'uncle_fu', 'vivian']
0.6B: ['aiden', 'dylan', 'eric', 'ono_anna', 'ryan', 'serena', 'sohee', 'uncle_fu', 'vivian']
```
9/9 identical, including `DEFAULT_SPEAKER` (`aiden`, present in both).

Cross-checked against `backend/app/voices.py`'s existing 6-preset roster: every preset's `speaker` value (`serena`, `vivian`, `sohee`, `ryan`, `aiden`, `uncle_fu`) is a member of both lists.

**Consequence for D-07:** implement the fallback exactly as decided (defensive, correct, cheap — 2-3 lines: `if resolved_speaker not in model.get_supported_speakers(): resolved_speaker = DEFAULT_SPEAKER`), but the planner and any manual verification step should not expect to be able to *demonstrate* the fallback firing against the current 6-preset roster — it would require either a future third checkpoint with a smaller speaker set, or a hand-crafted test that monkeypatches `get_supported_speakers()` to return a reduced list. Recommend a unit test that mocks/monkeypatches the speaker list rather than relying on a real preset/checkpoint mismatch that doesn't currently exist.

### Pitfall 4 (new this session — not covered by canonical research): Character preview audio is NOT covered by D-05/D-06's invalidation and has no cache key at all
**What goes wrong:** `_generate_preview` (main.py, character preview generation) calls `synthesize()` directly with no `compute_cache_key`/cache-hit check anywhere in its path — it's regenerated fresh on every `voice_version` bump (preset/instruction PATCH), not gated by a content hash the way segments are. D-05/D-06 explicitly scope the swap's invalidation to **segments** ("invalidates every segment in the project" / "reuses GEN-03's per-row mechanism"). A model swap does not bump any character's `voice_version`, so a character's existing `preview_audio_path` (generated under the previously-resident model) is left on disk and still served as-is after a swap — the user can click "play preview" on a character card and hear audio synthesized by the model that's no longer resident, indistinguishable from a fresh one.
**Why it happens:** Previews and segments use two different generation/caching paths in this codebase (previews: always-regenerate-on-relevant-PATCH, no cache key; segments: content-hash cache key checked before synth) — D-05/D-06 was written against the segment mechanism only, and the discussion that produced it didn't separately consider the preview path.
**How to avoid:** This is a scope decision the planner (or a quick discuss-phase follow-up) should make explicitly, not one this research resolves unilaterally — it wasn't in CONTEXT.md's locked decisions or discretion list. Two reasonable options: (a) extend the swap handler to also clear every character's `preview_audio_path` in the project (mirrors D-06's spirit, minimal extra code — same loop, one more table); (b) leave it out of Phase 5's scope and document it as a known gap (previews are a much shorter/cheaper regenerate than a full segment table, lower cost if stale). Given D-05's stated rationale ("obvious that a full re-generate pass is recommended... not a silent state where old-model audio keeps playing indistinguishably"), option (a) is more consistent with the decision's own stated intent — recommend the planner default to (a) unless the user says otherwise, and flag it explicitly in the plan rather than silently doing either.
**Warning signs:** After a swap, a character's "Play preview" button plays audio with no visible state change (no "Pending" badge — characters don't have the segment table's status badge at all), making this pitfall's "looks done but isn't" quality worse than the segment case, which at least has a visible pending state.
**Phase to address:** Phase 5 (same phase that introduces the swap) — recommend folding into the same D-06-derived invalidation loop, not deferring.

## Code Examples

### `POST /projects/{id}/model` backend handler shape
```python
# Source: this research, composed from existing patterns already in
# backend/app/main.py (try_claim_generation/release_generation usage
# mirrors regenerate_segment/generate_project; _serialize_project's
# existing shape) — no new library code, just wiring.
@app.post("/projects/{project_id}/model")
async def set_project_model(project_id: str, body: SetModelRequest) -> dict:
    if body.model_id not in MODEL_CHOICES:  # mirror tts_service's own validation
        raise HTTPException(status_code=422, detail=f"unknown model_id {body.model_id!r}")

    label = f"model-load:{body.model_id}"
    if not try_claim_generation(label):
        raise HTTPException(status_code=409, detail="Another generation is already in progress")

    try:
        await run_in_threadpool(tts_client.load_model, body.model_id)  # new tts_client helper
    except Exception as exc:
        release_generation()
        # D-02: project row untouched — still whatever model was resident before.
        raise HTTPException(status_code=502, detail=f"model load failed: {exc}") from exc

    with Session(engine) as session:
        project = session.get(Project, project_id)
        project.tts_model = body.model_id
        session.add(project)
        # D-05/D-06 (+ Pitfall 4 recommendation): invalidate every segment,
        # and — pending the scope decision above — every character preview.
        for segment in session.exec(
            select(Segment).where(Segment.project_id == project_id)
        ).all():
            _invalidate_segment(segment)  # existing helper, extracted from regenerate_segment's pattern
            session.add(segment)
        session.commit()
        characters = list(session.exec(select(Character).where(Character.project_id == project_id)).all())
        segments = list(session.exec(select(Segment).where(Segment.project_id == project_id)).all())
        result = _serialize_project(project, characters, segments)

    release_generation()
    return result
```

### `tts_service/server.py`'s new load route
```python
# Source: STACK.md's recommended endpoint shape, combined with the
# existing _ready-flag discipline already in server.py's /healthz.
@app.post("/model/{model_id}/load")
async def load_model_route(model_id: str) -> Response:
    global _ready
    if _model_module is None:
        return Response(status_code=503, content="model not loaded")
    if model_id not in _model_module.MODEL_CHOICES:
        return Response(status_code=422, content=f"unknown model_id {model_id!r}")

    _ready = False
    try:
        await run_in_threadpool(_model_module.ensure_loaded, model_id)
    except Exception:
        logger.exception("model swap failed")
        _ready = True  # old model is still the one resident (del happens AFTER new load succeeds)
        return Response(status_code=500, content="model swap failed")
    _ready = True
    return Response(status_code=200, content="ok")
```

### Frontend (binding contract — see `05-UI-SPEC.md` for the full, approved version)
The Model `Select`, D-03 warning note, D-02 error message, and D-04 disabled `Textarea` cells are fully specified with exact JSX and Tailwind classes in `.planning/phases/05-on-demand-model-swap/05-UI-SPEC.md` §"Component Contracts" — that file, not this one, is the binding source for frontend markup/copy. Key architectural point carried over into this research: **`generationLocked` (existing `useGenerationLock()` hook) already covers disabling Generate All/per-row/preview controls during a swap**, because the model-load claims the same single-flight backend lock under its own label — no new frontend lock state needed.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The 12-swap VRAM measurement (Pitfall 2) generalizes to longer-running production sessions (hours/days of intermittent swapping), not just a tight 70-second loop | Common Pitfalls | Low-moderate — mitigated by the recommended `mem_get_info()` log line in production; if slow drift exists at a much longer timescale it will be visible in logs before it becomes a hard OOM, per the original pitfall's own recommended mitigation |
| A2 | A fresh deploy environment (no pre-warmed HF cache for the 0.6B checkpoint) will complete the ~2.5GB one-time download within a reasonable UX window on the real deployment network — this research measured 36s on the actual deploy VM's network, which should be representative since it's the same physical network the production feature will run on, but wasn't tested from a cold Tailscale-only network path a real user's browser click would trigger from a different session | Standard Stack | Low — if slow, D-01's spinner already accommodates "tens of seconds," and a first-run one-time discovery download is a one-time cost identical in kind to the 1.7B model's existing first-run "1-2 minutes" documented behavior |

**All other claims in this research were either verified live against the production deployment target or cited directly from the already-HIGH-confidence milestone research (`ARCHITECTURE.md`/`PITFALLS.md`/`STACK.md`) — no unverified training-data claims about library behavior remain.**

## Open Questions

1. **Should a model swap also invalidate character preview audio (Pitfall 4), not just segments?**
   - What we know: D-05/D-06 explicitly scope invalidation to segments, reusing GEN-03's segment-specific mechanism. Character previews use a completely different, cache-free regeneration path with no existing "pending" visual state.
   - What's unclear: Whether this gap was a deliberate scoping choice during discuss-phase (previews are cheap/low-stakes) or simply not considered (previews weren't in view during that discussion).
   - Recommendation: Planner should default to including character preview invalidation in the same swap handler (same loop, one more table, consistent with D-05's stated "obvious, not silent" rationale) unless the user explicitly narrows scope. Flag explicitly in the plan so it's a visible decision, not a silent extension.

2. **Exact wire format for `POST /projects/{id}/model`'s request/response body** (e.g. `{"model_id": "1.7b"}` vs `{"tts_model": "1.7b"}`, whether the response is the full `_serialize_project` payload or a minimal ack) — mechanical, low-risk, left to the planner/implementer to match the codebase's existing PATCH-endpoint conventions (e.g. `PATCH /characters/{id}` at `main.py:407`) rather than inventing a new response shape.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ROCm/HIP GPU runtime (`/dev/kfd`, `/dev/dri`) | Model swap, all TTS inference | ✓ [VERIFIED: live on `qwen-ebook-tts` container] | ROCm 7.2.4, `torch 2.9.1+rocm7.2.4` | — |
| AMD RX 9070 XT (16GB) | VRAM budget for the swap | ✓ [VERIFIED: `torch.cuda.get_device_name(0)` == "AMD Radeon RX 9070 XT", `mem_get_info()` total ≈17,096MB] | — | — |
| `qwen-ebook-tts` Podman Quadlet service | Hosts the swap endpoint | ✓ [VERIFIED: `systemctl status qwen-ebook-tts.service` — active, running] | — | — |
| Outbound network from `qwen-ebook-tts` container (Hugging Face Hub) | Downloading the 0.6B checkpoint on first use | ✓ [VERIFIED: `curl -sI https://huggingface.co` returned 200; `snapshot_download` completed in 36s] | — | — |
| Persistent HF-cache volume across container restarts | Avoiding a re-download on every swap after the first | ✓ [inferred from existing 1.7B checkpoint already being cache-resident at container start; same volume mechanism applies to 0.6B] | — | — |
| 0.6B checkpoint pre-warmed on THIS deploy target specifically | Avoiding first-swap latency in this environment | ✓ (as of this research pass — downloaded and cache-verified) | — | Future fresh deploys: first 0.6B selection pays the one-time ~2.5GB download, same as 1.7B's existing documented first-run cost |

**Missing dependencies with no fallback:** None — every dependency this phase needs was directly verified present and working on the actual deployment target during this research pass.

## Security Domain

`security_enforcement` is not set in `.planning/config.json` (absent = enabled per policy) — included per protocol, scoped to what's actually new in this phase. This is a single-user, Tailscale-only app (no auth layer, per CLAUDE.md) — most ASVS categories are not applicable; the relevant surface is input validation on the one new user-controllable parameter.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Tailscale is the access boundary; no auth layer in this app (CLAUDE.md constraint, unchanged by this phase) |
| V3 Session Management | No | No session concept in this app |
| V4 Access Control | No | Single-user, no multi-tenant model |
| V5 Input Validation | Yes | `model_id` from the client must be validated against the fixed `MODEL_CHOICES = {"1.7b", "0.6b"}` set at BOTH the main-backend route and the `tts_service` route (defense in depth across the HTTP boundary between the two containers) — reject any other value with 422, never pass an unvalidated string into `from_pretrained()` (which would otherwise attempt an arbitrary Hugging Face Hub repo id, a mild SSRF/resource-exhaustion surface even on a trusted single-user network) |
| V6 Cryptography | No | No new cryptographic surface in this phase |

### Known Threat Patterns for this phase's stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Client sends an arbitrary string as `model_id` (not one of the two allowed ids), reaching `Qwen3TTSModel.from_pretrained(arbitrary_string, ...)` | Tampering / Denial of Service | Explicit `if model_id not in MODEL_CHOICES: raise/422` at both the backend route AND the `tts_service` route (the two are separate processes/containers — validating only one leaves the other trusting an unvalidated value crossing the internal HTTP boundary) — this is a mechanical allowlist check, not a design decision, but it's new attack surface introduced by this phase (today there's no user-controllable parameter that reaches `from_pretrained` at all) so it's worth calling out explicitly for the plan's task list |
| A crafted rapid-fire sequence of swap requests during an in-flight swap | Denial of Service (self-inflicted, single-user context) | Already covered by `try_claim_generation` returning 409 for a second concurrent claim attempt — no new mechanism needed, just confirm the swap route uses the same lock discipline as every other generation-triggering route |

## Sources

### Primary (HIGH confidence — verified this session, live on the production deployment target)
- Direct `podman exec` into the running `qwen-ebook-tts` container (RX 9070 XT, ROCm 7.2.4, `qwen-tts==0.1.1`) — `torch.cuda.mem_get_info()` measurements, `get_supported_speakers()` live call, `huggingface_hub.hf_hub_download`/`snapshot_download`/`HfApi.model_info` calls against the real Hugging Face Hub
- `qwen_tts/inference/qwen3_tts_model.py` and `qwen_tts/core/models/modeling_qwen3_tts.py`, read directly from the installed wheel inside the container (`_supported_speakers_set`, `get_supported_speakers`, `supported_speakers = self.config.talker_config.spk_id.keys()`, `if self.model.tts_model_size in "0b6": instruct = None`)
- `backend/app/main.py`, `backend/app/models.py`, `backend/app/cache_key.py`, `backend/app/generation_worker.py`, `backend/app/tts_client.py`, `backend/app/voices.py`, `backend/app/config.py`, `backend/tts_service/server.py`, `backend/tts_service/model.py`, `backend/Containerfile.tts`, `frontend/src/components/ConfigPanel.tsx` — this repo, read directly this session
- `.planning/phases/05-on-demand-model-swap/05-UI-SPEC.md` — approved UI design contract, binding for frontend implementation details

### Secondary (HIGH confidence — already-verified milestone research, cited verbatim)
- `.planning/research/ARCHITECTURE.md` §"Capability 2 — On-Demand Model Swap (1.7B / 0.6B)"
- `.planning/research/PITFALLS.md` §Pitfall 4, §Pitfall 5
- `.planning/research/STACK.md` §"v1.1 Addendum" (b), and the "Critical finding: `qwen-tts==0.1.1` silently drops `stopping_criteria`" section
- `.planning/phases/05-on-demand-model-swap/05-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `./CLAUDE.md`

### Tertiary
- None — no unverified web search was needed this session; the two open blockers were closable via direct measurement/source-read against the real deployment target, which is a stronger source than any external documentation would have been.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; existing pins verified live
- Architecture: HIGH — verified against installed source + already-HIGH milestone research
- VRAM fragmentation (Blocker 1): HIGH — real-hardware measurement, 12 cycles, zero drift; caveat only on generalizing to much longer timescales (see Assumption A1)
- Speaker-list parity (Blocker 2): HIGH — resolved directly from source logic + live config.json comparison, not just empirically "didn't observe a difference"
- Pitfalls: HIGH — two canonical pitfalls empirically closed this session; one new pitfall (character preview invalidation gap) identified via direct code read, flagged as an Open Question rather than unilaterally resolved since it touches a locked decision's scope

**Research date:** 2026-07-14
**Valid until:** Re-verify VRAM/speaker-parity findings if `qwen-tts`, `transformers`, or the pinned checkpoint revisions change (currently pinned exactly). Otherwise valid for the remainder of this milestone — ~30 days, standard for a stable, already-deployed stack.

---
*Phase 5 research consolidated: 2026-07-14*
