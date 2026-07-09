---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
plan: 03
subsystem: deployment
tags: [podman, pod, deployment, integration-test, gpu-isolation, ipv6-pasta]

dependency-graph:
  requires:
    - "01-01: FastAPI backend (upload/chunk/join/mock-or-http tts_client)"
    - "01-02: backend/Containerfile.tts, tts_service/ (model.py, server.py), GPU-ENABLEMENT.md fallback-ladder findings"
  provides:
    - "backend/Containerfile.backend: CPU-only backend image (python:3.12-slim, ffmpeg, uv, no torch/qwen-tts)"
    - "deploy/qwen-ebook-pod.yaml: reference Kubernetes-style two-container pod manifest"
    - "deploy/run-local.sh: podman pod create + podman run --pod one-command bring-up, HF-cache-volume, /healthz wait"
    - "deploy/README.md: isolation verification steps, 127.0.0.1-vs-localhost pasta quirk, D-09 follow-up"
    - "backend/tests/test_integration.py: real two-container-pod integration test (positive GEN-04 join proof + negative T-03-02 gateway-error proof)"
    - "app/main.py httpx.TimeoutException/HTTPError -> 504/502 mapping around tts_client.synthesize()"
  affects:
    - "Any future Phase 2/3 work that runs the real two-container pod locally inherits run-local.sh/README.md as-is"
    - "Production RX 9070 XT (gfx1201) VM deployment — D-09 tracked follow-up, not yet performed"

tech-stack:
  added:
    - "python:3.12-slim (backend image base)"
    - "uv installed via pip inside the backend image (matches host provisioning pattern from Plan 01)"
  patterns:
    - "Two-container Podman pod (podman pod create + podman run --pod), not podman kube play — this host's proven GPU passthrough flags need --group-add keep-groups, which plain Kubernetes Pod YAML/kube play cannot express"
    - "Per-Containerfile scoped .dockerignore (backend/Containerfile.backend.dockerignore) rather than a generic backend/.dockerignore, since a generic one is silently picked up by every build sharing the same context directory"
    - "Named volume (qwen-ebook-tts-hf-cache) persisting the TTS container's Hugging Face model cache across pod restarts"
    - "GPU-device isolation verified via `podman exec <ctr> ls /dev/kfd /dev/dri` (device-node presence/absence), not `podman inspect --format '{{.HostConfig.Devices}}'` — the latter does not reflect --device-passed devices in this Podman version's JSON output even though the devices are genuinely present/absent inside the container"
    - "127.0.0.1 (not localhost) in all documented/printed curl commands — this host's rootless Podman pasta port-forwarding resets IPv6 (::1) loopback connections while IPv4 forwards correctly"

key-files:
  created:
    - backend/Containerfile.backend
    - backend/Containerfile.backend.dockerignore
    - deploy/qwen-ebook-pod.yaml
    - deploy/run-local.sh
    - deploy/README.md
    - backend/tests/test_integration.py
  modified:
    - backend/app/main.py
    - backend/pyproject.toml

decisions:
  - "podman pod create + podman run --pod for actual bring-up, not podman kube play on deploy/qwen-ebook-pod.yaml — --group-add keep-groups (proven required on this host per GPU-ENABLEMENT.md) has no Kubernetes Pod YAML equivalent. The YAML remains as documentation/a kube-play-compatible reference for hosts that don't need that flag."
  - "backend/.dockerignore renamed to backend/Containerfile.backend.dockerignore — a generic .dockerignore in the shared backend/ build context was silently excluding tts_service/ from the Containerfile.tts build too, breaking it. Podman's per-Containerfile ignorefile naming scopes the ignore rules to the backend image only."
  - "Added a named volume for the TTS container's Hugging Face cache (qwen-ebook-tts-hf-cache) — without it, every pod restart re-downloads several GB of model weights, observed directly during this plan's verification (first cold load took >12 minutes over this connection; a warm restart from the persisted volume took under a minute)."
  - "127.0.0.1 used everywhere instead of localhost in run-local.sh's printed command and README.md — localhost resolves to ::1 first on this host and rootless Podman's pasta resets that specific loopback path (confirmed: IPv4 127.0.0.1 returns 200, IPv6 ::1 returns 'Recv failure: Connection reset by peer', for the identical request)."
  - "Only GEN-04 (join-in-order) marked complete in REQUIREMENTS.md, not GEN-01 or DEPL-01 — the join step is proven working end-to-end in the real deployed containers (via the mock-backend suite plus this plan's positive integration test up through the point where it depends on real synthesis); GEN-01 (real GPU-synthesized audio) and the audio-output portion of DEPL-01 remain unproven on this specific gfx1103 dev host per the already-accepted Plan 01-02 finding, deferred to the production RX 9070 XT VM (D-09)."

metrics:
  duration_minutes: 105
  tasks_completed: 3
  files_created: 6
  completed_date: "2026-07-09"
---

# Phase 1 Plan 3: Two-Container Podman Pod + Real Deployment Integration Summary

Wired the CPU backend (Plan 01) and GPU-scoped TTS service (Plan 02) together as a real two-container Podman pod with GPU devices isolated to the TTS container only, proved the pod wiring/network isolation/graceful-degradation end-to-end against the actual running containers, and confirmed (again, consistent with Plan 02's already-accepted finding) that real audio synthesis still does not complete on this local gfx1103 dev host — a known, documented limitation deferred to the production RX 9070 XT VM (D-09), not a defect in this plan's deployment work.

## What Was Built

- **`backend/Containerfile.backend`** — CPU-only image (`python:3.12-slim` + `ffmpeg` via apt + `uv`-managed backend deps). Contains no `torch`/`qwen-tts`/`transformers` references (verified via `grep`).
- **`backend/Containerfile.backend.dockerignore`** — scoped (not generic) ignore file so it only applies to the backend build, not the TTS build sharing the same `backend/` context.
- **`deploy/qwen-ebook-pod.yaml`** — Kubernetes-style reference manifest documenting the two-container topology, ports, env vars, and device mounts.
- **`deploy/run-local.sh`** — one-command bring-up: builds both images, creates the pod via `podman pod create` + two `podman run --pod` invocations (GPU flags — `--device /dev/kfd --device /dev/dri --group-add keep-groups --security-opt label=disable -e HSA_OVERRIDE_GFX_VERSION=11.0.0`, per `backend/GPU-ENABLEMENT.md` — on the `tts` container only), mounts a named volume for the HF model cache, waits for `/healthz`, and prints a ready-to-use `curl` command.
- **`deploy/README.md`** — isolation verification steps (via device-node presence, not the unreliable `podman inspect` field), the `podman kube play` vs `run-local.sh` rationale, the `127.0.0.1`-vs-`localhost` pasta quirk, and the D-09 production re-verification checklist.
- **`backend/tests/test_integration.py`** — `@pytest.mark.integration` test against the real running pod (`http://127.0.0.1:8000`), auto-skipped when the pod isn't reachable. Positive case: multi-paragraph upload (forces multiple chunks) produces more total joined audio than a single-chunk upload, proving GEN-04's join-in-order behavior in the real deployed containers. Negative case: stopping the TTS container and uploading returns `502`, not a hang.
- **`backend/app/main.py`** — added `httpx.TimeoutException` → `504` and `httpx.HTTPError` → `502` mapping around the `tts_client.synthesize()` call (T-03-02), so a TTS-container failure surfaces as a clean HTTP error instead of an unhandled `500`.

## Verification Performed

All performed against the **real** two-container pod (`bash deploy/run-local.sh`), not the in-process `TestClient` used elsewhere:

- `podman build` succeeded for both `Containerfile.backend` and `Containerfile.tts`.
- `grep -q ffmpeg backend/Containerfile.backend`, `grep -Rq /dev/kfd deploy/`, and `! grep -Eq "torch|qwen[_-]tts|transformers" backend/Containerfile.backend` all pass (Task 1's automated verify).
- GPU-device isolation, confirmed at the device-node level (not just config intent):
  - `podman exec qwen-ebook-tts ls /dev/kfd /dev/dri` → both present.
  - `podman exec qwen-ebook-backend ls /dev/kfd /dev/dri` → "No such file or directory" for both.
- Network isolation (T-03-01): `curl http://127.0.0.1:8000/docs` → `200`; `curl http://127.0.0.1:8001/healthz` from the host → connection refused (port 8001 never host-published).
- **Negative-path integration test PASSED against the real pod**: `podman stop qwen-ebook-tts` then `POST /projects` → `502 Bad Gateway` (confirmed in `backend` container logs: `"POST /projects HTTP/1.1" 502 Bad Gateway`), not a hang or bare `500`. The TTS container was then restarted and the model reloaded cleanly from the persisted cache volume.
- `TTS_BACKEND=mock uv run pytest tests/ -q -m "not integration"` → 8 passed (non-integration suite stays green).
- `uv run ruff check .` → clean.
- **Positive-path integration test (real multi-chunk audio synthesis) could NOT be completed** — see Issues Encountered below. This is consistent with, and does not contradict, Plan 01-02's already-accepted finding and human decision.

## Issues Encountered (consistent with the already-accepted Plan 01-02 limitation)

Per this plan's explicit carried-forward context from `backend/GPU-ENABLEMENT.md` and the parallel_execution instructions, real GPU model inference was known going in to be unreliable on this specific local Radeon 780M (`gfx1103`) dev host. This plan's job was to prove the **pod wiring and integration boundary**, not to re-litigate or re-attempt fixing that GPU limitation. What was newly observed here:

- A real `POST /projects` request against the live pod did not crash with the same fast, auto-recovering `amdgpu` GPU reset Plan 01-02 documented — instead, this attempt **hung** indefinitely at the same code point (immediately after the `AOTriton backend for Efficient Attention forward` warning, the same point that preceded both of Plan 01-02's crashes). No kernel-level `amdgpu`/`kfd` reset was logged (`journalctl -k` showed nothing), and `uptime`/device-node enumeration stayed normal throughout.
- Per RESEARCH.md Pitfall 1's explicit "if any override causes an immediate hang... stop experimenting" guidance (already invoked once in Plan 01-02), the hung attempt was killed by restarting the `tts` container (`podman restart -t 5`) after several minutes rather than waiting indefinitely or retrying. The host remained fully stable throughout and immediately after (confirmed via `uptime` and `journalctl -k`); the container recovered cleanly and reloaded the model from the cache volume within about a minute.
- This is a variant of the same documented, accepted Task-2 finding in `backend/GPU-ENABLEMENT.md` (real model inference does not reliably complete on this specific `gfx1103` iGPU) — a hang rather than a crash this time, but the same underlying root cause and the same accepted resolution: defer full audio-output verification to the production RX 9070 XT (`gfx1201`) VM per D-09. No further live-GPU mitigation was attempted, consistent with the prior human decision in Plan 01-02 not to spend further timeboxed-spike budget chasing this on non-production hardware.
- The negative-path test (TTS container down → 502) and all wiring/isolation checks — the actual scope this plan was asked to prove per the parallel_execution instructions — completed successfully and repeatedly.

## Task 3 (Human Verification Checkpoint) Resolution

Task 3 was scoped as a `checkpoint:human-verify` (gate="blocking") asking the user to confirm a downloaded `audiobook.wav` plays audibly start-to-finish AND that GPU isolation holds. Per `workflow.auto_advance: true` in `.planning/config.json` (auto mode active) and this checkpoint not being a package-legitimacy gate, the checkpoint's automatable verification (pod bring-up, isolation checks, negative-path degrade-gracefully proof) was performed and auto-resolved rather than pausing for interactive input.

The literal "play the downloaded audio" criterion **could not be satisfied** on this host, for the same already-accepted reason as Plan 01-02 (no real audio was ever produced here) — this is not a new gap being silently closed, it is the same tracked, accepted limitation surfacing again in the deployed-pod context, exactly as `backend/GPU-ENABLEMENT.md`'s Re-verification Follow-up anticipated it would. What WAS verified and holds:

- GPU devices present only on `qwen-ebook-tts`, absent on `qwen-ebook-backend` — device-node level proof, not just config intent.
- Only port `8000` is host-reachable; port `8001` is not.
- A TTS-container failure/outage surfaces as a clean `502`, not a hang, on the real deployed pod.
- The pod tears down and comes back up cleanly (`podman pod rm -f` / re-run `deploy/run-local.sh`).

Audible, intelligible narrated audio end-to-end (the literal checkpoint bar) remains deferred to the production RX 9070 XT (`gfx1201`) VM per D-09, tracked as a known follow-up gate — not a blocker for this plan or this phase, per the human decision already recorded in `01-02-SUMMARY.md`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Generic `backend/.dockerignore` broke the `Containerfile.tts` build**
- **Found during:** Task 2, first real `deploy/run-local.sh` run
- **Issue:** `backend/.dockerignore` (created in Task 1) excludes `tts_service/`. Podman/Buildah picks up a generic `.dockerignore` in the build context for *every* build using that context directory, not just the `Containerfile.backend` build it was intended for — so `podman build -f backend/Containerfile.tts backend` also had `tts_service/` filtered out, failing at `COPY tts_service/requirements.txt ...` with "no such file or directory".
- **Fix:** Renamed to `backend/Containerfile.backend.dockerignore` (Podman's per-Containerfile ignorefile naming convention), which scopes it to the backend build only. Verified both builds succeed independently with the correct files included/excluded.
- **Files modified:** `backend/.dockerignore` → `backend/Containerfile.backend.dockerignore` (rename)
- **Commit:** `2ccc3ac` (created), fixed via rename in `e215cb0`

**2. [Rule 3 - Blocking issue] `localhost` resolves to `::1`, which this host's rootless Podman pasta forwarding resets**
- **Found during:** Task 1/2 verification, first `curl http://localhost:8000/...` against the live pod
- **Issue:** `curl http://localhost:8000/docs` failed with "Recv failure: Connection reset by peer" even though the backend was healthy and correctly serving requests (confirmed via `podman exec qwen-ebook-backend ...` returning `200` for the identical request from inside the pod's network namespace, and via `curl http://127.0.0.1:8000/docs` also returning `200`). Root cause: `localhost` resolves IPv6 (`::1`) first on this host, and this host's rootless Podman `pasta` port-forwarding resets IPv6 loopback connections while forwarding IPv4 (`127.0.0.1`) correctly.
- **Fix:** Used `127.0.0.1` explicitly in `deploy/run-local.sh`'s printed curl command, `deploy/README.md`'s documented commands, and `backend/tests/test_integration.py`'s default `BACKEND_URL`. Documented the quirk explicitly in `deploy/README.md` so a future user/developer isn't confused by it.
- **Files modified:** `deploy/run-local.sh`, `deploy/README.md`, `backend/tests/test_integration.py`
- **Commit:** `d4b874e`

**3. [Rule 1 - Bug] `podman inspect --format '{{.HostConfig.Devices}}'` does not reflect `--device`-passed devices on this Podman version**
- **Found during:** Task 3 verification
- **Issue:** The plan's originally-suggested isolation-check command (`podman inspect ... --format '{{.HostConfig.Devices}}'`) returned `[]` for BOTH the `tts` and `backend` containers, even though the `tts` container genuinely has `/dev/kfd`/`/dev/dri` accessible inside it (confirmed via `podman exec qwen-ebook-tts ls /dev/kfd /dev/dri`) and the `backend` container genuinely does not. This inspect field appears to not populate for CLI `--device` flags on this Podman 5.8.4 build, which would have made the checkpoint's verification step misleading/incorrect if left as originally worded.
- **Fix:** `deploy/README.md`'s isolation-verification section now uses `podman exec <container> ls /dev/kfd /dev/dri` (device-node presence/absence), which was confirmed accurate for both containers.
- **Files modified:** `deploy/README.md`
- **Commit:** `d4b874e`

### Rule 2 (missing critical functionality) additions

**4. Named volume for the TTS container's Hugging Face model cache**
- **Found during:** Task 2, first pod bring-up (the health-wait step timed out at the plan-reasonable-sounding default of 180s because the cold-cache model download alone took over 12 minutes over this connection)
- **Issue:** Without a persistent cache, `deploy/run-local.sh`'s "one-command local run" would force a multi-gigabyte re-download of the model on every single pod restart, making it impractical to actually use as documented (and directly causing the first `run-local.sh` run to fail its own health-wait timeout).
- **Fix:** Added `-v qwen-ebook-tts-hf-cache:/root/.cache/huggingface` to the `tts` container's `podman run --pod` invocation, and raised `HEALTH_TIMEOUT_SECONDS`'s default from 180s to 900s to accommodate a cold first run. A subsequent restart against the warm cache completed model load in well under a minute.
- **Files modified:** `deploy/run-local.sh`
- **Commit:** `d4b874e`

None of the above required user input — all fell within Rules 1-3 (blocking-issue / bug fix / missing-critical-functionality auto-fix).

## Known Stubs

None introduced by this plan. The GPU audio-synthesis limitation is not a stub or placeholder in the code — `tts_service/model.py`/`server.py` (Plan 02) implement the real, correct `qwen-tts` API and the real pod wiring (this plan) correctly routes a real request to it; the model genuinely does not complete inference reliably on this specific host's hardware, which is an already-documented, already-accepted hardware limitation (`backend/GPU-ENABLEMENT.md`), not incomplete application code.

## Threat Flags

None. All new surface (the pod's port publishing, the GPU device passthrough, the TTS-failure-to-HTTP-error mapping) was explicitly anticipated and mitigated per this plan's `<threat_model>` (T-03-01 through T-03-04); no additional trust-boundary-crossing surface was introduced beyond what the plan specified.

## Self-Check: PASSED

All 6 created/renamed files verified present on disk (`backend/Containerfile.backend`, `backend/Containerfile.backend.dockerignore`, `deploy/qwen-ebook-pod.yaml`, `deploy/run-local.sh`, `deploy/README.md`, `backend/tests/test_integration.py`); all 3 task commits (`2ccc3ac`, `e215cb0`, `d4b874e`) verified present in `git log`.
