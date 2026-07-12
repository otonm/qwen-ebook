# Local Full-Stack Deployment (Phase 1 Walking Skeleton)

Runs the complete upload -> chunk -> synthesize -> join -> download pipeline
as a real two-container Podman pod, matching the permanent DEPL-01
architecture: a CPU-only `backend` container and a GPU-scoped `tts`
container, isolated from each other.

## One-command bring-up

```bash
bash deploy/run-local.sh
```

This builds both images (`backend/Containerfile.backend`,
`backend/Containerfile.tts`), creates a Podman pod, starts the `tts`
container first (GPU devices attached), then the `backend` container (no
GPU devices), waits for the TTS service's `/healthz` to report ready
(model load can take a few minutes on first run), and prints a ready-to-use
`curl` command.

Then:

```bash
curl -F file=@sample.txt http://127.0.0.1:8000/projects -o audiobook.wav
```

**Use `127.0.0.1`, not `localhost`.** This was originally observed as a
rootless-Podman `pasta` port-forwarding quirk (IPv4 loopback forwarded
correctly, IPv6 `::1` reset) on the gfx1103 dev host; `run-local.sh` now
runs rootful by default (see below), but `127.0.0.1` remains the safe
default either way.

Tear down:

```bash
sudo podman pod rm -f qwen-ebook
```

## Two-container isolation (DEPL-01)

| Container | Image | GPU devices | Host-published port |
|---|---|---|---|
| `qwen-ebook-tts` | `localhost/qwen-ebook-tts:dev` | `/dev/kfd`, `/dev/dri` | none (pod-internal `8001` only) |
| `qwen-ebook-backend` | `localhost/qwen-ebook-backend:dev` | none | `8000` |

This split is the permanent architecture, not a spike shortcut: the CPU
backend never imports `torch`/`qwen-tts`, and the TTS container is the only
place GPU device nodes are passed in. Verify the isolation directly by
checking for the actual device nodes inside each container (more reliable
on this Podman version than `podman inspect --format '{{.HostConfig.Devices}}'`,
which does not reflect `--device`-passed devices in its JSON output even
though the devices are genuinely present/absent inside the container):

```bash
sudo podman exec qwen-ebook-tts     ls /dev/kfd /dev/dri   # -> present
sudo podman exec qwen-ebook-backend ls /dev/kfd /dev/dri   # -> "No such file or directory"
```

Only port `8000` (the backend) is reachable from the host. Port `8001` (the
TTS service) stays internal to the pod network — confirm with
`curl http://127.0.0.1:8001/healthz` from the host, which should fail to
connect (T-03-01: the GPU service is unreachable except via the backend).

## Why `run-local.sh` instead of `podman kube play deploy/qwen-ebook-pod.yaml`

`deploy/qwen-ebook-pod.yaml` documents the pod topology (images, ports, env
vars, device mounts) as a Kubernetes-style manifest. `run-local.sh` instead
uses `podman pod create` + two `podman run --pod` invocations, run rootful
(`sudo podman`) with `--user 0:0` on the `tts` container — the flag
combination D-09 verification found necessary for real `/dev/kfd` access
(see "Production VM bring-up" below; rootless `--group-add keep-groups`
was tried first and does not grant device access on this Podman/crun
combination, independent of GPU architecture). The YAML remains the
canonical reference for the topology.

## Known limitation on this dev host (accepted, not a bug)

This local dev host is an AMD Radeon 780M (`gfx1103`) integrated GPU, not
the production target. Per `backend/GPU-ENABLEMENT.md`, real Qwen3-TTS
model inference (`POST /synthesize` on real text) reproducibly crashes the
GPU on this specific hardware with a recoverable `amdgpu` reset (host
stays stable; a fresh request after the crash typically fails the same
way). This was accepted by the user as a documented spike limitation:

- The pod wiring, network isolation, and GPU-device isolation described
  above ARE the thing this plan proves and verifies on this host.
- A full audible end-to-end `curl` response (real synthesized audio) is
  **not** expected to succeed on this dev host — that verification is
  deferred to the production RX 9070 XT (`gfx1201`) VM.

## Production VM bring-up

The production target is an AMD RX 9070 XT (`gfx1201`, RDNA4, officially
ROCm-7.2+-supported, dedicated 16GB VRAM) Debian 13 host. This section
covers getting from a fresh VM to a running pod; it does not yet exist, so
none of this has been run against real hardware (D-09).

### Reaching the VM

The VM joins this Tailscale tailnet and is reached exclusively via
Tailscale SSH at its Tailscale hostname — `ssh <user>@<tailscale-hostname>`.
It has no public internet exposure, matching this project's Tailscale-only
access model (no port-forwarding, no public IP).

### One-time bootstrap

On the fresh Debian 13 host, run once:

```bash
bash deploy/bootstrap-vm.sh
```

This idempotently installs Podman, Tailscale, and git; adds the invoking
user to the `render` and `video` groups (needed for `/dev/kfd`/`/dev/dri`
access without root — see `backend/GPU-ENABLEMENT.md`); and clones this
repo. It deliberately leaves two manual follow-ups to the user (it never
runs them, since both need interactive input):

1. Run `tailscale up --ssh` via sudo to join the tailnet and enable
   Tailscale SSH (interactive auth).
2. Re-login (or `newgrp render` / `newgrp video`) for the new group
   membership to take effect.

### D-09 GPU re-verification checklist

This entire local run (and `run-local.sh`'s GPU flags) was originally
performed and verified against a `gfx1103` integrated GPU that is not on
ROCm's officially supported architecture list — see
`backend/GPU-ENABLEMENT.md` for the full historical gfx1103 fallback-ladder
investigation log. Re-verified directly on the production RX 9070 XT VM:

1. ✅ `rocminfo` and a real on-device PyTorch matmul (`backend/tts_service/smoke_gpu.py`)
   both pass with `gfx1201` correctly identified as `AMD Radeon RX 9070 XT`
   — **no** `HSA_OVERRIDE_GFX_VERSION` or `GPU_SECURITY_OPT` needed, confirming
   gfx1201's official ROCm support means neither dev-host workaround applies
   here. Host stayed stable throughout (no `amdgpu`/`kfd` resets).
2. ❌ Rootless Podman (`--group-add keep-groups`, with or without
   `--privileged`, with or without explicit numeric `--group-add`) could
   **not** reach `/dev/kfd` on this host — the render/video host GIDs are
   lost in the rootless user-namespace mapping regardless of host group
   membership. This is a Podman/crun-level gap, not GPU-architecture-specific.
3. ✅ Rootful Podman (`sudo podman run --user 0:0 --device /dev/kfd --device /dev/dri`)
   works cleanly. `run-local.sh` now runs rootful by default (see above).
4. ✅ `POST /projects` through the full pod (rootful, `--user 0:0` TTS
   container) returns a real WAV: mono, 24kHz, 21.4s for a 3-sentence
   sample, 96.5% non-zero samples, max amplitude 22528/32768 — not silence
   or a placeholder. This also surfaced and fixed a real bug: `qwen-tts`'s
   tokenizer imports the `sox` PyPI wrapper (plus the system `sox` binary
   it shells out to) transitively — neither was installed (a prior decision,
   `IN-03`, had removed `sox` believing it unused by this project's own
   code). Both are now installed in `Containerfile.tts`/`requirements.txt`.

Tracked follow-up gate, not part of this phase's success bar (01-SKELETON.md
"Follow-up Gate") — all four items now closed.

## Quadlet (systemd-managed) deployment

`run-local.sh` above is the manual dev/re-bring-up path — nothing persists a
teardown or a VM reboot. For the permanent production deployment (DEPL-02),
the same two-container pod is expressed as three Podman Quadlet unit files
(`deploy/qwen-ebook.pod`, `deploy/qwen-ebook-tts.container`,
`deploy/qwen-ebook-backend.container`), managed by root's systemd. This is
the form that survives a reboot and restarts on failure.

**Reconfirm the Podman version on the VM first.** Quadlet's exact key set has
shifted across Podman 4.4–5.x releases; run `podman --version` over
Tailscale SSH and cross-check against the unit files' header comments before
assuming this syntax is correct on this specific host.

### Install the units

Over Tailscale SSH, as root (or via `sudo`):

```bash
sudo cp deploy/qwen-ebook.pod deploy/qwen-ebook-tts.container deploy/qwen-ebook-backend.container \
  /etc/containers/systemd/
sudo chown root:root /etc/containers/systemd/qwen-ebook*
sudo chmod 0644 /etc/containers/systemd/qwen-ebook*
sudo systemctl daemon-reload
```

Root-owned `0644` permissions match standard systemd unit-file convention —
no secret material lives in these units (the only env vars are the
non-sensitive `TTS_BACKEND`/`TTS_SERVICE_URL`).

### Bring the pod up

Starting the backend unit pulls in the pod and the TTS unit automatically,
via each unit's `Requires=`:

```bash
sudo systemctl start qwen-ebook-backend.service
```

### One-time tailnet exposure

The pod publishes the backend port to `127.0.0.1:8000` only — never
`0.0.0.0` — so `tailscale serve` is the sole path from the tailnet in
(DEPL-02, no public exposure, no added auth layer). Run this once; it
persists across reboots independently of the Quadlet units themselves:

```bash
sudo tailscale serve --bg 8000
```

**This is Open Question 2 from the phase research** — whether `tailscale
serve` on the host actually reaches a pod port published to loopback via
Podman's port-publish mechanism was not assumed; it must be confirmed live
on the VM at this step, not taken on faith.

### Post-deploy verification (do all four before considering DEPL-02 done)

1. **GPU devices are on the TTS container only** (Pitfall 4 — the flag set
   most often dropped in a hand-translated Quadlet unit):
   ```bash
   sudo systemctl status qwen-ebook-tts.service
   sudo podman exec qwen-ebook-tts ls /dev/kfd /dev/dri      # -> present
   sudo podman exec qwen-ebook-backend ls /dev/kfd /dev/dri  # -> "No such file or directory"
   ```
2. **Backend answers on host loopback:**
   ```bash
   curl 127.0.0.1:8000/healthz
   ```
   Expect a `200` response.
3. **Reachable from a second tailnet device:** from another machine on the
   same tailnet, open the app's Tailscale Serve URL (`https://tts.<tailnet
   name>.ts.net`, or run `tailscale serve status` on the VM to confirm the
   exact URL) and confirm the project list loads, then run a small
   end-to-end generate.
4. **Unreachable off-tailnet:** confirm no device outside the tailnet can
   reach the app — there is no public port published (`PublishPort=` in the
   `.pod` unit binds loopback only), so this should fail by construction,
   but is worth a live check rather than an assumption.

### Tear down / restart

```bash
sudo systemctl stop qwen-ebook-backend.service
sudo systemctl restart qwen-ebook-backend.service
```

Stopping/restarting the backend unit tears down/brings back the whole pod
via the `Requires=`/`After=` ordering in the unit files.
