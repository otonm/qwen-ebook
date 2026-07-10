"""SQLModel persistence tables: Project, Character, Segment.

D-02: no Phase 3 fields here (generation status, content-hash cache key,
audio cache path) — those belong to the later full-generation-pipeline
phase, not this analysis-and-review slice.
"""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    filename: str
    source_text: str
    status: str  # "analyzing" | "ready" | "error"
    error_detail: str | None = None


class Character(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    name: str
    description: str
    is_narrator: bool = False
    voice_preset: str | None = None
    voice_instructions: str
    preview_audio_path: str | None = None
    # Bumped on every PATCH that changes voice_preset/voice_instructions;
    # eager preview generation (Plan 02-04, Pitfall 5) only writes
    # preview_audio_path back if this still matches the version it started
    # with — last-request-wins under rapid re-assignment.
    voice_version: int = 0


class Segment(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    order: int
    character_id: str = Field(foreign_key="character.id")
    text: str
    voice_instructions: str
