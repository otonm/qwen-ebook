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

_OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"

# CAST-01/CAST-03: instructs Grok to (a) detect narrator + speaking cast
# with inferred traits, (b) split the text into ordered voice-tagged
# segments, and (c) reconcile confident cross-chunk character matches
# (D-08) when continuity context is supplied. Wording is intentionally
# treated as iterative, not a fixed spec — see 02-03-PLAN.md "Prompt-
# quality validation" for the required real-key manual UAT pass.
CAST_ANALYSIS_SYSTEM_PROMPT = """You are preparing narrative text for multi-voice audio narration.

1. Identify the cast: the narrator plus every distinct speaking character
   in the text. For each character, infer age, gender, and personality
   traits from context (word choice, actions, how others address them,
   how they speak) and summarize them in a short `description`. Mark the
   narrator with `is_narrator=true`.

2. Split the text into an ordered list of `segments`. Each segment is a
   contiguous span of narration, or a single character's uninterrupted
   dialogue — never mix two speakers into one segment. Tag each segment
   with the speaking `character_name` (must match a name in your cast
   list) and a short `voice_instructions` phrase describing how it should
   be spoken (e.g. "narrates in a soothing voice", "gaining confidence",
   "shouting in panic").

3. If you are given a `running_cast` (already-detected characters from
   earlier in this same book) and `recent_segments` (the most recently
   resolved segments) as continuity context: treat them as ground truth.
   When the new text confidently refers to one of those existing
   characters (e.g. "the old man" matching an existing "Marcus"), reuse
   that exact existing `character_name` instead of inventing a new,
   duplicate character entry. Only add a new character when you are not
   confident it is a repeat of one already listed.
"""

_MOCK_NARRATOR = CharacterSuggestion(
    name="Narrator",
    description="A calm, steady narrator guiding the reader through the story.",
    is_narrator=True,
)
_MOCK_CHARACTER = CharacterSuggestion(
    name="Alex",
    description="A determined supporting character who speaks with quiet confidence.",
)
_NARRATOR_INSTRUCTIONS = "narrates in a calm, steady voice"
_CHARACTER_INSTRUCTIONS = "speaks with quiet, determined confidence"


def _mock_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    return paragraphs or [text.strip()]


def _mock_analyze(text: str) -> CastAnalysisResult:
    # Canned deterministic output: a narrator + one named character, with
    # 2-3 segments derived from the input's paragraphs (mock backend, no
    # real cast detection happens here).
    paragraphs = _mock_paragraphs(text)[:3]
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
    user() message — never the system message."""
    if not running_cast and not recent_segments:
        return ""

    lines = ["Continuity context from earlier in this same book:"]
    if running_cast:
        lines.append("Already-detected cast (reuse these names for the same character):")
        lines.extend(f"- {c.name}: {c.description}" for c in running_cast)
    if recent_segments:
        lines.append("Most recently resolved segments (narrative continuity):")
        lines.extend(f"[{s.character_name}] {s.text}" for s in recent_segments)
    lines.append("---\n")
    return "\n".join(lines)


async def _real_analyze(
    text: str,
    running_cast: list[CharacterSuggestion] | None,
    recent_segments: list[SegmentSuggestion] | None,
) -> CastAnalysisResult:
    continuity = _build_continuity_block(running_cast, recent_segments)
    payload = {
        "model": settings.OPENROUTER_MODEL,
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
