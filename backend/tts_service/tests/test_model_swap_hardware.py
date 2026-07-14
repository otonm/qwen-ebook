"""Real-hardware swap-cycle test for tts_service.model.ensure_loaded.

Closes STATE.md's Phase 5 VRAM-fragmentation exit criterion: runs >=10
alternating swaps between the two Qwen3-TTS checkpoints and asserts free
VRAM is stable across cycles (RESEARCH.md Pitfall 2 measured zero drift
over 12 cycles on the production RX 9070 XT — this test re-proves that in
the actual ensure_loaded() code path, not just the standalone research
script, per PITFALLS.md's "Looks Done But Isn't" checklist item).

Skipped entirely when no CUDA/ROCm device is visible (dev machines without
the GPU container) — this is a hardware verification test, not a unit test
gated by TTS_BACKEND=mock.
"""

import pytest

torch = pytest.importorskip("torch")

from tts_service import model  # noqa: E402  (import after importorskip guard)

pytestmark = pytest.mark.skipif(
    not torch.cuda.is_available(), reason="requires a real CUDA/ROCm GPU device"
)

SWAP_CYCLES = 10
# RESEARCH.md Pitfall 2 measured byte-identical free VRAM across 12 real
# cycles (zero drift) — 64MB is a generous tolerance above that, not a
# loosened bar.
FREE_VRAM_TOLERANCE_MB = 64


def test_swap_cycle_vram_is_stable_and_single_model_resident():
    model_ids = ["1.7b", "0.6b"]
    # Free VRAM after loading a given model_id is compared against EARLIER
    # readings for that SAME model_id, not across model_ids — the two
    # checkpoints have different resident footprints by design (RESEARCH.md
    # Pitfall 2: ~4.3GB vs ~2.3GB), so a stability/drift check must hold
    # model size constant and only vary "how many swaps happened before this
    # reading".
    free_after_load_mb: dict[str, list[float]] = {"1.7b": [], "0.6b": []}

    # Prime residency so the first swap below actually exercises the
    # del+gc.collect+empty_cache unload branch, not just a first-ever load.
    model.ensure_loaded(model_ids[0])

    for i in range(SWAP_CYCLES):
        target = model_ids[(i + 1) % 2]
        model.ensure_loaded(target)

        assert model._loaded_model_id == target
        supported = model.get_supported_speakers()
        assert supported, f"get_supported_speakers() empty after swap to {target!r}"

        free_bytes, _total_bytes = torch.cuda.mem_get_info()
        free_after_load_mb[target].append(free_bytes / 1024**2)

    for target, readings in free_after_load_mb.items():
        if not readings:
            continue
        baseline = readings[0]
        for cycle, free_mb in enumerate(readings):
            drift = abs(free_mb - baseline)
            assert drift <= FREE_VRAM_TOLERANCE_MB, (
                f"{target!r} cycle {cycle}: free VRAM drifted {drift:.1f} MB from "
                f"this model's own baseline {baseline:.1f} MB (reading: {free_mb:.1f} "
                f"MB) — exceeds {FREE_VRAM_TOLERANCE_MB} MB tolerance"
            )


def test_ensure_loaded_rejects_unknown_model_id():
    resident_before = model._loaded_model_id
    with pytest.raises(ValueError):
        model.ensure_loaded("bogus")
    assert model._loaded_model_id == resident_before


def test_ensure_loaded_reapplies_cancel_patch_after_swap():
    model.ensure_loaded("0.6b")
    original_generate = model.model.model.talker.generate
    model.ensure_loaded("1.7b")
    # A fresh from_pretrained gets its own talker object — the patched
    # generate on the new instance must not be the same bound method as the
    # previous instance's patched generate (RESEARCH.md: "the patch does not
    # survive a fresh from_pretrained").
    assert model.model.model.talker.generate is not original_generate
    assert model.model.model.talker.generate.__name__ == "_talker_generate_with_cancel"
