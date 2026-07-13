"""Fixed voice-preset roster for the wizard's voice picker and the analysis
LLM's casting pick (PRESET-REWORK).

6 curated personas, each with a fleshed-out steering `description` the
analysis LLM adapts per character (see analysis_client.py's system prompt,
built from `preset_description()` so prompt and roster can't drift) and a
`speaker` — the underlying Qwen CustomVoice speaker name that actually drives
timbre, confirmed 2026-07-12 by calling
tts_service.model.get_supported_speakers() inside the live qwen-ebook-tts
container on the production RX 9070 XT VM. DEFAULT_SPEAKER server-side is
"aiden"; DEFAULT_PRESET here (narrator_sultry_woman) is the narrator
fallback and the "nothing selected" fallback.

# ponytail: speaker->persona mapping below is best-effort timbre matching,
# not vendor metadata (Qwen ships no per-speaker description) — the wizard's
# play/pause preview is the actual source of truth, and `instruct` steering
# (commit f51f748) is the real lever. Re-map from listening, don't guess
# harder here.
"""

from __future__ import annotations

DEFAULT_PRESET = "narrator_sultry_woman"

PRESET_VOICES: list[dict] = [
    {
        "name": "narrator_sultry_woman",
        "label": "Narrator (young sultry woman)",
        "keywords": ("narrator", "sultry", "young woman"),
        "speaker": "serena",
        "description": (
            "A young woman with a deep, sultry voice. Warm lower register, "
            "unhurried pace, and a calm, self-assured demeanor — the default "
            "narrator voice when no other persona fits better."
        ),
    },
    {
        "name": "middle_sultry_woman",
        "label": "Middle-aged sultry woman",
        "keywords": ("middle-aged woman", "mature woman", "sultry"),
        "speaker": "vivian",
        "description": (
            "A middle-aged woman with a sultry voice. Slightly deeper and "
            "more grounded than a younger voice, measured pace, and a "
            "composed, worldly emotional demeanor."
        ),
    },
    {
        "name": "playful_student",
        "label": "Playful student (19)",
        "keywords": ("student", "teenager", "19-year-old", "playful", "young woman"),
        "speaker": "sohee",
        "description": (
            "A 19-year-old student with a youthful, playful, and bright "
            "tone. Quick, energetic pace and an upbeat, curious emotional "
            "demeanor."
        ),
    },
    {
        "name": "bright_young_guy",
        "label": "Bright young guy",
        "keywords": ("young guy", "young man", "bright", "positive"),
        "speaker": "ryan",
        "description": (
            "A young guy with a bright tone and a positive attitude. Brisk, "
            "lively pace and an enthusiastic, upbeat emotional demeanor."
        ),
    },
    {
        "name": "reassuring_young_man",
        "label": "Reassuring young man",
        "keywords": ("young man", "reassuring", "deep voice"),
        "speaker": "aiden",
        "description": (
            "A young man with a deep, reassuring voice. Steady, measured "
            "pace and a calm, trustworthy emotional demeanor."
        ),
    },
    {
        "name": "gruff_older_man",
        "label": "Gruff older man",
        "keywords": ("old man", "older man", "elderly", "gruff", "gravelly"),
        "speaker": "uncle_fu",
        "description": (
            "An older man with a gruff, weathered voice. Slower, deliberate "
            "pace and a grounded, world-worn emotional demeanor."
        ),
    },
]

_PRESET_BY_NAME: dict[str, dict] = {voice["name"]: voice for voice in PRESET_VOICES}
_DEFAULT_SPEAKER = _PRESET_BY_NAME[DEFAULT_PRESET]["speaker"]


def list_presets() -> list[dict]:
    """Preset list for the wizard's dropdown — name + label only."""
    return [{"name": voice["name"], "label": voice["label"]} for voice in PRESET_VOICES]


def preset_speaker(preset_id: str) -> str:
    """Resolve a preset id to the Qwen CustomVoice speaker name to pass to
    tts_client.synthesize(). Empty/unknown preset ids fall back to the
    DEFAULT_PRESET's speaker (the "auto-selected" sentinel, WIZ-03)."""
    voice = _PRESET_BY_NAME.get(preset_id)
    return voice["speaker"] if voice else _DEFAULT_SPEAKER


def preset_description(preset_id: str) -> str:
    """Return a preset's steering description (used to build the analysis
    prompt and as the wizard's editable default)."""
    voice = _PRESET_BY_NAME.get(preset_id)
    return voice["description"] if voice else _PRESET_BY_NAME[DEFAULT_PRESET]["description"]


def merge_instructions(base: str, delivery: str) -> str:
    """Combine a character's adapted base voice description with a
    segment's delivery instruction into one `instruct` string for TTS.
    Narration segments carry an empty delivery, so the merge yields just
    the base; a dialogue line yields base + delivery. Empty parts are
    stripped and skipped so no stray separators appear."""
    parts = [part.strip() for part in (base, delivery) if part and part.strip()]
    return ". ".join(parts)


def best_guess_preset(description: str) -> str | None:
    """D-16 best-guess pick: match simple keyword signals in `description`
    against each preset's tags, falling back to DEFAULT_PRESET when nothing
    matches. Returns None only if the roster is empty."""
    if not PRESET_VOICES:
        return None
    lowered = description.lower()
    for voice in PRESET_VOICES:
        if any(keyword in lowered for keyword in voice["keywords"]):
            return voice["name"]
    return DEFAULT_PRESET


if __name__ == "__main__":
    assert merge_instructions("base voice", "whispers") == "base voice. whispers"
    assert merge_instructions("base voice", "") == "base voice"
    assert merge_instructions("", "whispers") == "whispers"
    assert merge_instructions("", "") == ""
    assert preset_speaker("") == _DEFAULT_SPEAKER
    assert preset_speaker("not-a-real-preset") == _DEFAULT_SPEAKER
    assert preset_speaker(DEFAULT_PRESET) == _DEFAULT_SPEAKER
    assert len(PRESET_VOICES) == 6
    assert best_guess_preset("") == DEFAULT_PRESET
    print("voices self-check passed")
