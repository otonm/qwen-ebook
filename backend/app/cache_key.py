"""Content-hash cache key for per-segment TTS output (GEN-02).

A single SHA-256 hexdigest over every field that affects the resulting
audio: the resolved speaker preset, this segment's voice instructions, its
text, and a hardcoded TTS model-version constant — the tuple GEN-02
specifies as "(character, voice instructions, text, voice/model version)".
Recompute this live before every generate-check (Pitfall 3) rather than
trusting a stored value as ground truth — an out-of-band character preset
change, a text edit, or a future model-version bump are all naturally
cache-busting with no extra invalidation code path.
"""

from __future__ import annotations

import hashlib

# Bump this string manually if the TTS model or backend implementation
# changes in a way that could change output audio for the same inputs.
# Only one model (Qwen3-TTS-12Hz-1.7B-CustomVoice) is in scope for v1, so
# this is a constant today, not a live "model version" lookup.
TTS_MODEL_VERSION = "qwen3-tts-12hz-1.7b-customvoice-v1"

# ASCII unit separator — avoids a crafted voice-instructions string
# containing a delimiter character (e.g. "|") silently colliding two
# different (character, text) pairs onto the same hash.
_FIELD_SEPARATOR = "\x1f"


def compute_cache_key(resolved_speaker: str, voice_instructions: str, text: str) -> str:
    """`resolved_speaker` must be the same value passed to
    tts_client.synthesize() (character.voice_preset, or best_guess_preset()
    fallback — see regenerate_segment's resolution logic) so a character's
    preset change is naturally reflected without extra bookkeeping."""
    payload = _FIELD_SEPARATOR.join(
        [resolved_speaker, voice_instructions, text, TTS_MODEL_VERSION]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    same_a = compute_cache_key("preset-a", "warm tone", "Hello there.")
    same_b = compute_cache_key("preset-a", "warm tone", "Hello there.")
    different = compute_cache_key("preset-a", "warm tone", "Goodbye there.")
    different_model = compute_cache_key("preset-a", "warm tone", "Hello there.", model_id="0.6b")
    assert same_a == same_b, "identical inputs must produce identical digests"
    assert same_a != different, "different text must produce different digests"
    assert same_a != different_model, "different model_id must produce different digests"
    print("cache_key self-check passed")
