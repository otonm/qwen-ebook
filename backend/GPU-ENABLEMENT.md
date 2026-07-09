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
- Host remained fully stable throughout every experiment in this log (no `amdgpu`/`kfd` kernel resets, no page faults, no desktop hang — confirmed via `journalctl -k` and `uptime` after each attempt)

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

## Re-verification Follow-up (D-09)

This entire investigation was performed on the local Radeon 780M (`gfx1103`) dev host. The production deployment target is an AMD RX 9070 XT (`gfx1201`, RDNA4, officially supported by ROCm 7.2+). None of the workarounds here (override, `label=disable`) are expected to be necessary on the production VM once it exists — `gfx1201` is officially supported and the RX 9070 XT is a discrete GPU with its own SELinux/device profile that has not been tested. Re-verify this fallback ladder from scratch on that hardware before assuming any of these specific flags carry over.
