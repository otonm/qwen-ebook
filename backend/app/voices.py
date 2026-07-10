"""CustomVoice preset roster for the wizard's voice picker (WIZ-03).

# ponytail: the real Qwen3-TTS-12Hz-1.7B-CustomVoice preset roster is only
# knowable by calling model.get_supported_speakers() inside the GPU
# container (tts_service/model.py) — this repo's dev/CI environment has no
# GPU access to enumerate it, and no prior Phase 1 log/doc recorded the
# actual names either (02-RESEARCH.md Open Question 2). Ship the single
# known default entry ("" -> whatever tts_service.model.DEFAULT_SPEAKER
# resolves to server-side, the same empty-string-means-container-default
# convention already used by TTS_DEFAULT_SPEAKER in config.py) as the known
# ceiling. Upgrade path: once this runs against the real GPU container, add
# a `/voices` passthrough on the TTS service exposing its own
# get_supported_speakers(), and populate PRESET_VOICES (with per-entry
# `keywords`) from that real list instead of this placeholder.
"""

from __future__ import annotations

PRESET_VOICES: list[dict] = [
    {
        "name": "",
        "label": "Default narrator (auto-selected)",
        "keywords": (),
    },
]


def list_presets() -> list[dict]:
    """Preset list for the wizard's dropdown — name + label only."""
    return [{"name": voice["name"], "label": voice["label"]} for voice in PRESET_VOICES]


def best_guess_preset(description: str) -> str | None:
    """D-16 best-guess pick: match simple keyword signals in `description`
    against each preset's tags, falling back to the first (narrator) preset
    when nothing matches. Returns None only if the roster is empty."""
    if not PRESET_VOICES:
        return None
    lowered = description.lower()
    for voice in PRESET_VOICES:
        if any(keyword in lowered for keyword in voice["keywords"]):
            return voice["name"]
    return PRESET_VOICES[0]["name"]
