"""CPU-only unit test for the D-01/D-02 immediate-cancel event/criteria
contract (tts_service/model.py's _cancel_event + _CancelStoppingCriteria).

tts_service.model cannot be imported on a CPU-only host: it triggers a real
model load (torch/transformers/qwen_tts) at import time, and none of those
packages are installed outside the GPU container's own isolated environment
(tts_service/requirements.txt + Containerfile.tts) — the backend's
pyproject.toml deliberately does not depend on them either. So this test
does not import tts_service.model at all; it reconstructs the exact
threading.Event + StoppingCriteria __call__ contract in isolation.
# ponytail: this is a stub of the real _CancelStoppingCriteria class, not
# an import of it — the actual class (and whether it truly aborts a live
# ROCm decode loop) is proven by spike_cancel_hw.py running inside the GPU
# container, not by this test.
"""

import threading


class _StubCancelStoppingCriteria:
    """Mirrors tts_service.model._CancelStoppingCriteria.__call__ exactly:
    returns whether the given threading.Event is set."""

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event

    def __call__(self, input_ids=None, scores=None, **kwargs) -> bool:
        return self._cancel_event.is_set()


def test_criteria_returns_true_after_request_cancel_then_false_after_clear():
    cancel_event = threading.Event()
    criteria = _StubCancelStoppingCriteria(cancel_event)

    assert criteria(None, None) is False

    cancel_event.set()  # mirrors request_cancel()
    assert criteria(None, None) is True

    cancel_event.clear()  # mirrors synthesize_wav's clear-at-start (T-04-01)
    assert criteria(None, None) is False
