"""Background analysis task + in-process SSE progress registry.

D-03: analysis runs as a background asyncio task, not inline in the
request handler that creates the Project — no Celery/Redis (CLAUDE.md), a
plain per-project asyncio.Queue is the right-sized tool for a single-user,
single-process app.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from sqlmodel import Session

from app.analysis_client import analyze
from app.db import engine
from app.models import Character, Project, Segment
from app.token_estimate import estimate_tokens

logger = logging.getLogger(__name__)

# Keyed by project_id — each analysis run gets its own progress queue for
# its lifetime, popped once a terminal ("done"/"error") event is drained.
_progress_queues: dict[str, asyncio.Queue] = {}


def _get_queue(project_id: str) -> asyncio.Queue:
    return _progress_queues.setdefault(project_id, asyncio.Queue())


async def progress_events(project_id: str) -> AsyncIterator[tuple[str, dict]]:
    """Drain `project_id`'s progress queue until a terminal event, per the
    SSE endpoint in main.py."""
    queue = _get_queue(project_id)
    while True:
        event_type, payload = await queue.get()
        yield event_type, payload
        if event_type in ("done", "error"):
            _progress_queues.pop(project_id, None)
            return


async def run_analysis(project_id: str) -> None:
    queue = _get_queue(project_id)
    try:
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            text = project.source_text

        await queue.put(("progress", {"stage": "estimating"}))
        # Single-shot only this plan; multi-chunk fallback for texts over
        # ANALYSIS_TOKEN_LIMIT (D-07/D-08 cross-chunk reconciliation) is
        # Plan 03 — computed and logged here so the threshold is visible.
        logger.info(
            "project %s estimated at %d tokens", project_id, estimate_tokens(text)
        )

        await queue.put(("progress", {"stage": "analyzing"}))
        result = await analyze(text)

        with Session(engine) as session:
            project = session.get(Project, project_id)
            name_to_id: dict[str, str] = {}
            for suggestion in result.characters:
                character = Character(
                    id=uuid.uuid4().hex,
                    project_id=project_id,
                    name=suggestion.name,
                    description=suggestion.description,
                    is_narrator=suggestion.is_narrator,
                    # D-16: pre-fill from the inferred description as an
                    # editable default — CharacterSuggestion carries no
                    # voice_instructions field, so this is always the fill.
                    voice_instructions=suggestion.description,
                )
                session.add(character)
                name_to_id[suggestion.name] = character.id

            for suggestion in result.segments:
                character_id = name_to_id.get(suggestion.character_name)
                if character_id is None:
                    # Grok/mock referenced a character name not in its own
                    # cast list — skip rather than violate the FK.
                    continue
                session.add(
                    Segment(
                        id=uuid.uuid4().hex,
                        project_id=project_id,
                        order=suggestion.order,
                        character_id=character_id,
                        text=suggestion.text,
                        voice_instructions=suggestion.voice_instructions,
                    )
                )

            project.status = "ready"
            session.add(project)
            session.commit()

        await queue.put(("done", {"status": "ready"}))
    except Exception as exc:
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "error"
                project.error_detail = str(exc)
                session.add(project)
                session.commit()
        await queue.put(("error", {"detail": str(exc)}))
