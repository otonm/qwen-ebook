"""Standalone GPU compute smoke test — run BEFORE any TTS model weights load.

RESEARCH.md Open Question 1 / Pitfall 2: this host's GPU (gfx1103, Radeon
780M) is not on ROCm's officially-supported architecture list. A card can
render a desktop over /dev/dri while still lacking working KFD compute
queues, and even once compute is detected, Ubuntu-based rocBLAS is
documented to sometimes omit gfx1103 Tensile GEMM kernels. This script
proves both things in isolation, with a fast, cheap check, so a bad GPU
state fails fast instead of hanging mid multi-GB model load.

Exit code 0  -> GPU is a usable compute agent, matmul succeeded on-device.
Exit code != 0 -> assertion failed; see stderr for which check failed.
"""

import sys


def main() -> int:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        print(f"FAIL: could not import torch: {exc}", file=sys.stderr)
        return 1

    print(f"torch version: {torch.__version__}")
    hip_version = getattr(torch.version, "hip", None)
    print(f"torch.version.hip: {hip_version}")
    cuda_version = getattr(torch.version, "cuda", None)
    print(f"torch.version.cuda: {cuda_version}")

    is_available = torch.cuda.is_available()
    print(f"cuda.is_available() = {is_available}")
    if not is_available:
        print(
            "FAIL: torch.cuda.is_available() is False — no compute device visible "
            "to PyTorch. Check /dev/kfd, /dev/dri passthrough and --group-add keep-groups.",
            file=sys.stderr,
        )
        return 1

    device_count = torch.cuda.device_count()
    print(f"cuda.device_count() = {device_count}")
    if device_count < 1:
        print("FAIL: device_count() < 1 despite is_available() True", file=sys.stderr)
        return 1

    device_name = torch.cuda.get_device_name(0)
    device_props = torch.cuda.get_device_properties(0)
    print(f"device 0 name: {device_name}")
    print(f"device 0 properties: {device_props}")

    # RESEARCH.md Open Question 1: confirm this is a COMPUTE agent, not just
    # a display-capable node. A successful get_device_properties() call plus
    # a real on-device matmul below is the practical proxy for "detected as
    # a compute agent" from inside a container without a rocminfo binary.
    gcn_arch = getattr(device_props, "gcnArchName", None)
    print(f"device 0 gcnArchName: {gcn_arch}")

    # Minimal on-device matmul — the real proof that compute queues work,
    # not just device enumeration. This is deliberately tiny/fast (RESEARCH.md
    # Pitfall 2: distinguish "device not found" from "rocBLAS/Tensile no
    # kernel found" — both surface differently and both must be caught here,
    # before any 1.7B-parameter model load is attempted).
    try:
        a = torch.randn(256, 256, device="cuda")
        b = torch.randn(256, 256, device="cuda")
        result = (a @ b).sum().item()
    except RuntimeError as exc:
        print(f"FAIL: on-device matmul raised RuntimeError: {exc}", file=sys.stderr)
        print(
            "This may be a rocBLAS/Tensile 'no kernel found' error (RESEARCH.md "
            "Pitfall 2 — gfx1103 Tensile GEMM kernel gap) rather than a device "
            "detection failure. See backend/GPU-ENABLEMENT.md for the fallback ladder.",
            file=sys.stderr,
        )
        return 1

    print(f"matmul(256x256 @ 256x256).sum() = {result}")

    if result != result:  # NaN check without importing math
        print("FAIL: matmul result is NaN — silent GPU corruption?", file=sys.stderr)
        return 1

    # Confirm the result tensor actually lived on the GPU (not a silent CPU
    # fallback that would still "work" but defeat the point of this check).
    if a.device.type != "cuda":
        print(f"FAIL: tensor device was '{a.device.type}', not 'cuda' — silent CPU fallback", file=sys.stderr)
        return 1

    print("PASS: GPU compute agent detected and on-device matmul succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
