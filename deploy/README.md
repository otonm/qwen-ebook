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
curl -F file=@sample.txt http://localhost:8000/projects -o audiobook.wav
```

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
place GPU device nodes are passed in. Verify the isolation directly:

```bash
podman inspect qwen-ebook-backend --format '{{.HostConfig.Devices}}'  # -> []
podman inspect qwen-ebook-tts     --format '{{.HostConfig.Devices}}'  # -> /dev/kfd, /dev/dri
```

Only port `8000` (the backend) is reachable from the host. Port `8001` (the
TTS service) stays internal to the pod network — confirm with
`curl http://localhost:8001/healthz` from the host, which should fail to
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

## Follow-up: re-verify on the production RX 9070 XT VM (D-09)

This entire local run was performed and verified against a `gfx1103`
integrated GPU that is not on ROCm's officially supported architecture
list. The production deployment target is an AMD RX 9070 XT (`gfx1201`,
RDNA4, officially supported by ROCm 7.2+, dedicated 16GB VRAM). Before
relying on this deployment in production:

1. Re-run `bash deploy/run-local.sh` on the RX 9070 XT VM from scratch.
2. Re-verify whether the `HSA_OVERRIDE_GFX_VERSION` override and
   `--security-opt label=disable` are still necessary — `gfx1201` is
   officially supported, so neither workaround is expected to be needed,
   but this has not been tested.
3. Confirm a real `POST /projects` request returns audible, intelligible
   synthesized audio end-to-end (the actual GEN-01/DEPL-01 audio-output
   bar that this local dev host's GPU could not clear — see
   `backend/GPU-ENABLEMENT.md`).

This is a tracked follow-up gate, not part of this phase's success bar
(01-SKELETON.md "Follow-up Gate").
