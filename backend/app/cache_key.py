"""Content-hash cache key for per-segment TTS output (GEN-02).

A single SHA-256 hexdigest over every field that affects the resulting
audio: the resolved speaker preset, this segment's voice instructions, its
text, and the live per-project `model_id` (Project.tts_model) — the tuple
GEN-02 specifies as "(character, voice instructions, text, voice/model
version)". Model identity is now a live per-project value (Phase 5,
CFG-04), not a hardcoded constant — two otherwise-identical segments
generated under different models must never collide onto the same cache
key (Pitfall 4 / Pattern 2). Recompute this live before every
generate-check (Pitfall 3) rather than trusting a stored value as ground
truth — an out-of-band character preset change, a text edit, or a model
swap are all naturally cache-busting with no extra invalidation code path.
"""

from __future__ import annotations

import hashlib

# ASCII unit separator — avoids a crafted voice-instructions string
# containing a delimiter character (e.g. "|") silently colliding two
# different (character, text) pairs onto the same hash.
_FIELD_SEPARATOR = "\x1f"


def compute_cache_key(
    resolved_speaker: str, voice_instructions: str, text: str, model_id: str
) -> str:
    """`resolved_speaker` must be the same value passed to
    tts_client.synthesize() (character.voice_preset, or best_guess_preset()
    fallback — see regenerate_segment's resolution logic) so a character's
    preset change is naturally reflected without extra bookkeeping.
    `model_id` must be the resident project's Project.tts_model — this is
    what makes a model swap force-invalidate every previously-cached
    segment for free, since the payload now differs from any pre-swap key."""
    payload = _FIELD_SEPARATOR.join(
        [resolved_speaker, voice_instructions, text, model_id]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    same_a = compute_cache_key("preset-a", "warm tone", "Hello there.", "1.7b")
    same_b = compute_cache_key("preset-a", "warm tone", "Hello there.", "1.7b")
    different = compute_cache_key("preset-a", "warm tone", "Goodbye there.", "1.7b")
    different_model = compute_cache_key("preset-a", "warm tone", "Hello there.", model_id="0.6b")
    assert same_a == same_b, "identical inputs must produce identical digests"
    assert same_a != different, "different text must produce different digests"
    assert same_a != different_model, "different model_id must produce different digests"
    print("cache_key self-check passed")
