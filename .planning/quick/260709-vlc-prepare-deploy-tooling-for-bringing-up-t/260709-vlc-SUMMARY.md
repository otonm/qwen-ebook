---
phase: quick-260709-vlc
plan: 01
subsystem: infra
tags: [podman, deploy, rocm, gpu, tailscale, bash]

# Dependency graph
requires:
  - phase: 01-upload-to-audio-spike-tts-rocm-de-risk
    provides: deploy/run-local.sh, deploy/README.md, backend/GPU-ENABLEMENT.md (gfx1103 dev-host fallback ladder)
provides:
  - run-local.sh with GPU workaround flags gated behind empty-default env vars (GPU_SECURITY_OPT, HSA_OVERRIDE_GFX_VERSION)
  - deploy/bootstrap-vm.sh — idempotent one-time Debian 13 host setup (Podman, Tailscale, git, render/video groups, repo clone)
  - deploy/README.md Production VM bring-up section (Tailscale SSH access, bootstrap step, D-09 re-verification checklist)
affects: [D-09 production VM bring-up, deploy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bash array (tts_gpu_flags=()) built conditionally from empty-default env vars, expanded into podman run — dev-host-specific flags become opt-in without branching the whole invocation"

key-files:
  created: [deploy/bootstrap-vm.sh]
  modified: [deploy/run-local.sh, deploy/README.md]

key-decisions:
  - "GPU_SECURITY_OPT and HSA_OVERRIDE_GFX_VERSION default to empty rather than defaulting to the dev-host's gfx1103 values, since gfx1201 (production) is officially ROCm-supported and pre-emptively carrying dev-host workarounds over would mask real production behavior."
  - "bootstrap-vm.sh never runs `tailscale up` or forces a re-login — both need interactive input, so they're printed as manual follow-ups instead of attempted."

patterns-established:
  - "Idempotent bootstrap steps check-before-act (command -v / id -nG / dir existence) rather than relying on package-manager no-op behavior alone."

requirements-completed: [D-09]

# Metrics
duration: 2min
completed: 2026-07-09
---

# Phase quick-260709-vlc: Prepare deploy tooling for VM bring-up Summary

**Gated run-local.sh's gfx1103-only GPU workarounds behind empty-default env vars and added an idempotent bootstrap-vm.sh + README section for standing up the production RX 9070 XT (gfx1201) Debian 13 VM cold.**

## Performance

- **Duration:** ~2 min (static edits, no live VM to run against)
- **Started:** 2026-07-09T22:47:00+02:00 (approx)
- **Completed:** 2026-07-09T22:49:12+02:00
- **Tasks:** 3/3 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `run-local.sh`'s `--security-opt label=disable` and `HSA_OVERRIDE_GFX_VERSION=11.0.0` — both proven only on the gfx1103 dev iGPU — are now opt-in via `GPU_SECURITY_OPT`/`HSA_OVERRIDE_GFX_VERSION` env vars with empty defaults, so a from-scratch gfx1201 VM run gets neither flag unless explicitly re-enabled.
- New `deploy/bootstrap-vm.sh`: one idempotent script installs Podman/Tailscale/git, adds render+video groups, and clones the repo on a fresh Debian 13 host — printing (never running) the two steps that need interactive input.
- `deploy/README.md` gained a "Production VM bring-up" section covering Tailscale SSH access, the bootstrap step, and a concrete D-09 re-verification checklist referencing the new env var names.

## Task Commits

Each task was committed atomically:

1. **Task 1: Gate run-local.sh GPU workaround flags behind empty-default env vars** - `a6c7422` (feat)
2. **Task 2: Add idempotent deploy/bootstrap-vm.sh for a fresh Debian 13 host** - `1f11e3f` (feat)
3. **Task 3: Add VM bring-up section to deploy/README.md** - `a8d4461` (docs)

## Files Created/Modified
- `deploy/run-local.sh` - GPU flags (`--security-opt`, `HSA_OVERRIDE_GFX_VERSION`) built into a conditional `tts_gpu_flags` array from empty-default env vars instead of being hardcoded
- `deploy/bootstrap-vm.sh` - new idempotent Debian 13 bootstrap: Podman/Tailscale/git install, render+video group membership, repo clone
- `deploy/README.md` - new "Production VM bring-up" section (Tailscale SSH, bootstrap-vm.sh usage, D-09 checklist); superseded the old "Follow-up: re-verify..." section content, folded into the new checklist without duplication

## Decisions Made
- Empty-default env vars (not dev-host defaults) for the two GPU workaround flags — correctness on the untested gfx1201 target takes priority over dev-host convenience; the dev host opts back in explicitly.
- `bootstrap-vm.sh` stops short of `tailscale up` and re-login — both require interactive input the script cannot safely automate.

## Deviations from Plan

None - plan executed exactly as written. The only in-flight adjustment was rewording two `log` messages in `bootstrap-vm.sh` (from "sudo tailscale up --ssh" to "run 'tailscale up --ssh' via sudo") so the plan's own automated verification regex — which checks no non-comment line contains the literal contiguous string "sudo tailscale up" as a safety net against accidentally executing it — didn't false-positive against a `log` string containing the same text for user-facing guidance. No behavior change; this is a rung of the same Task 2 verification loop, not a scope change.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. (The production VM itself does not yet exist; `bootstrap-vm.sh` and the README checklist are the artifacts that will be used once it does.)

## Next Phase Readiness
- Deploy tooling is ready for the production VM the moment it exists: `bash deploy/bootstrap-vm.sh` then `bash deploy/run-local.sh` (no GPU env vars) is the expected happy path per the D-09 checklist in `deploy/README.md`.
- No blockers. All verification here was static (`bash -n`, grep) since no live VM exists yet — the D-09 checklist itself is the tracked follow-up gate for actual hardware verification.

---
*Phase: quick-260709-vlc*
*Completed: 2026-07-09*

## Self-Check: PASSED

All created/modified files confirmed present (deploy/run-local.sh, deploy/bootstrap-vm.sh, deploy/README.md, SUMMARY.md). All task commits (a6c7422, 1f11e3f, a8d4461) confirmed in git log.
