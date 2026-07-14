"""Shared Pydantic contract: the Grok structured-output response shape,
reused verbatim (via .model_dump()) for SQLModel persistence and again as
the FastAPI GET /projects/{id} response shape (RESEARCH.md Code Examples —
one schema, three consumers)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# PRESET-REWORK: the 6 fixed preset ids from voices.py, duplicated here as a
# Literal (not imported) so this schema stays a plain, dependency-free
# contract usable for OpenRouter's json_schema — analysis_client.py is the
# module responsible for keeping the prompt's preset list in sync with
# voices.PRESET_VOICES.
VoicePresetId = Literal[
    "narrator_sultry_woman",
    "middle_sultry_woman",
    "playful_student",
    "bright_young_guy",
    "reassuring_young_man",
    "gruff_older_man",
]


class CharacterSuggestion(BaseModel):
    name: str
    voice_preset: VoicePresetId = Field(
        description="The closest-matching fixed voice preset for this character."
    )
    description: str = Field(
        description=(
            "Voice-relevant traits only: age, gender, vocal tone/register, pace, "
            "accent, emotional demeanor. No occupation, plot role, relationships, "
            "or other story/background detail. This is the picked preset's "
            "description ADAPTED to this specific character."
        )
    )
    is_narrator: bool = False


class SegmentSuggestion(BaseModel):
    order: int
    character_name: str  # resolved to Character.id after persistence
    text: str
    voice_instructions: str = Field(
        description=(
            "A short spoken-delivery direction only (tone, pace, volume, "
            "emotional inflection), e.g. 'whispers' or 'in a happy tone, "
            "getting more excited'. Never a scene or action description, and "
            "never a substitute for including that scene/action text in a "
            "segment's own `text`. Dialogue lines: infer from context. "
            "Narration: empty string \"\" by default, unless the narration's "
            "own tone is distinctly charged (e.g. 'tense', 'melancholy')."
        )
    )


class CastAnalysisResult(BaseModel):
    characters: list[CharacterSuggestion]
    segments: list[SegmentSuggestion]
