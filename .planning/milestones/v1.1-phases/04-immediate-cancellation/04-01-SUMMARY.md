---
phase: 04-immediate-cancellation
plan: 01
subsystem: tts-service
tags: [stopping-criteria, transformers, qwen-tts, rocm, cancellation, monkeypatch]

# Dependency graph
requires: []
provides:
  - "_cancel_event (threading.Event), _CancelStoppingCriteria, GenerationCancelled, request_cancel() in tts_service/model.py"
  - "synthesize_wav clears the event first, passes stopping_criteria into generate_custom_voice, raises GenerationCancelled on a fired cancel"
  - "monkeypatch of model.model.talker.generate that actually threads stopping_criteria into the real HF GenerationMixin.generate() call — the piece qwen-tts's own wrapper silently drops"
  - "backend/tests/test_cancel_machinery.py (CPU-only wiring test) and backend/tts_service/spike_cancel_hw.py (hardware timing spike, mirrors smoke_gpu.py)"
  - "hardware-verified finding: the talker's autoregressive decode loop aborts within ~1 decode step (~46ms) of request_cancel(); the post-talker vocoder (speech_tokenizer.decode) is a non-interruptible single forward pass whose latency scales with how much was already generated"
affects: [04-02, 04-03, 04-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Monkeypatch the ONE stable, standard-API call site (self.talker.generate, a real transformers.GenerationMixin.generate()) instead of reimplementing a third-party wrapper's much larger, version-fragile internal method, when that wrapper silently drops a kwarg it claims to forward"
    - "Per-stage elapsed-time logging (talker.generate() vs speech_tokenizer.decode()) plus a decode-step counter in the StoppingCriteria, to attribute a hardware timing measurement to the correct stage instead of guessing"

key-files:
  created:
    - backend/tests/test_cancel_machinery.py
    - backend/tts_service/spike_cancel_hw.py
  modified:
    - backend/tts_service/model.py

key-decisions:
  - "D-02 hardware spike FAILED the plan's literal pass bar (spike_cancel_hw.py exit code 1: cancel-to-stop must be <2000ms AND <25% of baseline) both before and after the fix — the script itself never passed and is not being retroactively rewritten to say otherwise."
  - "Root cause found by reading the installed qwen-tts==0.1.1 wheel directly: Qwen3TTSForConditionalGeneration.generate() builds its talker_kwargs dict from a hardcoded literal key list that does not include **kwargs, silently dropping stopping_criteria before it reaches self.talker.generate() (the actual interruptible HF generate() call)."
  - "Fixed by monkeypatching model.model.talker.generate directly (commit 9ced07f) rather than reimplementing qwen_tts's larger wrapper method — verified live on the RX 9070 XT: the talker's decode loop now aborts within ~46ms of request_cancel() (decode-step check #17 of an interrupted run)."
  - "User (via orchestrator) reviewed the full re-measured numbers and the stage-by-stage breakdown and made an explicit, informed decision to ACCEPT this as satisfying the phase's intent for D-01's 'true kill' bar in spirit, WITHOUT reopening 04-01's must_haves or loosening spike_cancel_hw.py's numeric ceiling. The ceiling stays as originally written, documenting the original target; the spike script still exits 1 against it."
  - "The remaining gap (vocoder/speech_tokenizer.decode() tail, non-interruptible, latency proportional to how much was already generated before Stop) is documented as a known, understood limitation, not silently accepted as if it didn't exist."

patterns-established:
  - "When a hardware/library assumption a plan checkpoint depends on turns out false, trace the actual library source (not just its docs) before concluding the mechanism is broken — the fix was one line once the real drop point was found by reading the wheel."

requirements-completed: []  # GEN-06/07/08 need the backend/frontend plumbing in 04-02/03/04 before the user-facing capability is actually complete; this plan only proves and lands the tts_service-side mechanism.

coverage:
  - id: D1
    description: "Cancellation machinery (_cancel_event, _CancelStoppingCriteria, GenerationCancelled, request_cancel()) exists in tts_service/model.py and synthesize_wav wires it around the real generate call"
    requirement: "GEN-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_cancel_machinery.py#test_criteria_returns_true_after_request_cancel_then_false_after_clear"
        status: pass
      - kind: other
        ref: "grep -n 'class _CancelStoppingCriteria' / 'def request_cancel' backend/tts_service/model.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "On real RX 9070 XT ROCm hardware, request_cancel() actually interrupts the in-flight GPU decode loop (D-02) rather than letting it run to completion"
    requirement: "GEN-06"
    verification:
      - kind: other
        ref: "backend/tts_service/spike_cancel_hw.py run inside the qwen-ebook-tts container against real weights"
        status: fail
    human_judgment: true
    rationale: "The spike script's literal pass bar (cancel-to-stop <2000ms AND <25% of baseline) was NOT met (189,015ms / 28.2% of baseline for the 3900-char worst case) — exit code 1, both before and after the fix. However, per-stage timing logs prove the talker's autoregressive decode loop (the actual GPU call D-02 was worried about) now aborts within ~46ms of request_cancel(); the remaining time is a separate, non-interruptible, partial-output-proportional vocoder decode stage. The user reviewed this full breakdown and explicitly decided to accept it as satisfying D-01's intent in spirit, without rewriting the plan's numeric bar. This is a judgment call on record, not an automated pass — hence human_judgment: true and verification status: fail (the automated check genuinely failed; the acceptance is a separate, documented human decision)."
  - id: D3
    description: "synthesize_wav raises GenerationCancelled (not a silently truncated WAV) when a cancel fired during generation"
    requirement: "GEN-06"
    verification:
      - kind: other
        ref: "backend/tts_service/spike_cancel_hw.py stdout: 'CANCEL-TO-STOP time: ... (outcome: cancelled)' + tts_service.model log 'synthesize_wav: cancel fired mid-generate — raising GenerationCancelled'"
        status: pass
    human_judgment: false

duration: ~4h (includes a mid-session interruption/resume for a usage-limit reset; wall-clock spans two hardware-investigation rounds)
completed: 2026-07-13
status: complete
---

# Phase 4 Plan 1: StoppingCriteria Cancellation Machinery + D-02 Hardware Validation Summary

**Landed the `_cancel_event`/`_CancelStoppingCriteria`/`request_cancel`/`GenerationCancelled` machinery in `tts_service/model.py`, then discovered via real RX 9070 XT hardware testing that qwen-tts's own wrapper silently drops `stopping_criteria` before it reaches the interruptible call — fixed by patching `model.model.talker.generate` directly, verified to abort the decode loop within ~46ms, with a documented non-interruptible vocoder tail remaining.**

## Performance

- **Duration:** ~4h (includes a mid-session interruption/resume for a usage-limit reset)
- **Started:** 2026-07-13T14:03:24+02:00 (Task 1 commit)
- **Completed:** 2026-07-13T18:20:26+02:00 (final fix commit)
- **Tasks:** 3/3 (Task 3 was the blocking checkpoint; resolved via investigation + fix + explicit user acceptance decision, not a clean automated pass)
- **Files modified:** 3 (`backend/tts_service/model.py`, `backend/tts_service/spike_cancel_hw.py`, `backend/tests/test_cancel_machinery.py`)

## Accomplishments

- Cancellation machinery (`_cancel_event`, `_CancelStoppingCriteria`, `GenerationCancelled`, `request_cancel()`) landed in `tts_service/model.py` as planned (Task 1), plus a CPU-only unit test and a standalone hardware timing spike script mirroring `smoke_gpu.py`'s conventions (Task 2).
- **D-02 hardware spike (Task 3) initially FAILED hard**, and honestly: `request_cancel()` had no measurable effect on wall-clock duration — the cancelled run's total time (272.8s pre-cancel sleep + 474.7s post-cancel wait ≈ 747.5s) matched the uncancelled baseline almost exactly. Root cause traced to the actual installed `qwen-tts==0.1.1` wheel source, not guessed: `Qwen3TTSForConditionalGeneration.generate()` builds its `talker_kwargs` dict from a hardcoded literal key list that never incorporates the caller's `**kwargs`, so a `stopping_criteria` passed all the way through `generate_custom_voice(**kwargs)` is silently dropped before it ever reaches `self.talker.generate()` — the real `transformers.GenerationMixin.generate()` call that would honor it.
- Fixed by monkeypatching `model.model.talker.generate` directly (the one stable, standard-API call site) rather than reimplementing qwen_tts's much larger, version-fragile wrapper method. Re-verified on the same RX 9070 XT hardware with per-stage timing logs: the talker's autoregressive decode loop now stops within **~46ms** of `request_cancel()` (cancel observed on decode-step check #17 of an interrupted 800-char run).
- Identified and documented the remaining gap: `speech_tokenizer.decode()` (the vocoder stage that turns generated codes into a waveform) runs *after* the now-interruptible talker stage, is a single `torch.inference_mode()` forward pass (not a loop — confirmed by reading `qwen_tts/inference/qwen3_tts_tokenizer.py`), and is genuinely not interruptible via `stopping_criteria`. Its latency scales with how much was already generated before Stop was clicked (measured: 6.7s for a 17-decode-step partial; 189s for a ~40%-into-a-3900-char-segment partial).
- The literal `spike_cancel_hw.py` pass bar (cancel-to-stop <2000ms AND <25% of baseline) is **still not met** for the worst case (189,015ms / 28.2% of baseline after the fix, down from 474,693ms / 69.6% before it). The user reviewed the full stage-by-stage breakdown and made an explicit, informed decision to accept this as satisfying D-01's "true kill" intent in spirit — the actual GPU decode loop genuinely stops almost instantly; what remains is a bounded, understood, progress-proportional cleanup step, not an unbounded orphaned call. This is a documented human judgment call, not a rewritten pass bar (see Deviations below).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the cancellation machinery to tts_service/model.py** - `a005ef4` (feat)
2. **Task 2: Machinery unit test + standalone hardware timing spike script** - `a5b79d2` (test)
3. **Task 3: D-02 hardware validation checkpoint** - investigation and fix, not a single clean task commit:
   - `b7f76c6` (fix) - warm up spike_cancel_hw.py with the full LONG_TEXT before timing, to exclude one-time-per-shape MIOpen kernel-selection overhead from the timed measurement
   - `9ced07f` (fix) - patch `model.model.talker.generate` so `stopping_criteria` actually reaches the decode loop (the D-02 root-cause fix)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified

- `backend/tts_service/model.py` - Cancellation machinery (Task 1) + the D-02 fix: monkeypatches `model.model.talker.generate` to inject `stopping_criteria` (the real fix), plus elapsed-time logging on the talker/vocoder stages and a decode-step counter in `_CancelStoppingCriteria` for future diagnosability
- `backend/tts_service/spike_cancel_hw.py` - Standalone hardware timing spike (mirrors `smoke_gpu.py`); warms up with the full timed text before measuring, to keep the timed numbers honest
- `backend/tests/test_cancel_machinery.py` - CPU-only unit test of the event/criteria contract (stubbed, since `tts_service.model` can't be imported off-GPU-container)

## Decisions Made

- Root-caused D-02's hardware failure by reading the actual installed `qwen-tts==0.1.1` wheel source rather than treating "StoppingCriteria doesn't work on ROCm" as the conclusion — the real issue was one layer up, in qwen_tts's own kwarg-forwarding code, not in Transformers or ROCm.
- Fixed via a targeted monkeypatch of `model.model.talker.generate` (a stable, standard `transformers.GenerationMixin.generate()` call) instead of reimplementing `Qwen3TTSForConditionalGeneration.generate()`'s much larger, qwen_tts-version-fragile body — smaller, more robust diff, per the plan's own guidance to avoid "hard-coded allowlist"-style reimplementation.
- **Did not rewrite `04-01-PLAN.md`'s `must_haves` or `spike_cancel_hw.py`'s numeric ceiling (2000ms / 25%).** The ceiling remains as originally written, documenting the original target. `spike_cancel_hw.py` still exits 1 against the worst-case (3900-char) measurement. The plan is being closed via an explicit user acceptance decision on record (see `coverage: D2` above and Deviations below), not because the automated check passed.
- Left the known vocoder-tail characteristic (cancel-to-stop latency scales with how much audio was already generated before Stop was clicked) as documented context for later plans — relevant to 04-03's frontend "stopping…" transient-state design (D-03/D-05, since the wait isn't always sub-second) and potentially worth a one-line mention in 04-04's D-06 caveat-copy update, though that phrasing call belongs to 04-04, not this plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Warmed up spike_cancel_hw.py with the full LONG_TEXT before timing**
- **Found during:** Task 3 (first hardware run)
- **Issue:** An unwarmed first call polluted the timed measurement with one-time-per-shape ROCm/MIOpen kernel-selection overhead — a naive first run showed a ~15-minute baseline for 3900 chars, dominated by `MIOpen(HIP) ... GetSolutionsFallback` warnings, not representative decode speed.
- **Fix:** Added an untimed warmup pass using the identical `LONG_TEXT` (not a short placeholder) before the timed baseline/cancel runs, so both cover the same shape range.
- **Files modified:** `backend/tts_service/spike_cancel_hw.py`
- **Verification:** Re-ran on hardware; the warmup/baseline discrepancy dropped from ~15min-vs-normal to both being similarly-scaled real numbers (later investigation revealed this "warmup" cost recurs on essentially every call at a given shape — see Issues Encountered below — so this fix's main value is honestly excluding one call's worth of that cost from the timed numbers, not eliminating it).
- **Committed in:** `b7f76c6`

**2. [Rule 1 - Bug, escalated per D-02 then resolved] Patched `model.model.talker.generate` so `stopping_criteria` reaches the real decode loop**
- **Found during:** Task 3 (D-02 checkpoint) — the hardware spike showed `request_cancel()` had no effect on wall-clock duration at all.
- **Issue:** `qwen-tts==0.1.1`'s `Qwen3TTSForConditionalGeneration.generate()` silently drops a caller-supplied `stopping_criteria` kwarg before it reaches the actual interruptible `self.talker.generate()` call (see Accomplishments above for the exact mechanism).
- **Fix:** Monkeypatched `model.model.talker.generate` at model-load time in `tts_service/model.py` to inject `stopping_criteria` via `kwargs.setdefault(...)`, delegating to the original bound method.
- **Files modified:** `backend/tts_service/model.py`
- **Verification:** Re-ran the hardware spike and a targeted shorter-text diagnostic with per-stage timing logs; confirmed the talker's decode loop now stops within ~46ms of `request_cancel()`. This did NOT flip `spike_cancel_hw.py`'s exit code to 0 (a separate, non-interruptible vocoder stage still dominates the worst-case number) — the checkpoint was resolved via an explicit user decision to accept the verified partial fix, not by this fix alone clearing the bar. Per Rule 4 (architectural change / genuinely unsure), this monkeypatch was applied only after being explicitly requested by the user (via the orchestrator) as the investigation lead to chase, and the "accept and proceed" decision after re-measurement was likewise explicit and on record.
- **Committed in:** `9ced07f`

---

**Total deviations:** 2 auto-fixed/escalated-then-resolved (2 Rule 1, one of which was escalated to and resolved by explicit user decision per D-02's own escalation requirement)
**Impact on plan:** Both changes were necessary to get an honest, root-caused hardware measurement and a genuine (if partial) fix for D-02's core question. No scope creep — the vocoder-tail gap was investigated to the point of a clear, non-speculative diagnosis and then explicitly left unfixed per the user's own scope call (see Issues Encountered), not abandoned mid-investigation.

## Issues Encountered

- **D-02's original checkpoint measurement was a clean FAIL, not ambiguous:** cancel-to-stop was 474,693ms against a 682,108ms baseline — the cancelled run's total wall-clock time was within 0.1% of an equivalent uncancelled run, proving `request_cancel()` had no effect at all before the fix. This was reported to the user honestly as a checkpoint halt, per the plan's own D-02 escalation instructions — no fallback was silently substituted.
- **Root cause required reading the actual installed library source**, not just ARCHITECTURE.md's wheel-reading (which was correct as far as it went — `stopping_criteria` genuinely does flow through `generate_custom_voice`'s kwarg-forwarding chain — but stopped one layer short of where `Qwen3TTSForConditionalGeneration.generate()` internally rebuilds its own `talker_kwargs` dict without the incoming `**kwargs`).
- **A persistent (not one-time) MIOpen performance characteristic was discovered** during investigation: `MIOpen(HIP): Warning [IsEnoughWorkspace] ... GetSolutionsFallback` recurs on essentially every call to a given GEMM shape in this container's ROCm/MIOpen build, not just the first time a shape is seen (confirmed by re-hitting shapes already exercised in an earlier run and seeing the same warning again). This means the vocoder-decode tail's several-second cost is not a "warm it up once and it's fast forever" problem — it likely affects overall TTS throughput generally (not just cancellation), but fixing it (MIOpen/ROCm environment tuning, or a streaming/chunked vocoder decode architecture) is out of scope for this plan; flagged here for future reference, not fixed.
- **Session was interrupted mid-investigation by a usage-limit reset** and resumed from where it left off (git history + running container state were sufficient to pick back up without redoing prior hardware runs).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The tts_service-side cancellation mechanism (`_cancel_event`, `_CancelStoppingCriteria`, `GenerationCancelled`, `request_cancel()`, and the talker-generate patch) is landed and hardware-verified to genuinely interrupt the GPU decode loop, ready for 04-02 to wire a `/cancel` HTTP endpoint on top of it.
- **04-03/04-04 should design the frontend "stopping…" state (D-03/D-05) and the batch-cancel caveat copy (D-06) with the documented vocoder-tail latency in mind** — a Stop click will not always resolve in well under a second; for a cancel fired late into a long segment's synthesis, the visible "stopping…" state may need to persist for several seconds to tens of seconds while the partial-codes vocoder decode finishes. This is real, measured backend behavior, not a UI polish question.
- GEN-06/07/08 are **not yet marked complete** — this plan proves and lands only the `tts_service`-side mechanism; the backend cancel endpoint, task registry, and frontend Stop controls (04-02/03/04) are still needed before the user-facing capability described by those requirements actually exists.
- No blockers for 04-02 to proceed.

---
*Phase: 04-immediate-cancellation*
*Completed: 2026-07-13*
