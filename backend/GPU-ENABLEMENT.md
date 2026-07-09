# GPU Enablement Log — AMD Radeon 780M (gfx1103)

**Host:** Bazzite/Fedora-Atomic, kernel `7.0.9-ogc3.2.fc44`, Podman `5.8.4`, SELinux Enforcing.
**GPU:** AMD Radeon 780M (Phoenix/HawkPoint, RDNA3, `gfx1103`) — integrated APU, not on ROCm's officially-supported architecture list.
**Base image:** `docker.io/rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1` (`torch` `2.9.1+rocm7.2.4`, HIP `7.2.53211`).

This log records the actual, ordered fallback-ladder investigation performed on this exact host, per RESEARCH.md Common Pitfalls 1/2/5 and Open Question 1. Re-verification on the production RX 9070 XT (`gfx1201`) VM is a tracked follow-up (D-09), not covered here.

## Result Summary

**Working configuration (rung 2 of the fallback ladder):**

```bash
podman run --rm \
  --device /dev/kfd --device /dev/dri \
  --group-add keep-groups \
  --security-opt label=disable \
  -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
  localhost/qwen-ebook-tts:dev \
  python /app/tts_service/smoke_gpu.py
```

- `cuda.is_available()` = `True`
- Device detected: `AMD Radeon 780M Graphics`, reported `gcnArchName` = `gfx1100` (spoofed via the override)
- 256x256 on-device matmul: **PASS**, exit code 0
- Host remained fully stable throughout the rung 1/2 compute-smoke investigation below (no `amdgpu`/`kfd` kernel resets, no page faults, no desktop hang — confirmed via `journalctl -k` and `uptime` after each attempt)

**IMPORTANT — updated after Task 2:** this rung-2 configuration is proven sufficient for isolated GPU compute (device detection + on-device matmul), which was Task 1's success criterion. It is **not** sufficient for full Qwen3-TTS model inference on this host — real `/synthesize` calls reproducibly crash with a recoverable `amdgpu` GPU reset. See "Task 2 finding" section below for the full detail. This host is not the production target (D-09), so this finding is being surfaced as a decision checkpoint rather than solved at all costs here.

## Fallback Ladder — What Was Actually Tried, In Order

### Rung 1: Native — no `HSA_OVERRIDE_GFX_VERSION`

```bash
podman run --rm --device /dev/kfd --device /dev/dri --group-add keep-groups \
  localhost/qwen-ebook-tts:dev python /app/tts_service/smoke_gpu.py
```

**Result: FAILED.** Device detection succeeded (`cuda.is_available()=True`, `gcnArchName=gfx1103`, correct VRAM/name reported) — RESEARCH.md Open Question 1 is answered: this host's kernel-bundled `amdgpu`/KFD driver *does* expose gfx1103 as a compute agent, not just a display device. However, the very first on-device tensor allocation (`torch.randn(4,4, device="cuda")`) crashed the process with **exit code 139** (SIGSEGV / general protection fault) inside `libamdhip64.so.7.2.70204`, before any matmul was attempted.

`journalctl -k` for this run showed:
```
audit: AVC avc: denied { map } for pid=... comm="python" path="/dev/kfd" ... tcontext=system_u:object_r:hsa_device_t:s0 tclass=chr_file permissive=0
kernel: traps: python[...] general protection fault ip:...libamdhip64.so.7.2.70204[...]
```

Per RESEARCH.md Pitfall 5 ("only reach for `label=disable` if `ausearch`/`journalctl` shows a genuine denial against these specific device types") — this is exactly that genuine denial: SELinux is blocking `mmap()` (`map` permission) of `/dev/kfd` even though the device node itself carries the correct `hsa_device_t` label. `ausearch` itself required root and was not available in this session (`Error opening /var/log/audit/audit.log (Permission denied)`); the same denial was independently confirmed via `journalctl` (readable without root on this host), which is an equally valid audit source.

Root cause identified via `getsebool -a`: the `container_use_devices` boolean is **off** on this host (`container_use_dri_devices` is on, which is why plain `/dev/dri` display access works fine, but compute access via `/dev/kfd` needs the broader `container_use_devices` boolean). Enabling it persistently (`sudo setsebool -P container_use_devices on`) requires root, which this session did not have (`sudo: a password is required`).

### Isolating the SELinux variable

To confirm SELinux was the actual blocker (not a red herring), two isolation tests were run:

1. `--security-opt label=disable` alone (bypasses the container's SELinux confinement without needing host root/setsebool): **still crashed**, same GPF at the same `libamdhip64.so` offset, but `journalctl` showed **no** new AVC denial for that run — proving the SELinux `map` denial actually was suppressed, yet the crash persisted for a different reason.
2. `--privileged --device /dev/kfd --device /dev/dri --group-add keep-groups` (no override): **still crashed** identically, again no AVC denial. Host stayed stable (`uptime` nominal, no kernel resets).

Conclusion: SELinux's `container_use_devices=off` gap is real and does independently block native (non-overridden) GPU access — see the rung-1 log above — but is not sufficient on its own to explain the crash once the SELinux confinement is lifted. There is a second, deeper issue.

### Rung 2: `HSA_OVERRIDE_GFX_VERSION=11.0.0` (cautious, per Pitfall 1)

Per RESEARCH.md Pitfall 1's caution ("if any override value causes an immediate hang, kill it and stop experimenting... a real hard-lock has been reported for this architecture"), the override was tried with a hard `timeout 45` wrapper and active `journalctl`/`uptime` monitoring immediately after, watching specifically for kernel-level `amdgpu` resets or a desktop hang — **not** just a process crash.

- `--device /dev/kfd --device /dev/dri --group-add keep-groups -e HSA_OVERRIDE_GFX_VERSION=11.0.0` (no elevated privilege): crashed with a different, more specific error this time — `Memory critical error by agent node-0 (Agent handle: 0x...) on address 0x... Reason: Memory in use.` — a genuine ROCm/HIP-level error message (not a bare SIGSEGV), and the SELinux `map` denial for `/dev/kfd` was present again in `journalctl` for this run (since `--security-opt label=disable` wasn't passed this time). **Host stayed fully stable** — no kernel resets, no hang, `uptime`/`/dev/kfd`/`/dev/dri` all normal immediately after. This confirms `HSA_OVERRIDE_GFX_VERSION=11.0.0` itself is safe on this host (unlike the `11.0.2` value RESEARCH.md's Assumption A1 flags as causing a full hard-lock elsewhere — that value was deliberately never tried here).
- `--privileged --device /dev/kfd --device /dev/dri --group-add keep-groups -e HSA_OVERRIDE_GFX_VERSION=11.0.0`: **PASSED.** Tensor creation, `torch.cuda.synchronize()`, and a real on-device matmul all completed successfully with correct numeric output.
- `--security-opt label=disable --device /dev/kfd --device /dev/dri --group-add keep-groups -e HSA_OVERRIDE_GFX_VERSION=11.0.0` (narrower than `--privileged`, matching Pitfall 5's minimal-scope guidance): **PASSED**, identical result. This is the adopted minimal-privilege configuration — it avoids `--privileged`'s much broader grant (all Linux capabilities, disabled seccomp filtering, etc.) while still resolving the confirmed SELinux `map` denial on `/dev/kfd`.

Re-running the actual `smoke_gpu.py` script with this exact configuration passed cleanly (exit code 0) and was reproducible.

### Rung 3: rocBLAS/Tensile kernel patch (Pitfall 2)

**Not needed.** Once the SELinux denial was bypassed and the override applied, matmul succeeded directly with no rocBLAS/Tensile "no kernel found" style error — this host's `rocm/pytorch:rocm7.2.4` image's bundled rocBLAS does have working GEMM kernels for the overridden `gfx1100` target on this GPU.

## Working Passthrough Flags (adopted for Tasks 2/3 and going forward)

```
--device /dev/kfd --device /dev/dri --group-add keep-groups --security-opt label=disable
-e HSA_OVERRIDE_GFX_VERSION=11.0.0
```

**Deviation from RESEARCH.md's default recommendation:** RESEARCH.md's primary recommendation was to try no override first and leave SELinux Enforcing without `label=disable` unless a genuine denial was confirmed. Both of those conditions were tested and found necessary to relax on *this specific host* — native (no override) crashes on the very first GPU tensor allocation, and a genuine SELinux `map` denial on `/dev/kfd` (root cause: `container_use_devices` SELinux boolean is off, and this session had no root/sudo access to flip it persistently) blocks passthrough without `--security-opt label=disable`. Both findings are documented here with the exact `journalctl` evidence per Pitfall 5's evidentiary bar.

**Follow-up (tracked, not blocking this plan):** A host administrator with root access could instead run `sudo setsebool -P container_use_devices on` to fix the SELinux gap without needing `--security-opt label=disable` per-container. This was not done in this session (no sudo password available to the executing agent) and does not change the `HSA_OVERRIDE_GFX_VERSION=11.0.0` requirement, which is independent of the SELinux issue (proven via the `--privileged` isolation test above, which also required the override to pass).

## SELinux Note (Pitfall 5 compliance)

This host's device nodes carry the labels RESEARCH.md documented: `/dev/kfd` is `hsa_device_t`, `/dev/dri/renderD128` is `dri_device_t` — both are correctly labeled for container passthrough per the standard `container-selinux` policy. The actual gap found is a **boolean**, not a device mislabel: `container_use_devices` (`getsebool container_use_devices` → `off`), distinct from `container_use_dri_devices` (`on`, which is why `/dev/dri`-only access such as display/render would work without any extra flags). `--security-opt label=disable` was adopted only after confirming a genuine denial via `journalctl` (per Pitfall 5's bar), not reflexively.

## Environment Details

| Item | Value |
|---|---|
| GPU | AMD Radeon 780M Graphics (Phoenix/HawkPoint, RDNA3) |
| Native `gcnArchName` | `gfx1103` |
| Overridden `gcnArchName` (via `HSA_OVERRIDE_GFX_VERSION=11.0.0`) | `gfx1100` |
| VRAM reported | 13895 MB (shared system RAM) |
| `torch.__version__` | `2.9.1+rocm7.2.4.git39497456` |
| `torch.version.hip` | `7.2.53211-97f5574fe2` |
| SELinux mode | Enforcing |
| `container_use_devices` (getsebool) | off (root required to change; not changed in this session) |
| `container_use_dri_devices` (getsebool) | on |
| Kernel | `7.0.9-ogc3.2.fc44` (Bazzite/Fedora-Atomic) |

## Task 2 finding: real model inference crashes reproducibly (rung 2 is insufficient for full generation)

After Task 1's smoke test passed cleanly (exit 0) with the rung-2 configuration
(`--security-opt label=disable --device /dev/kfd --device /dev/dri --group-add keep-groups -e HSA_OVERRIDE_GFX_VERSION=11.0.0`),
Task 2's actual `/synthesize` endpoint (real `Qwen3TTSModel.generate_custom_voice()`
call, not a toy matmul) was tested against a running `tts_service.server:app`
container using the identical rung-2 flags. The model loaded successfully
(`GET /healthz` → 200, default speaker `aiden` selected from `['aiden',
'dylan', 'eric', 'ono_anna', 'ryan', 'serena', 'sohee', 'uncle_fu',
'vivian']`), but **every real synthesis call crashed the container**
(exit code 139), reproducibly across two independent container instances.

**Attempt 1** (`POST /synthesize {"text":"Hello, this is a test of the
narrator voice."}`):
```
Setting `pad_token_id` to `eos_token_id`:2150 for open-end generation.
HW Exception by GPU node-1 (Agent handle: 0x182d42e0) reason :GPU Hang
```
Kernel log: `amdgpu 0000:65:00.0: GPU reset begin!` → `GPU reset(1) succeeded!`
then a second `GPU reset(2) succeeded!` (MES failed to respond to
REMOVE_QUEUE, triggered a follow-up MODE2 reset). `kwin_wayland` logged "A
graphics reset not attributable to the current GL context occurred" (the
desktop compositor observed the reset but recovered).

**Attempt 2** (fresh container, same flags, same request): crashed
identically but with a different low-level signature:
```
.../transformers/integrations/sdpa_attention.py:96: UserWarning: Using AOTriton backend for Efficient Attention forward...
MIOpen(HIP): Warning [IsEnoughWorkspace] [GetSolutionsFallback WTI] Solver <GemmFwdRest>, workspace required: 10321920, provided ptr: 0 size: 0
MIOpen(HIP): Warning [IsEnoughWorkspace] [EvaluateInvokers] Solver <GemmFwdRest>, workspace required: 10321920, provided ptr: 0 size: 0
(x2 more of the same warning pair)
Memory access fault by GPU node-1 (Agent handle: 0x3d13f6e0) on address (nil). Reason: Page not present or supervisor privilege.
```
Kernel log: `GPU reset(3) succeeded!` then `GPU reset(4) succeeded!`
(same REMOVE_QUEUE/MES-unrecoverable-state pattern as attempt 1).

**Critical safety observation:** in both attempts, the host's `amdgpu`
kernel driver auto-recovered via its built-in MODE2 GPU reset — `uptime`
and `/dev/kfd`/`/dev/dri` enumeration were confirmed normal after each
crash, and a plain re-run of Task 1's smoke-test matmul immediately after
attempt 1 passed cleanly (exit 0), proving the device itself was not
permanently wedged. This is a *recoverable* fault, not the catastrophic
full-desktop hard-lock RESEARCH.md Pitfall 1 warned about for
`HSA_OVERRIDE_GFX_VERSION=11.0.2` specifically (that value was never
tried). Nonetheless, per Pitfall 1's explicit guidance ("if any override
value causes an immediate hang... stop experimenting"), further live GPU
stress attempts on this host were deliberately stopped after this second
reproduction rather than continuing open-ended retries.

**Root-cause hypothesis (not confirmed):** the `MIOpen ... Solver
<GemmFwdRest>, workspace required: 10321920, provided ptr: 0 size: 0`
warning immediately preceding attempt 2's page fault strongly suggests
RESEARCH.md's secondary-sourced concern is real: [MIOpen gfx1103
precompiled convolution/GEMM kernel database
gap](https://github.com/ROCm/rocm-libraries/issues/6335). The isolated
256x256 matmul in Task 1's smoke test does not exercise this code path
(it's a plain BLAS GEMM, not an attention solver going through MIOpen's
fallback-solver search with an under-provisioned workspace buffer), which
is why Task 1 passed while real model inference — which routes through
`transformers`' SDPA attention integration using the AOTriton backend on
ROCm — did not. This is architecturally distinct from Pitfall 2's
rocBLAS/Tensile GEMM-kernel gap (a different library, MIOpen vs rocBLAS)
and was not something the plan's fallback ladder explicitly enumerated a
rung-3 fix for (the documented Fedora Tensile-kernel-extraction
workaround targets rocBLAS, not MIOpen).

**Rung 3 (rocBLAS/Tensile kernel patch) was not attempted** for this
specific MIOpen/AOTriton failure mode — it targets a different library
than the one implicated here, and per an explicit steer to avoid
open-ended retrying on non-production hardware, further live-GPU
mitigation attempts (e.g., forcing a different SDPA backend, MIOpen env
var tuning `MIOPEN_FIND_MODE`/`MIOPEN_DEBUG_CONV_GEMM`, or attempting a
MIOpen kernel-database patch analogous to Pitfall 2's rocBLAS workaround)
were deliberately deferred to a human decision rather than attempted
blind.

**Bottom line for this plan (D-08):** the GPU IS proven usable for real
compute from inside the isolated container (device detection + on-device
matmul, Task 1's success criterion) on this local `gfx1103` hardware, but
**full Qwen3-TTS model inference does not yet reliably produce real audio
on this specific dev host** — every attempt reproducibly triggers a
recoverable GPU fault/reset during the attention/GEMM-heavy forward pass.
Since this dev host (Radeon 780M / gfx1103, an unsupported iGPU sharing
system RAM, force-overridden to report as `gfx1100`) is explicitly *not*
the production target (RX 9070 XT / gfx1201, officially ROCm-7.2-
supported, dedicated 16GB VRAM — see Re-verification Follow-up below),
this finding may not generalize to production hardware at all. This is
being surfaced as a decision checkpoint rather than solved at all costs
on non-production hardware, per this plan's D-09 scoping.

## Resolution (human decision)

The checkpoint above was presented to the user with three options: (1)
attempt further live-GPU mitigation on this host (MIOpen env var tuning or
a MIOpen kernel-database patch), (2) accept this as a documented spike
limitation and defer full audio-output verification to the production RX
9070 XT VM per D-09, or (3) obtain root/sudo access to test the SELinux
`container_use_devices` fix in isolation.

**Option 2 was chosen.** This plan (01-02) is being closed out with the GPU
compute-capability finding (Task 1: PASS) and the real-inference-crash
finding (Task 2: reproducible GPU fault, auto-recovers cleanly, host stable)
both documented above and accepted as-is. No further live GPU mitigation
was attempted on this dev host. Audio-output verification for `GEN-01`/
`DEPL-01` is deferred to the production RX 9070 XT (`gfx1201`) VM per the
Re-verification Follow-up below, which was already planned as a tracked
follow-up under D-09 rather than this phase's success bar. Plan 01-03 may
proceed using this plan's container image and code with this limitation
flagged.

## Re-verification Follow-up (D-09)

This entire investigation was performed on the local Radeon 780M (`gfx1103`) dev host. The production deployment target is an AMD RX 9070 XT (`gfx1201`, RDNA4, officially supported by ROCm 7.2+). None of the workarounds here (override, `label=disable`) are expected to be necessary on the production VM once it exists — `gfx1201` is officially supported and the RX 9070 XT is a discrete GPU with its own SELinux/device profile that has not been tested. Re-verify this fallback ladder from scratch on that hardware before assuming any of these specific flags carry over.

**This follow-up now also covers the Task 2 real-inference GPU-crash finding**, not just the passthrough/override flags: on the production RX 9070 XT VM, re-run the full smoke test (Task 1) AND a real `/synthesize` call (Task 2) end-to-end before assuming audio output works there — do not assume the MIOpen/AOTriton workspace issue found on this `gfx1103` iGPU is specific to this hardware without confirming the production `gfx1201` dGPU doesn't hit the same or a related gap.
