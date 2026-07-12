"""Resumable batch generation state machine (GEN-05) + generation-stream SSE
progress queue registry — mirrors analysis_worker.py's shape: a per-project
asyncio.Queue registry, drained until a terminal event by main.py's SSE
endpoint.

Per-segment synthesis itself is NOT duplicated here: `run_batch_generation`
calls main.py's `regenerate_segment` (a lazy, in-function import to avoid a
circular import — main.py imports this module at load time) so there is
exactly one place that resolves a speaker, recomputes the GEN-02 content-
hash cache key, and applies the generation_version last-request-wins guard
(Pitfall 2/3). This also means a mid-batch per-row edit and this batch loop
share the identical cache-hit-skip behavior instead of two implementations
drifting apart.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.audio_join import join_wavs
from app.config import settings
from app.db import engine
from app.models import Project, Segment

logger = logging.getLogger(__name__)

# Keyed by project_id, same discipline as analysis_worker._progress_queues —
# a separate registry so a project's analysis stream and generation stream
# never share (or collide on) the same queue.
_generation_progress_queues: dict[str, asyncio.Queue] = {}


def _get_generation_queue(project_id: str) -> asyncio.Queue:
    return _generation_progress_queues.setdefault(project_id, asyncio.Queue())


def has_pending_generation_queue(project_id: str) -> bool:
    """True if `project_id` has a live generation progress queue whose
    terminal ("done"/"error") event hasn't been drained yet — same "already
    finished vs. still buffered" distinction has_pending_queue makes for
    analysis (WR-02)."""
    return project_id in _generation_progress_queues


async def generation_progress_events(project_id: str) -> AsyncIterator[tuple[str, dict]]:
    """Drain `project_id`'s generation progress queue until a terminal
    event, per generation_stream in main.py."""
    queue = _get_generation_queue(project_id)
    while True:
        event_type, payload = await queue.get()
        yield event_type, payload
        if event_type in ("done", "error"):
            _generation_progress_queues.pop(project_id, None)
            return


async def _join_project(project_id: str) -> None:
    """GEN-03/Open Question 1: join every segment's audio_path, in table
    order, into a single output file — but block (raise) if any segment
    lacks a valid audio_path rather than silently skipping it or falling
    back to a "last good" file (ENH-02 is deferred past v1)."""
    with Session(engine) as session:
        segments = sorted(
            session.exec(select(Segment).where(Segment.project_id == project_id)).all(),
            key=lambda s: s.order,
        )

    missing = [s.id for s in segments if not s.audio_path or not Path(s.audio_path).is_file()]
    if missing:
        raise RuntimeError(f"{len(missing)} segment(s) failed to generate — join blocked")

    wav_paths = [s.audio_path for s in segments if s.audio_path is not None]
    out_dir = Path(settings.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Server-generated uuid filename — never derived from any client string
    # (T-03-06).
    out_path = str(out_dir / f"{uuid.uuid4().hex}.{settings.OUTPUT_FORMAT}")
    await run_in_threadpool(join_wavs, wav_paths, out_path, settings.OUTPUT_FORMAT)

    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is not None:
            project.output_path = out_path
            session.add(project)
            session.commit()


async def run_batch_generation(project_id: str) -> None:
    """CFG-03/GEN-05: walk every segment in table order, synthesizing on a
    cache miss and skipping a genuine cache hit, persisting status after
    every segment so a crash mid-run leaves an accurate record and a fresh
    invocation can resume correctly. One segment's synth failure never
    aborts the rest (A4). Ends with a blocking join over the complete
    segments' audio (Open Question 1)."""
    # Lazy import: main.py imports this module at module load time, so a
    # top-level `from app.main import regenerate_segment` here would be
    # circular. By the time this coroutine actually runs, app.main has
    # finished importing.
    from app.main import regenerate_segment

    queue = _get_generation_queue(project_id)

    try:
        # Pitfall 1: a "generating" row left behind by a crashed prior
        # process is not actually in flight — asyncio tasks don't survive a
        # restart. Reset it to "pending" before the loop, or a resumed
        # batch would treat it as someone else's job forever.
        with Session(engine) as session:
            stale = session.exec(
                select(Segment)
                .where(Segment.project_id == project_id)
                .where(Segment.generation_status == "generating")
            ).all()
            for segment in stale:
                segment.generation_status = "pending"
                session.add(segment)
            session.commit()

        with Session(engine) as session:
            segment_ids = [
                s.id
                for s in sorted(
                    session.exec(
                        select(Segment).where(Segment.project_id == project_id)
                    ).all(),
                    key=lambda s: s.order,
                )
            ]

        total = len(segment_ids)
        for index, segment_id in enumerate(segment_ids, start=1):
            with Session(engine) as session:
                segment = session.get(Segment, segment_id)
                if segment is None:
                    continue
                if (
                    segment.generation_status == "complete"
                    and segment.audio_path
                    and Path(segment.audio_path).is_file()
                ):
                    # Optimization only, not a correctness requirement:
                    # regenerate_segment below would no-op via its own live
                    # cache-key recompute anyway (Pitfall 3); skipping here
                    # just avoids a spurious "generating" progress blip for
                    # an already-good row.
                    await queue.put(
                        (
                            "progress",
                            {
                                "segment_id": segment_id,
                                "n": index,
                                "total": total,
                                "status": "complete",
                            },
                        )
                    )
                    continue
                segment.generation_status = "generating"
                session.add(segment)
                session.commit()
                version = segment.generation_version

            await queue.put(
                (
                    "progress",
                    {
                        "segment_id": segment_id,
                        "n": index,
                        "total": total,
                        "status": "generating",
                    },
                )
            )

            try:
                await regenerate_segment(segment_id, version)
            except Exception as exc:
                # Backstop: regenerate_segment already catches its own synth
                # failures and persists "error" — this catches anything
                # else unexpected so one bad row still can't take the batch
                # down (GEN-05/A4).
                logger.exception(f"batch generation failed for segment {segment_id}")
                with Session(engine) as session:
                    segment = session.get(Segment, segment_id)
                    if segment is not None:
                        segment.generation_status = "error"
                        segment.generation_error = str(exc)
                        session.add(segment)
                        session.commit()
                await queue.put(
                    (
                        "progress",
                        {
                            "segment_id": segment_id,
                            "n": index,
                            "total": total,
                            "status": "error",
                        },
                    )
                )
                continue

            with Session(engine) as session:
                segment = session.get(Segment, segment_id)
                status = segment.generation_status if segment is not None else "error"
            await queue.put(
                (
                    "progress",
                    {"segment_id": segment_id, "n": index, "total": total, "status": status},
                )
            )

        try:
            await _join_project(project_id)
        except Exception as exc:
            logger.exception(f"batch join failed for project {project_id}")
            await queue.put(("error", {"detail": str(exc)}))
            return

        await queue.put(("done", {"status": "ready"}))
    except Exception as exc:
        logger.exception(f"batch generation crashed for project {project_id}")
        await queue.put(("error", {"detail": str(exc)}))
