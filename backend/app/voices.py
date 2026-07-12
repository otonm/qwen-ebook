"""CustomVoice preset roster for the wizard's voice picker (WIZ-03).

Confirmed 2026-07-12 by calling tts_service.model.get_supported_speakers()
inside the live qwen-ebook-tts container on the production RX 9070 XT VM
(resolves the placeholder previously shipped here — see git history).
DEFAULT_SPEAKER server-side is "aiden".

# ponytail: gender/style in each label is a best-effort read of the speaker
# name, not vendor metadata (Qwen ships no per-speaker description) — if a
# label is wrong, the wizard's play/pause preview (WIZ-04) is the actual
# source of truth; re-label from listening, don't guess harder here.
"""

from __future__ import annotations

PRESET_VOICES: list[dict] = [
    {
        "name": "",
        "label": "Default narrator (auto-selected)",
        "keywords": (),
    },
    {
        # Checked before the generic male presets below: an "elderly male
        # grandfather" description contains both "elderly" and "male", and
        # this more specific match should win over the generic ones.
        "name": "uncle_fu",
        "label": "Uncle Fu (male, older/character)",
        "keywords": ("old man", "elderly", "grandfather", "uncle", "gruff"),
    },
    {
        "name": "aiden",
        "label": "Aiden (male)",
        "keywords": ("male", "man", "boy", "he ", "his "),
    },
    {
        "name": "dylan",
        "label": "Dylan (male)",
        "keywords": ("male", "man", "boy"),
    },
    {
        "name": "eric",
        "label": "Eric (male)",
        "keywords": ("male", "man"),
    },
    {
        "name": "ryan",
        "label": "Ryan (male)",
        "keywords": ("male", "young man", "boy"),
    },
    {
        "name": "serena",
        "label": "Serena (female)",
        "keywords": ("female", "woman", "girl", "she ", "her "),
    },
    {
        "name": "vivian",
        "label": "Vivian (female)",
        "keywords": ("female", "woman"),
    },
    {
        "name": "sohee",
        "label": "Sohee (female)",
        "keywords": ("female", "young woman", "girl"),
    },
    {
        "name": "ono_anna",
        "label": "Ono Anna (female)",
        "keywords": ("female", "woman"),
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
