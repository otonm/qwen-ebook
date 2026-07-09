---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
plan: 02
subsystem: infra
tags: [rocm, podman, gpu, qwen-tts, fastapi, gfx1103, amd]

# Dependency graph
requires: []
provides:
  - "backend/Containerfile.tts: GPU-scoped rocm/pytorch-based container image for Qwen3-TTS"
  - "backend/tts_service/smoke_gpu.py: proven compute-agent + on-device matmul smoke test"
  - "backend/tts_service/model.py + server.py: Qwen3-TTS loaded once at startup, /synthesize + /healthz implemented per the internal contract"
  - "backend/GPU-ENABLEMENT.md: full fallback-ladder investigation on local gfx1103 hardware, including a critical unresolved finding (real inference GPU-hangs reproducibly)"
affects: ["01-03 (deployment/pod plan)", "any future GPU-inference work on non-RX-9070-XT hardware"]

# Tech tracking
tech-stack:
  added: ["qwen-tts==0.1.1", "rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1", "transformers==4.57.3", "accelerate==1.12.0", "fastapi==0.139.0", "uvicorn==0.51.0"]
  patterns: ["Isolated GPU-scoped TTS container behind an internal HTTP boundary (model loaded once at startup, never per-request)", "GPU compute smoke test run before any model weights load", "Ordered, evidence-gated fallback ladder for unsupported-GPU ROCm enablement (journalctl/getsebool-driven, not reflexive)"]

key-files:
  created:
    - backend/Containerfile.tts
    - backend/tts_service/__init__.py
    - backend/tts_service/requirements.txt
    - backend/tts_service/smoke_gpu.py
    - backend/tts_service/model.py
    - backend/tts_service/server.py
    - backend/GPU-ENABLEMENT.md
  modified: []

key-decisions:
  - "Fully-qualified the Containerfile base image as docker.io/rocm/pytorch (not the plan's short-name rocm/pytorch) because this host's registries.conf has short-name-mode=enforcing and cannot prompt in a non-TTY build"
  - "Adopted --security-opt label=disable (not full --privileged) as the minimal-privilege fix for a confirmed genuine SELinux AVC denial (map permission on /dev/kfd, root cause: container_use_devices boolean off, no root access to fix persistently via setsebool)"
  - "Adopted HSA_OVERRIDE_GFX_VERSION=11.0.0 after native (no override) failed at the very first GPU tensor allocation; 11.0.2 was deliberately never tried per RESEARCH.md's hard-lock warning for that specific value"
  - "generate_custom_voice's real signature (verified from the qwen-tts==0.1.1 wheel) is (text, speaker, ...) -> Tuple[List[np.ndarray], int], not the plan interface note's shorthand -> np.ndarray; model.py implements the verified signature"
  - "STOPPED live GPU stress testing after two reproducible full-model-inference crashes (each auto-recovered via kernel amdgpu MODE2 reset, host stayed stable) rather than continuing open-ended retries, per RESEARCH.md Pitfall 1 and explicit orchestrator guidance -- surfacing as a decision checkpoint instead"

patterns-established:
  - "Pattern: GPU compute smoke test (device detection + tiny matmul) must run and pass BEFORE attempting any real model load or inference -- this successfully isolated 'GPU compute works' from 'GPU model inference works' as two genuinely different risk tiers on unsupported hardware"
  - "Pattern: SELinux AVC denials must be confirmed via journalctl (or ausearch, if root is available) before reaching for --security-opt label=disable -- never applied reflexively"

requirements-completed: []  # GEN-01 and DEPL-01 are NOT validated by this plan yet -- see status below

# Metrics
duration: ~230min (includes a ~51min base-image pull and ~2 model-load cycles at ~2.5-3min each)
completed: 2026-07-09
---

# Phase 1 Plan 2: TTS/ROCm De-risk Spike Summary

**GPU-scoped Podman container for Qwen3-TTS built and proven for raw compute on local gfx1103 hardware (device detection + on-device matmul), but real model inference reproducibly crashes the GPU (auto-recovering) -- plan execution is PAUSED at a decision checkpoint, not complete.**

## Status: CHECKPOINT (plan not complete)

This plan is `autonomous: false` and explicitly scoped as an iterative,
timeboxed GPU-enablement spike. Tasks 1 and 2's *code* are implemented and
committed. Task 1's automated verification (GPU compute smoke test) passes.
Task 2's automated verification (real `/synthesize` producing a `RIFF`-header
WAV) does **not** currently pass -- every real-model-inference attempt on
this host crashes the container with a GPU fault. Task 3 (the plan's
human-verify checkpoint for audible audio + host stability) was never
reached because no audio was ever successfully produced to verify.

**This SUMMARY is being written now, ahead of full plan completion,** to
preserve the investigation and code in the worktree's git history before
the orchestrator reclaims the worktree, per the parallel-execution safety
requirement. A human decision is needed on how to proceed (see "Decision
Needed" below) before this plan can be marked complete.

## Performance

- **Duration:** ~230 min wall-clock (dominated by a ~51 min ROCm base-image
  pull over this connection, plus two ~2.5-3 min model-weight-download/load
  cycles for live testing)
- **Tasks attempted:** 2 of 3 (Task 1 complete + verified; Task 2 code
  complete, verification blocked; Task 3 not reached)
- **Files created:** 7

## Accomplishments

- Built `localhost/qwen-ebook-tts:dev` (30.1 GB), a GPU-scoped Podman image
  from `docker.io/rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1`
  with the exact-pinned `qwen-tts==0.1.1` stack, isolated from the backend's
  own dependency file.
- Proved, on this local Radeon 780M (`gfx1103`, not officially ROCm-supported),
  that the GPU is a genuine usable compute agent from inside the isolated
  container: `torch.cuda.is_available()=True`, real on-device 256x256 matmul
  succeeds -- answering RESEARCH.md's Open Question 1.
- Ran a real, evidence-driven fallback-ladder investigation (not a single
  assumed-working step): diagnosed and confirmed via `journalctl` a genuine
  SELinux `container_use_devices` gap (root required to fix persistently, not
  available in this session), isolated it from a second, independent ROCm
  issue via `--privileged` A/B testing, and landed on a minimal-privilege
  working configuration (`--security-opt label=disable` +
  `HSA_OVERRIDE_GFX_VERSION=11.0.0`) for raw compute.
- Implemented `backend/tts_service/model.py` (model loaded once at startup,
  `sdpa` attention, `bf16`, `DEFAULT_SPEAKER` chosen from
  `get_supported_speakers()`) and `backend/tts_service/server.py`
  (`POST /synthesize`, `GET /healthz`, AMD GPU keepalive background task)
  per the internal contract locked in 01-SKELETON.md, verified against the
  actual downloaded `qwen-tts==0.1.1` wheel's real API signatures.
- Discovered and documented, with full evidence and hypothesis, a
  **critical, reproducible finding**: real Qwen3-TTS inference (not just a
  toy matmul) crashes this host's GPU during the attention/GEMM-heavy
  forward pass (`MIOpen ... GemmFwdRest` workspace-size warnings immediately
  preceding a GPU page fault / hang), twice, on two independent container
  instances. The host's kernel `amdgpu` driver auto-recovered via MODE2
  reset both times -- no permanent damage, no full hard-lock, host stayed
  fully responsive throughout -- but real audio was never successfully
  produced on this hardware in this session.

## Task Commits

1. **Task 1: TTS container image + GPU compute smoke test (fallback ladder, iterative)** - `b38ecb9` (feat)
2. **Task 2: Load Qwen3-TTS once at startup + implement /synthesize and /healthz** - `65e69d9` (feat) -- code complete; live verification blocked, see Issues Encountered

**Task 3 (checkpoint:human-verify) was not reached** -- no successful audio
output exists yet to verify.

## Files Created/Modified

- `backend/Containerfile.tts` - GPU-scoped image, `rocm/pytorch` base (fully-qualified `docker.io/`), exact-pinned qwen-tts stack, no torch reinstall
- `backend/tts_service/__init__.py` - package marker + isolation-boundary docstring
- `backend/tts_service/requirements.txt` - isolated TTS-container dependency pins
- `backend/tts_service/smoke_gpu.py` - compute-agent + on-device matmul smoke test, run before model load
- `backend/tts_service/model.py` - `Qwen3TTSModel.from_pretrained()` loaded once at startup, `DEFAULT_SPEAKER` selection, `synthesize_wav()`
- `backend/tts_service/server.py` - `POST /synthesize`, `GET /healthz`, AMD GPU keepalive background task
- `backend/GPU-ENABLEMENT.md` - full fallback-ladder investigation log, including the critical Task 2 finding

## Decisions Made

- Fully-qualified `docker.io/rocm/pytorch:...` in the Containerfile FROM line (Rule 3 blocking-issue auto-fix; this host's `registries.conf` has `short-name-mode=enforcing` and cannot prompt in a non-TTY build session).
- Adopted `--security-opt label=disable` (narrower than `--privileged`) as the minimal-privilege fix for a *confirmed* genuine SELinux AVC denial (`map` on `/dev/kfd`; root cause `container_use_devices` boolean off; no root access available in this session to fix persistently via `setsebool -P`).
- Adopted `HSA_OVERRIDE_GFX_VERSION=11.0.0` after proving native (no override) fails at the very first GPU tensor allocation on this host; `11.0.2` was deliberately never tried per RESEARCH.md's specific hard-lock warning for that value.
- Implemented `generate_custom_voice`'s real, wheel-verified signature (`(text, speaker, ...) -> Tuple[List[np.ndarray], int]`) rather than the plan's interface-note shorthand (`-> np.ndarray`).
- Stopped further live GPU stress testing after two reproducible full-model-inference crashes (both auto-recovered, host stayed stable) rather than continuing open-ended retries, consistent with RESEARCH.md Pitfall 1's explicit "stop experimenting" guidance and an explicit orchestrator steer to treat this as a documented spike outcome given the dev host is not the production target (D-09).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fully-qualified the Containerfile base image**
- **Found during:** Task 1
- **Issue:** `podman build` failed immediately with "short-name resolution enforced but cannot prompt without a TTY" for `FROM rocm/pytorch:...`
- **Fix:** Changed to `FROM docker.io/rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1`
- **Files modified:** `backend/Containerfile.tts`
- **Verification:** Build succeeded (30.1 GB image tagged `localhost/qwen-ebook-tts:dev`)
- **Committed in:** `b38ecb9`

**2. [Rule 1 - Bug] Corrected `generate_custom_voice`'s return signature**
- **Found during:** Task 2, while inspecting the downloaded `qwen-tts==0.1.1` wheel to verify the plan's interface note
- **Issue:** Plan's interfaces block stated `generate_custom_voice(...) -> np.ndarray`; the real signature returns `Tuple[List[np.ndarray], int]` (a list of arrays plus sample rate)
- **Fix:** `model.py`'s `synthesize_wav()` unpacks `wavs, sample_rate = model.generate_custom_voice(...)` and writes `wavs[0]` with the returned `sample_rate`
- **Files modified:** `backend/tts_service/model.py`
- **Verification:** Confirmed directly against `qwen_tts/inference/qwen3_tts_model.py` in the downloaded wheel
- **Committed in:** `65e69d9`

---

**Total deviations:** 2 auto-fixed (1 blocking-issue, 1 bug-correction against verified source)
**Impact on plan:** Both necessary for the build/code to function at all; no scope creep.

## Issues Encountered

**Real Qwen3-TTS model inference crashes the GPU reproducibly on this dev
host (unresolved -- decision needed).** Task 1's GPU compute smoke test
(device detection + 256x256 matmul) passes cleanly with the fallback-ladder
configuration (`--security-opt label=disable -e
HSA_OVERRIDE_GFX_VERSION=11.0.0`). However, real `/synthesize` calls against
the fully-loaded model crash the container (exit 139) on both attempts made:
first with `HW Exception ... reason: GPU Hang`, second with `Memory access
fault ... Page not present`, both immediately preceded by `MIOpen ...
Solver <GemmFwdRest>, workspace required: 10321920, provided ptr: 0 size:
0` warnings -- suggesting a MIOpen/AOTriton attention-kernel workspace gap
distinct from the rocBLAS/Tensile gap RESEARCH.md's rung 3 explicitly
targets. The host's `amdgpu` driver auto-recovered via a kernel-level MODE2
GPU reset both times (`GPU reset(1..4) succeeded!`); `uptime` and
`/dev/kfd`/`/dev/dri` were confirmed normal after each crash, and the smoke
test was successfully re-run after the first crash, confirming the device
itself was not permanently wedged. Full detail, evidence, and hypothesis in
`backend/GPU-ENABLEMENT.md` ("Task 2 finding" section).

Live GPU stress testing was deliberately stopped after this second
reproduction (not open-ended retried), per RESEARCH.md Pitfall 1's explicit
guidance and because this dev host (`gfx1103`, unsupported, iGPU sharing
system RAM) is not the production target (RX 9070 XT / `gfx1201`,
officially ROCm-7.2-supported dGPU, D-09) -- this finding may not
generalize to production hardware.

## Decision Needed (blocking Task 2/3 completion)

1. **Attempt further mitigation on this host** -- e.g. MIOpen env var tuning
   (`MIOPEN_FIND_MODE`, `MIOPEN_DEBUG_CONV_GEMM`), or a MIOpen
   kernel-database patch analogous to Pitfall 2's documented rocBLAS/Fedora
   workaround (not yet attempted -- targets a different library than the
   one implicated here).
2. **Accept this as a legitimate, documented spike outcome for local
   `gfx1103` hardware** and defer full audio-output verification to the
   production RX 9070 XT (`gfx1201`) VM once available (D-09 already scopes
   re-verification as a tracked follow-up, not this phase's success bar) --
   proceed to Plan 03 / later work with this finding flagged, rather than
   spending further timeboxed-spike budget here.
3. **Provide root/sudo access** to test whether `sudo setsebool -P
   container_use_devices on` (the underlying SELinux gap found in Task 1)
   plus retrying without `--security-opt label=disable` changes anything
   about the Task 2 crash (unlikely, since the `--privileged` isolation test
   already showed the crash is independent of the SELinux issue, but not
   fully ruled out for the inference-specific code path).

## Next Phase Readiness

- Task 1's container build + GPU compute-smoke pattern is solid and
  reusable regardless of which option above is chosen.
- Task 2's `model.py`/`server.py` code is believed correct against the
  actual `qwen-tts` API (verified from source) and does not need rework
  unless a MIOpen-specific mitigation requires code changes (e.g., an
  `attn_implementation` change, which would itself be a Rule 4
  architectural deviation from the plan's locked `sdpa` decision and would
  need separate approval).
- Plan 01-03 (deployment/pod plan) should NOT assume this plan's audio
  output is proven yet -- treat GEN-01/DEPL-01 as still open until this
  checkpoint is resolved.
- `backend/GPU-ENABLEMENT.md` is the authoritative, evidence-backed record
  of everything tried; read it fully before attempting further GPU
  mitigation work on this host.

---
*Phase: 01-upload-to-audio-spike-tts-rocm-de-risk*
*Completed: NOT COMPLETE -- checkpoint written 2026-07-09*
