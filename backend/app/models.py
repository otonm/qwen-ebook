"""SQLModel persistence tables: Project, Character, Segment.

Plan 03-01 adds Segment's generation-status/content-hash-cache fields and
Project's created_at/output_path — front-loaded here so later Phase 3 plans
never touch this file again (see 03-01-PLAN.md).
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    filename: str
    source_text: str
    status: str  # "analyzing" | "ready" | "error"
    error_detail: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Set once the full-project audio join (plan 03-03) completes.
    output_path: str | None = None


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
    # Plan 03-01 generation fields (GEN-02/03/05).
    generation_status: str = "pending"  # "pending" | "generating" | "complete" | "error"
    generation_error: str | None = None
    audio_path: str | None = None
    cache_key: str | None = None
    # Bumped on every PATCH; regenerate_segment only writes back if this
    # still matches the version it started with — last-request-wins guard,
    # same pattern as Character.voice_version.
    generation_version: int = 0
