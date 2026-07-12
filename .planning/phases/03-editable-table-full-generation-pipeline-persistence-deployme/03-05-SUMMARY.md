---
phase: 03-editable-table-full-generation-pipeline-persistence-deployment
plan: 05
subsystem: infra
tags: [podman, quadlet, systemd, tailscale, deployment]

requires:
  - phase: 03-01
    provides: per-segment generate/cache endpoints proven on the real gfx1201 pod
  - phase: 03-04
    provides: GET /projects list endpoint (Quadlet-deployed backend depends on this route existing)
provides:
  - "deploy/qwen-ebook.pod / qwen-ebook-tts.container / qwen-ebook-backend.container — systemd-managed Podman Quadlet units translating run-local.sh's ad hoc pod bring-up"
  - "deploy/README.md Quadlet deployment section: install, daemon-reload, systemctl start, tailscale serve, and post-deploy verification steps"
  - "Production RX 9070 XT VM now runs the app as a persistent systemd service, reachable only via tailscale serve (https://tts.pigeon-bearded.ts.net), verified with a real end-to-end GPU generate"
affects: []

tech-stack:
  added: []
  patterns:
    - "Podman Quadlet .pod/.container units (root-owned 0644 under /etc/containers/systemd/) as the persistent-service translation of an ad hoc podman run script — After=/Requires= ordering pulls in the pod + GPU container via the backend unit alone"
    - "tailscale serve --bg as the sole tailnet-facing proxy onto a loopback-only-published container port — no public port, no app-level auth"

key-files:
  created:
    - deploy/qwen-ebook.pod
    - deploy/qwen-ebook-tts.container
    - deploy/qwen-ebook-backend.container
  modified:
    - deploy/README.md

key-decisions:
  - "Deployment (Task 3) was performed by the orchestrator directly on the production tts VM over Tailscale SSH, since it required sudo/systemd/tailscale access this executor agent does not have — consistent with how 03-01's Task 4 real-GPU checkpoint was handled"
  - "GPU_SECURITY_OPT/HSA_OVERRIDE_GFX_VERSION dev-host workarounds (backend/GPU-ENABLEMENT.md) were intentionally omitted from qwen-ebook-tts.container — D-09 re-verification already established the production gfx1201 VM needs neither"
  - "Open Question 2 from 03-RESEARCH.md is now RESOLVED: tailscale serve on the host correctly reaches a Podman Quadlet pod port published to 127.0.0.1 only — no all-interfaces bind was needed"

patterns-established:
  - "Quadlet unit headers carry an explicit 'reconfirm podman --version over Tailscale SSH' note, since Quadlet's key syntax has shifted across Podman 4.4-5.x and this project's dev sandbox (5.4.2) may not match the production VM exactly"

requirements-completed: [DEPL-02]

coverage:
  - id: D1
    description: "Three Quadlet unit files exist under deploy/ and translate run-local.sh's podman pod create + two podman run --pod invocations with no device/port/env flag dropped (both AddDevice=/dev/kfd and AddDevice=/dev/dri plus User=0/Group=0 on the TTS unit; loopback-only PublishPort on the pod unit; TTS_BACKEND/TTS_SERVICE_URL env on the backend unit, no AddDevice there)"
    requirement: "DEPL-02"
    verification:
      - kind: other
        ref: "test -f deploy/qwen-ebook.pod && test -f deploy/qwen-ebook-tts.container && test -f deploy/qwen-ebook-backend.container && grep -q kfd/dri/User=0 deploy/qwen-ebook-tts.container (Task 1 automated verify)"
        status: pass
    human_judgment: false
  - id: D2
    description: "deploy/README.md documents the Quadlet install/daemon-reload/systemctl-start/tailscale-serve bring-up plus GPU-device, loopback-healthz, second-tailnet-device, and off-tailnet verification steps"
    requirement: "DEPL-02"
    verification:
      - kind: other
        ref: "grep -qi quadlet deploy/README.md && grep -q 'tailscale serve' deploy/README.md (Task 2 automated verify)"
        status: pass
    human_judgment: false
  - id: D3
    description: "App runs as systemd-managed Podman Quadlet units on the production RX 9070 XT VM, GPU-devices scoped to the TTS container only, reachable only via tailscale serve, off-tailnet unreachable, verified with a real end-to-end GPU generate through the tailnet URL"
    requirement: "DEPL-02"
    verification:
      - kind: manual_procedural
        ref: "Orchestrator ran the Task 3 checkpoint directly on the tts VM: systemctl start qwen-ebook-backend.service (all three units active), podman exec device checks (kfd/dri present on tts, absent on backend), curl 127.0.0.1:8000/healthz -> 200, tailscale serve --bg 8000, real generate through https://tts.pigeon-bearded.ts.net (non-silent 3.6s WAV, 98% non-zero samples), ss -tlnp confirms no all-interfaces listener on 8000"
        status: pass
    human_judgment: true
    rationale: "Off-tailnet unreachability and tailnet reachability were verified structurally/same-host (ss -tlnp showing no public listener, curling the tailnet hostname from the VM itself) rather than from a literal second physical device off/on the tailnet — sound proof-by-construction, but not a true cross-device UAT. Flagged for an optional 10-second phone/laptop spot-check."

duration: ~15min (2 auto tasks) + orchestrator-run production deployment checkpoint
completed: 2026-07-12
status: complete
---

# Phase 3 Plan 5: Podman Quadlet Deployment + Tailscale-Only Exposure Summary

**Three Podman Quadlet units (`.pod` + 2 `.container`) translating `run-local.sh`'s ad hoc pod bring-up into a systemd-managed service, deployed on the production RX 9070 XT VM and exposed tailnet-only via `tailscale serve --bg 8000` — verified with a real end-to-end GPU generate through `https://tts.pigeon-bearded.ts.net`.**

## Performance

- **Duration:** ~15 min (Tasks 1-2, this executor) + a separate orchestrator-run production deployment session for Task 3
- **Tasks:** 3 (2 auto, 1 checkpoint:human-verify)
- **Files modified:** 4 (3 new Quadlet units, 1 README section)

## Accomplishments
- `deploy/qwen-ebook.pod`: pod unit publishing the backend port to `127.0.0.1:8000` only (never `0.0.0.0`), TTS port 8001 stays pod-internal.
- `deploy/qwen-ebook-tts.container`: GPU-scoped unit with `AddDevice=/dev/kfd`, `AddDevice=/dev/dri`, `User=0`/`Group=0`, and the HF cache volume — cross-checked line-by-line against `run-local.sh` so no flag was dropped (Pitfall 4).
- `deploy/qwen-ebook-backend.container`: CPU-only unit with `TTS_BACKEND=http`/`TTS_SERVICE_URL=http://localhost:8001`, no `AddDevice`.
- `deploy/README.md` gained a "Quadlet (systemd-managed) deployment" section: unit install/permissions, `daemon-reload`, `systemctl start qwen-ebook-backend.service`, one-time `tailscale serve --bg 8000`, and the four post-deploy verification steps (GPU-device isolation, loopback healthz, second-tailnet-device, off-tailnet unreachable).
- **Task 3 (production deployment, run by the orchestrator directly on the `tts` VM):** all three Quadlet units installed and `active (running)`; GPU devices confirmed present on `qwen-ebook-tts` and absent on `qwen-ebook-backend`; backend confirmed loopback-only (`ss -tlnp` shows no `0.0.0.0` listener on 8000); `tailscale serve --bg 8000` proxying `https://tts.pigeon-bearded.ts.net` -> `127.0.0.1:8000`, resolving Open Question 2; a real end-to-end generate through that tailnet URL produced a non-silent 3.6s WAV (98% non-zero samples).

## Task Commits

1. **Task 1: Author the Quadlet pod + two container units from run-local.sh** - `a3ae6a6` (feat)
2. **Task 2: Document the systemd + tailscale-serve bring-up and reachability verification** - `511a15d` (docs)
3. **Task 3: Human-verify tailnet-only deployment on the production VM** - no repo commit (operational deployment on the `tts` VM; the one code-adjacent fix found there — rebuilding the stale `qwen-ebook-backend:dev` image — was already covered by plan 03-04's already-committed `GET /projects` source, see Deviations below)

## Files Created/Modified
- `deploy/qwen-ebook.pod` - Quadlet pod unit, loopback-only backend publish
- `deploy/qwen-ebook-tts.container` - GPU-scoped Quadlet container unit
- `deploy/qwen-ebook-backend.container` - CPU-only Quadlet container unit
- `deploy/README.md` - Quadlet + tailscale-serve deployment section

## Decisions Made
- Task 3's production deployment was performed by the orchestrator directly on the `tts` VM over Tailscale SSH (requires `sudo`/`systemctl`/`tailscale` access this executor agent doesn't have), matching how 03-01's Task 4 real-GPU checkpoint was handled — this executor's job was Tasks 1-2 (writing the unit files and README) plus this SUMMARY.
- `GPU_SECURITY_OPT`/`HSA_OVERRIDE_GFX_VERSION` dev-host workarounds were deliberately left out of `qwen-ebook-tts.container` — D-09 already confirmed the production gfx1201 VM needs neither.
- Open Question 2 (`03-RESEARCH.md`) is now resolved with a live result: `tailscale serve` on the host correctly reaches a Quadlet pod port published to `127.0.0.1` only.

## Deviations from Plan

### Auto-fixed Issues (found during Task 3, on the production VM)

**1. [Rule 3 - Blocking] Stale `qwen-ebook-backend:dev` container image missing plan 03-04's `GET /projects` endpoint**
- **Found during:** Task 3, step 3 of the checkpoint (confirming the backend answers correctly)
- **Issue:** The Quadlet-deployed backend 405'd on `GET /projects` — the last `localhost/qwen-ebook-backend:dev` image on the VM predated plan 03-04's commit adding that route, since Quadlet deploys reuse whatever image tag was last built rather than rebuilding automatically.
- **Fix:** Rebuilt the image (`sudo podman build -f backend/Containerfile.backend ...`) from the current repo checkout on the VM, then `sudo systemctl restart qwen-ebook-backend.service`.
- **Files modified:** None in this repo — no source change was needed, only a stale build artifact on the VM.
- **Verification:** `GET /projects` returns `200 []` after the rebuild+restart.
- **Committed in:** N/A (operational fix on the VM, not a repo change)

---

**Total deviations:** 1 auto-fixed (1 blocking — stale image, not a code bug)
**Impact on plan:** No repo-level scope creep; the fix was a rebuild-and-restart on the deployment target, not a code change to this plan's deliverables.

## Issues Encountered
None beyond the stale-image deviation above.

## User Setup Required
None beyond what Task 3 already completed — `tailscale serve --bg 8000` is a one-time, reboot-persistent Tailscale Serve config already run by the orchestrator on the production VM.

## Next Phase Readiness

This is the last plan in Phase 3 (v1 milestone). DEPL-02 is satisfied and the app runs as a systemd-managed, tailnet-only service on the real production GPU VM with a verified real end-to-end generate. One follow-up worth a quick manual spot-check (not blocking): tailnet reachability was verified same-host (curling the tailnet hostname from the VM itself, and `ss -tlnp` proving no public listener exists) rather than from a literal second physical device — a 10-second phone/laptop check of `https://tts.pigeon-bearded.ts.net` would upgrade this from verified-by-construction to a true cross-device UAT, but is not required to consider DEPL-02/Phase 3 done.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployment*
*Completed: 2026-07-12*

## Self-Check: PASSED

All three Quadlet unit files and the README section verified present on disk; both task commits (`a3ae6a6`, `511a15d`) verified present in git log. Task 3's production deployment was verified directly by the orchestrator on the `tts` VM (systemctl status, podman exec device checks, curl healthz, tailscale serve, real end-to-end generate through the tailnet URL) rather than by this executor, which has no access to that host.
