"""LLM cast/segment analysis client.

Mirrors tts_client.py's mock/real backend switch (LLM_BACKEND, not
TTS_BACKEND): with LLM_BACKEND=mock, returns canned deterministic cast +
segments and never touches xai_sdk at all — the real import only happens
lazily inside the non-mock branch below, so `import app.analysis_client`
alone never pulls in xai_sdk (DEPL-01-style isolation, mirrored from
tts_client's GPU/CPU boundary).

Real Grok wiring (system/user role separation per RESEARCH.md Security
Domain, `chat.parse(CastAnalysisResult)`) lands in Plan 03 — this plan only
proves the mock path end-to-end.
"""

from __future__ import annotations

from app.config import settings
from app.schemas import CastAnalysisResult, CharacterSuggestion, SegmentSuggestion

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


async def analyze(
    text: str,
    running_cast: list[CharacterSuggestion] | None = None,
    recent_segments: list[SegmentSuggestion] | None = None,
) -> CastAnalysisResult:
    """Detect the cast + segments for `text`.

    `running_cast`/`recent_segments` carry cross-chunk reconciliation
    context (D-07/D-08) — accepted here for interface stability but unused
    until Plan 03's multi-chunk path.
    """
    if settings.LLM_BACKEND == "mock":
        return _mock_analyze(text)

    # Real Grok wiring lands in Plan 03. The import is intentionally lazy
    # and only reached on this non-mock branch, so LLM_BACKEND=mock never
    # imports xai_sdk.
    import xai_sdk  # noqa: F401

    raise NotImplementedError("Real Grok analysis wiring lands in Plan 03")
