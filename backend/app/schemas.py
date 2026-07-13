"""Shared Pydantic contract: the Grok structured-output response shape,
reused verbatim (via .model_dump()) for SQLModel persistence and again as
the FastAPI GET /projects/{id} response shape (RESEARCH.md Code Examples —
one schema, three consumers)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterSuggestion(BaseModel):
    name: str
    description: str = Field(
        description=(
            "Voice-relevant traits only: age, gender, vocal tone/register, pace, "
            "accent, emotional demeanor. No occupation, plot role, relationships, "
            "or other story/background detail."
        )
    )
    is_narrator: bool = False


class SegmentSuggestion(BaseModel):
    order: int
    character_name: str  # resolved to Character.id after persistence
    text: str
    voice_instructions: str = Field(
        description=(
            "Spoken-delivery direction only (tone, pace, volume, emotional "
            "inflection), e.g. 'narrates in a soothing voice'. Never a scene "
            "or action description."
        )
    )


class CastAnalysisResult(BaseModel):
    characters: list[CharacterSuggestion]
    segments: list[SegmentSuggestion]
