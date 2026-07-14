"""LLM cast/segment analysis client.

Mirrors tts_client.py's mock/real backend switch (LLM_BACKEND, not
TTS_BACKEND): with LLM_BACKEND=mock, returns canned deterministic cast +
segments and makes no network call at all.

Real wiring (CAST-01/CAST-03) talks to OpenRouter's OpenAI-compatible
chat-completions endpoint via `httpx` (already a project dependency — no
provider-specific SDK needed, and OpenRouter itself is a routing layer
in front of many providers/models, not a single vendor SDK). System
prompt and book text are kept in separate message roles (RESEARCH.md
Security Domain / T-02-07) — book text is never concatenated into the
system message, which is the app's mitigation for prompt injection via
untrusted book text. The response is requested as strict JSON-schema
structured output (`response_format: json_schema`) and validated via
`CastAnalysisResult.model_validate_json()` — the model's declared JSON
schema IS `CastAnalysisResult.model_json_schema()`, so there is no
separate hand-maintained schema to drift out of sync.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.schemas import CastAnalysisResult, CharacterSuggestion, SegmentSuggestion
from app.voices import DEFAULT_PRESET, PRESET_VOICES, preset_description

_OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


def _build_preset_roster_block() -> str:
    """Renders the fixed presets (id + description) from voices.py so the
    prompt and PRESET_VOICES can't drift apart (PRESET-REWORK)."""
    lines = [f'- "{voice["name"]}": {voice["description"]}' for voice in PRESET_VOICES]
    return "\n".join(lines)


# CAST-01/CAST-03: instructs Grok to (a) detect narrator + speaking cast
# with inferred traits, cast each from the fixed presets, and adapt the
# picked preset's description to the character, (b) split the text into a
# COMPLETE ordered script of voice-tagged segments with delivery
# instructions, and (c) reconcile confident cross-chunk character matches
# (D-08) when continuity context is supplied. Wording is intentionally
# treated as iterative, not a fixed spec — see 02-03-PLAN.md "Prompt-quality
# validation" for the required real-key manual UAT pass.
#
# content-loss fix (debug/llm-analysis-content-loss.md): real-key testing
# showed the model was silently dropping dialogue tags/action beats (e.g.
# "she said, her voice calm but firm") whenever it used that narration to
# derive a dialogue segment's voice_instructions — it treated "extract the
# delivery cue" as license to discard the sentence instead of ALSO keeping
# it as its own Narrator segment. Step 2 below is now explicit that 100% of
# the input must survive into segments, and that deriving a delivery cue
# from narration text does not exempt that text from also appearing.
CAST_ANALYSIS_SYSTEM_PROMPT = f"""You are converting narrative text into a complete script for \
multi-voice audio narration. The single most important rule: every word of the input text must \
survive into `segments` — you are re-typesetting the text into a script, not summarizing, \
adapting, or condensing it.

1. Identify the cast: the narrator plus every distinct speaking character
   in the text. For EACH character (including the narrator), pick the
   single closest-matching voice preset from this fixed list of 5 personas
   and set `voice_preset` to its id:

{_build_preset_roster_block()}

   Then ADAPT that preset's description to this specific character's
   inferred traits from the text — age, gender, vocal tone/register, pace,
   accent, and emotional demeanor (e.g. shy vs. playful, teenager vs.
   mid-20s) — and put the adapted result in `description`. Do NOT include
   the character's occupation, role in the plot, relationships to other
   characters, backstory, or any other story detail that has no bearing on
   how they sound — a costume designer's brief, not a character bio.

   Narrator handling: assign the narrator `voice_preset="{DEFAULT_PRESET}"`
   (the default narrator persona) UNLESS the narration is clearly a
   specific character's first- or third-person voice, in which case pick
   and adapt the matching preset instead. Mark the narrator with
   `is_narrator=true`.

2. Split the text into an ordered list of `segments` covering the ENTIRE
   input, read sequentially front to back with nothing skipped. Each
   segment is a contiguous span of narration, or a single character's
   uninterrupted dialogue — never mix two speakers into one segment. Tag
   each segment with the speaking `character_name` (must match a name in
   your cast list).

   COMPLETENESS IS MANDATORY: every sentence, clause, dialogue tag (e.g.
   "she said", "he shouted"), and action beat (e.g. "leaning against the
   doorway") in the source must appear, verbatim, in exactly one segment.
   Formatting/whitespace may be normalized (collapse repeated blank lines,
   trim stray spaces), but words and content may never be removed,
   paraphrased, or summarized. Concatenating every segment's `text` in
   order must reproduce the full input.

   This completeness rule applies ONLY to the text under "=== TEXT TO
   CONVERT ===" (or the whole user message when that marker is absent). If
   a "Continuity context" block appears first, it is reference material
   already persisted from earlier in the book — never re-emit it, or any
   part of it, as a new segment. Producing a segment for content that only
   appears in the continuity block, and not in the text to convert, is
   exactly as wrong as dropping content.

   CRITICAL — dialogue tags and action beats do NOT disappear into
   voice_instructions: when the narration around a quote (e.g. "she said,
   her voice calm but firm") tells you how the line is delivered, that
   sentence still belongs in the output as its own Narrator segment,
   positioned immediately before or after the quote exactly as in the
   source. Using it to inform that character's `voice_instructions` never
   excuses dropping it from the text.

   `voice_instructions` contract: a short spoken-delivery direction for a
   voice actor — tone, pace, volume, emotional inflection, and how it
   shifts through the line (e.g. "whispers", "in a happy tone, getting
   more excited", "scared, voice trembling", "flat and weary", "growing
   angrier with each word"). Never restate what is happening in the scene,
   describe physical actions/gestures, or summarize plot/story content —
   delivery guidance only, never a scene description.
   - Dialogue segments: infer this from context — who's speaking, to
     whom, and the surrounding narration's emotional cues.
   - Narration segments: leave as an empty string "" by default; only set
     it when that narration's own tone is distinctly charged (e.g.
     "tense", "melancholy", "urgent") — most narration segments should
     still be "".

3. If you are given a `running_cast` (already-detected characters from
   earlier in this same book) and `recent_segments` (the most recently
   resolved segments) as continuity context: treat them as ground truth.
   When the new text confidently refers to one of those existing
   characters (e.g. "the old man" matching an existing "Marcus"), reuse
   that exact existing `character_name` instead of inventing a new,
   duplicate character entry. Only add a new character when you are not
   confident it is a repeat of one already listed.
"""

# content-loss fix: low temperature keeps segmentation close to a
# deterministic "re-typeset the input" task rather than letting sampling
# variance invite paraphrasing/summarization of narration. Module-level
# constant (not a Settings/env knob) since there is no comparable
# per-deployment LLM-call parameter in config.py to follow, and nothing so
# far needs it tunable per environment.
_ANALYSIS_TEMPERATURE = 0.2

_MOCK_NARRATOR = CharacterSuggestion(
    name="Narrator",
    voice_preset=DEFAULT_PRESET,
    description=preset_description(DEFAULT_PRESET),
    is_narrator=True,
)
_MOCK_CHARACTER = CharacterSuggestion(
    name="Alex",
    voice_preset="playful_student",
    description="A determined supporting character who speaks with quiet confidence.",
)
_NARRATOR_INSTRUCTIONS = ""
_CHARACTER_INSTRUCTIONS = "speaks with quiet, determined confidence"


def _mock_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    return paragraphs or [text.strip()]


def _mock_analyze(text: str) -> CastAnalysisResult:
    # Canned deterministic output: a narrator + one named character, with
    # segments derived from every paragraph (mock backend, no real cast
    # detection happens here). Must cover 100% of the input like the real
    # backend now does (content-loss fix round 2) — analysis_worker's
    # coverage-retry gate would otherwise fail a mock-mode project with more
    # than a few paragraphs, since mock's output is deterministic and a
    # retry would never improve it.
    paragraphs = _mock_paragraphs(text)
    segments = [
        SegmentSuggestion(
            order=index,
            character_name=_MOCK_NARRATOR.name if index % 2 == 0 else _MOCK_CHARACTER.name,
            text=paragraph,
            voice_instructions=(
                _NARRATOR_INSTRUCTIONS if index % 2 == 0 else _CHARACTER_INSTRUCTIONS
            ),
        )
        for index, paragraph in enumerate(paragraphs)
    ]
    return CastAnalysisResult(characters=[_MOCK_NARRATOR, _MOCK_CHARACTER], segments=segments)


def _build_continuity_block(
    running_cast: list[CharacterSuggestion] | None,
    recent_segments: list[SegmentSuggestion] | None,
) -> str:
    """Render D-07's continuity context (running cast + last-20 resolved
    segments) as plain text, prepended to the book text inside the SAME
    user() message — never the system message.

    content-loss fix round 3 (debug/llm-analysis-content-loss.md):
    real-key multi-chunk testing showed the model re-emitting this
    continuity block's own content as brand-new segments on the following
    chunk call — round 1's "100% of the input must survive into segments"
    instruction didn't distinguish "the new text to convert" from "already-
    resolved context shown for reference" once both landed in the same
    user message, so each chunk started duplicating the last chunk's tail.
    The explicit non-reproduction instruction + "=== TEXT TO CONVERT ==="
    marker (matched by the system prompt's completeness-rule scoping) fixes
    that ambiguity."""
    if not running_cast and not recent_segments:
        return ""

    lines = [
        "Continuity context from earlier in this same book — reference "
        "only. Do NOT create segments for anything in this block; it is "
        "already persisted and must not appear again in your output."
    ]
    if running_cast:
        lines.append("Already-detected cast (reuse these names for the same character):")
        lines.extend(f"- {c.name}: {c.description}" for c in running_cast)
    if recent_segments:
        lines.append("Most recently resolved segments (narrative continuity):")
        lines.extend(f"[{s.character_name}] {s.text}" for s in recent_segments)
    lines.append("=== TEXT TO CONVERT ===\n")
    return "\n".join(lines)


async def _real_analyze(
    text: str,
    running_cast: list[CharacterSuggestion] | None,
    recent_segments: list[SegmentSuggestion] | None,
) -> CastAnalysisResult:
    continuity = _build_continuity_block(running_cast, recent_segments)
    payload = {
        "model": settings.OPENROUTER_MODEL,
        "temperature": _ANALYSIS_TEMPERATURE,
        "messages": [
            {"role": "system", "content": CAST_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"{continuity}{text}"},
        ],
        # Strict JSON-schema structured output — the schema IS
        # CastAnalysisResult's own, so response shape can't drift from the
        # Pydantic contract used for persistence/API responses elsewhere.
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "CastAnalysisResult",
                "strict": True,
                "schema": CastAnalysisResult.model_json_schema(),
            },
        },
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)
    ) as client:
        response = await client.post(
            _OPENROUTER_CHAT_COMPLETIONS_URL,
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            json=payload,
        )
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    return CastAnalysisResult.model_validate_json(content)


async def analyze(
    text: str,
    running_cast: list[CharacterSuggestion] | None = None,
    recent_segments: list[SegmentSuggestion] | None = None,
) -> CastAnalysisResult:
    """Detect the cast + segments for `text`.

    `running_cast`/`recent_segments` carry cross-chunk reconciliation
    context (D-07/D-08), used only on the non-mock path's multi-chunk
    calls.
    """
    if settings.LLM_BACKEND == "mock":
        return _mock_analyze(text)

    return await _real_analyze(text, running_cast, recent_segments)
