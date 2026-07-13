"""Standalone D-02 hardware behavioral spike — proves whether request_cancel()
actually aborts a live ROCm decode loop promptly, not just whether the Python
call chain exists. ARCHITECTURE.md "Capability 1" already confirmed the
StoppingCriteria hook is reachable at HIGH confidence by reading the
qwen-tts wheel; this script is the MEDIUM-confidence hardware proof that
closes the gap (D-01/D-02 — the highest-risk unknown in this milestone).

Mirrors smoke_gpu.py's standalone-script convention: run directly inside the
GPU container against real weights, exit 0/non-0, print everything a human
needs to eyeball the blocking checkpoint result without re-running anything.

Exit code 0  -> cancel-to-stop time is under BOTH the hard ceiling (2000 ms)
                AND 25% of the uncancelled baseline synth time.
Exit code != 0 -> either threshold failed, or the criteria didn't actually
                  interrupt generation at all; see stderr for which.
"""

import sys
import threading
import time

# A text near tts_service.model.MAX_TEXT_LENGTH so decode genuinely takes
# multiple seconds — long enough that a mid-run cancel lands mid-loop
# rather than racing a call that's already finished.
_SENTENCE = "The quick brown fox jumps over the lazy dog near the riverbank at dusk. "
LONG_TEXT = (_SENTENCE * 60)[:3900]

HARD_CEILING_MS = 2000.0
BASELINE_FRACTION_CEILING = 0.25

# Fixed floor for the pre-cancel sleep, and a fraction of the *measured*
# baseline used above that floor. A pure fixed constant risked either firing
# before decode starts (if hardware is slow) or after the whole call already
# finished (if hardware is fast) — since the baseline run below measures the
# real duration first, deriving the delay from it lands mid-decode
# regardless of actual hardware speed.
MIN_CANCEL_DELAY_SECONDS = 0.1
CANCEL_DELAY_FRACTION_OF_BASELINE = 0.4


def main() -> int:
    try:
        from tts_service import model
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        print(f"FAIL: could not import tts_service.model: {exc}", file=sys.stderr)
        return 1

    print(f"LONG_TEXT length: {len(LONG_TEXT)} chars")

    # --- Warmup: one throwaway synth of the SAME LONG_TEXT, excluded from
    # all timing. MIOpen (ROCm's kernel library) does exhaustive kernel
    # autotuning the FIRST time it sees a given op/shape on this process (no
    # cached kernel db entry yet) — confirmed live on this hardware: an
    # unwarmed first call logged repeated "MIOpen(HIP): Warning
    # [IsEnoughWorkspace] ... GemmFwdRest" autotune lines with GROWING
    # workspace sizes tied to the growing decode-step sequence length, and
    # took ~15 minutes for 3900 chars vs. a normal steady-state decode. A
    # short warmup text only tunes shapes up to ITS shorter length, leaving
    # the timed baseline to still hit fresh (slow) shapes past that point —
    # so the warmup text must be identical to LONG_TEXT to guarantee full
    # shape coverage before anything is timed.
    print("Warming up model (first-call ROCm/MIOpen kernel autotune, excluded from timing)...")
    warmup_start = time.monotonic()
    model.synthesize_wav(LONG_TEXT)
    warmup_elapsed_ms = (time.monotonic() - warmup_start) * 1000
    print(f"Warmup synth time (excluded from measurements): {warmup_elapsed_ms:.1f} ms")

    # --- Baseline: full synth, no cancel ---
    print("Running baseline (uncancelled) synth...")
    baseline_start = time.monotonic()
    model.synthesize_wav(LONG_TEXT)
    baseline_elapsed_ms = (time.monotonic() - baseline_start) * 1000
    print(f"BASELINE uncancelled synth time: {baseline_elapsed_ms:.1f} ms")

    # --- Cancel run: start synth in a background thread, cancel mid-decode ---
    result: dict[str, object] = {}

    def _run_synth() -> None:
        try:
            model.synthesize_wav(LONG_TEXT)
            result["outcome"] = "completed_without_cancellation"
        except model.GenerationCancelled:
            result["outcome"] = "cancelled"
        except Exception as exc:  # pragma: no cover - surfaced via stderr below
            result["outcome"] = "error"
            result["error"] = str(exc)

    cancel_delay_seconds = max(
        MIN_CANCEL_DELAY_SECONDS,
        (baseline_elapsed_ms / 1000) * CANCEL_DELAY_FRACTION_OF_BASELINE,
    )
    print(
        f"Starting cancelled run, will fire request_cancel() after "
        f"{cancel_delay_seconds:.2f}s..."
    )
    thread = threading.Thread(target=_run_synth)
    thread.start()
    time.sleep(cancel_delay_seconds)

    cancel_call_time = time.monotonic()
    model.request_cancel()
    # Generous safety join timeout — if StoppingCriteria genuinely doesn't
    # work, we still want the script to return (non-zero) rather than hang
    # forever waiting on a decode loop that will never check the event.
    thread.join(timeout=max(HARD_CEILING_MS, baseline_elapsed_ms) / 1000 * 3)
    cancel_to_stop_ms = (time.monotonic() - cancel_call_time) * 1000

    if thread.is_alive():
        print(
            "FAIL: synthesize_wav thread did not return within the safety join "
            "timeout after request_cancel() — StoppingCriteria did not abort "
            "the decode loop.",
            file=sys.stderr,
        )
        return 1

    outcome = result.get("outcome")
    print(f"CANCEL-TO-STOP time: {cancel_to_stop_ms:.1f} ms (outcome: {outcome})")

    if outcome != "cancelled":
        print(
            f"FAIL: expected GenerationCancelled, got outcome={outcome!r} "
            f"({result.get('error', '')}) — the stopping criteria did not "
            "actually interrupt generation.",
            file=sys.stderr,
        )
        return 1

    if cancel_to_stop_ms >= HARD_CEILING_MS:
        print(
            f"FAIL: cancel-to-stop time {cancel_to_stop_ms:.1f} ms exceeds the "
            f"{HARD_CEILING_MS:.0f} ms hard ceiling.",
            file=sys.stderr,
        )
        return 1

    baseline_fraction = cancel_to_stop_ms / baseline_elapsed_ms if baseline_elapsed_ms else 1.0
    print(f"cancel-to-stop is {baseline_fraction * 100:.1f}% of the uncancelled baseline")
    if baseline_fraction >= BASELINE_FRACTION_CEILING:
        print(
            f"FAIL: cancel-to-stop time is {baseline_fraction * 100:.1f}% of "
            f"the baseline, at or above the {BASELINE_FRACTION_CEILING * 100:.0f}% ceiling.",
            file=sys.stderr,
        )
        return 1

    print(
        "PASS: request_cancel() aborted the live decode loop promptly "
        f"({cancel_to_stop_ms:.1f} ms, {baseline_fraction * 100:.1f}% of baseline)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
