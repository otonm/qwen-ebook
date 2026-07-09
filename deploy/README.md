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

**Use `127.0.0.1`, not `localhost`.** On this host, rootless Podman's
`pasta` port-forwarding correctly forwards IPv4 loopback (`127.0.0.1`) but
resets IPv6 loopback (`::1`) connections, and `localhost` resolves to
`::1` first on most systems — `curl http://localhost:8000/...` reproducibly
fails with "Recv failure: Connection reset by peer" here even though the
backend is healthy and reachable on `127.0.0.1`. This is a host
networking-stack quirk, not an application bug (confirmed via
`podman exec qwen-ebook-backend ...` returning 200 for the same request
made from inside the pod network namespace).

Tear down:

```bash
podman pod rm -f qwen-ebook
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
podman exec qwen-ebook-tts     ls /dev/kfd /dev/dri   # -> present
podman exec qwen-ebook-backend ls /dev/kfd /dev/dri   # -> "No such file or directory"
```

Only port `8000` (the backend) is reachable from the host. Port `8001` (the
TTS service) stays internal to the pod network — confirm with
`curl http://127.0.0.1:8001/healthz` from the host, which should fail to
connect (T-03-01: the GPU service is unreachable except via the backend).

## Why `run-local.sh` instead of `podman kube play deploy/qwen-ebook-pod.yaml`

`deploy/qwen-ebook-pod.yaml` documents the pod topology (images, ports, env
vars, device mounts) as a Kubernetes-style manifest. However, this host's
proven-working GPU passthrough configuration (see
`backend/GPU-ENABLEMENT.md`) requires `--group-add keep-groups`, which has
no equivalent field in plain Kubernetes Pod YAML / `podman kube play`.
`podman run --pod` supports `--group-add` directly, so `run-local.sh` uses
`podman pod create` + two `podman run --pod` invocations instead of
`podman kube play` on this host. The YAML remains the canonical reference
for the topology and is usable with `podman kube play` on a host where
`--group-add keep-groups` isn't required (e.g. once the host's
`container_use_devices` SELinux boolean is enabled — see
`backend/GPU-ENABLEMENT.md`'s tracked follow-up).

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

This entire local run (and `run-local.sh`'s GPU flags) was performed and
verified against a `gfx1103` integrated GPU that is not on ROCm's
officially supported architecture list — see `backend/GPU-ENABLEMENT.md`
for the full historical gfx1103 fallback-ladder investigation log. Before
relying on this deployment in production, on the RX 9070 XT VM:

1. Run `bash deploy/run-local.sh` from scratch with **no** GPU-flag env
   vars set (`GPU_SECURITY_OPT` and `HSA_OVERRIDE_GFX_VERSION` unset) —
   `gfx1201` is officially supported, so neither dev-host workaround is
   expected to be needed.
2. Confirm a real `POST /projects` (or `/synthesize`) request returns
   audible, intelligible synthesized audio end-to-end (the actual
   GEN-01/DEPL-01 audio-output bar that the `gfx1103` dev host's GPU could
   not clear).
3. Only if a genuine failure is reproduced, fall back by exporting
   `HSA_OVERRIDE_GFX_VERSION` and/or `GPU_SECURITY_OPT` (e.g. `label=disable`)
   — do not pre-emptively carry the dev-host workarounds over.

This is a tracked follow-up gate, not part of this phase's success bar
(01-SKELETON.md "Follow-up Gate").
