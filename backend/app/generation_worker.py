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

# T-03-25/T-03-26, generalized in 04-03 (Pitfall 3): keyed by the same
# label strings try_claim_generation already receives — "segment:{id}",
# "preview:{id}", "batch:{id}" — so EVERY kind of generation (not just
# batch) has an addressable task a cancel endpoint can look up. main.py
# registers via register_generation_task and removes the entry via a
# done-callback, same registry discipline as _generation_progress_queues.
_running_generations: dict[str, asyncio.Task] = {}

# Single-flight guard: at most one generation — a character preview, a
# per-row segment, or a whole batch run, in any project — may be in flight
# across the ENTIRE app at once. tts_service/server.py's /synthesize has no
# concurrency control of its own (a bare run_in_threadpool with no lock or
# queue), so two uncoordinated calls would race the same model instance on
# a single 16GB-VRAM GPU. Global rather than per-project because the
# constraint is the one shared GPU, not any one project. A plain module
# global (not an asyncio.Lock) is safe here: there is no `await` between
# the check and the set in try_claim_generation, and asyncio is
# single-threaded, so no other coroutine can interleave between them.
_active_generation_label: str | None = None


def is_any_generation_active() -> bool:
    return _active_generation_label is not None


def try_claim_generation(label: str) -> bool:
    """Atomically claim the single global generation slot. Returns False
    without blocking or queueing if another generation already holds it —
    callers surface that as a 409 (explicit user action) or silently skip
    (best-effort background regen, e.g. after undo-merge)."""
    global _active_generation_label
    if _active_generation_label is not None:
        return False
    _active_generation_label = label
    return True


def release_generation() -> None:
    global _active_generation_label
    _active_generation_label = None


# 04-03/Pitfall 2: labels with a cancel in progress. Empirically, cancelling
# an asyncio Task that's awaiting starlette's run_in_threadpool (anyio
# to_thread) does NOT wait for the underlying worker thread to finish —
# the await unblocks almost immediately while the thread keeps running
# detached (verified directly against this app's installed anyio/starlette
# versions, contradicting the naive assumption that task.cancel() + await
# blocks for the real call's full duration). Calling task.cancel() would
# therefore make _spawn_claimed_generation's done-callback (and
# run_batch_generation's per-segment loop) treat the generation as
# finished — and release the lock / advance to the next segment — the
# instant task.cancel() is issued, exactly the race this plan's "must_haves"
# truth forbids ("never released merely because task.cancel() was issued").
# So cancel handlers never call task.cancel(): they call tts_client.cancel()
# (the real interrupt — server-side StoppingCriteria on real hardware) and
# then plainly `await task`, which only returns once the underlying call
# has ACTUALLY finished (interrupted quickly by the server, or run to its
# natural completion if the interrupt didn't land). The batch loop is the
# one case with a "next item" to skip, so it additionally consults this
# request-to-stop set between segments — set by cancel_generation, cleared
# by consume_stop_requested — to break out of the loop after the
# currently-settling segment instead of proceeding to the next one.
_stop_requested: set[str] = set()


def request_stop(label: str) -> None:
    _stop_requested.add(label)


def consume_stop_requested(label: str) -> bool:
    """True if a stop was requested for `label` since the last check;
    clears the flag so a stale request can't linger into a future run."""
    if label in _stop_requested:
        _stop_requested.discard(label)
        return True
    return False


def is_stop_requested(label: str) -> bool:
    """Non-consuming peek — used where a DIFFERENT consumer still needs to
    observe the same flag afterward. E.g. regenerate_segment peeks
    "batch:{project_id}" to decide whether its own synth failure was
    caused by a cancel (so it can write "pending" instead of "error")
    without clearing the flag out from under run_batch_generation's own
    loop-top consume_stop_requested check, which is what actually stops
    the batch from advancing to the next segment."""
    return label in _stop_requested


def _get_generation_queue(project_id: str) -> asyncio.Queue:
    return _generation_progress_queues.setdefault(project_id, asyncio.Queue())


def ensure_generation_queue(project_id: str) -> None:
    """Eagerly create `project_id`'s progress queue before the HTTP handler
    that starts a run returns. Without this, a client that reconnects its
    SSE stream immediately after the POST response (the frontend's
    generation-stream reconnect-per-run pattern) can race the
    asyncio.create_task'd run_batch_generation's first push_generation_event
    — has_pending_generation_queue would see no queue yet and take the
    "nothing running" fast path, closing the stream before a single
    progress event ever arrives."""
    _get_generation_queue(project_id)


def register_generation_task(label: str, task: asyncio.Task) -> None:
    """Register `task` under `label` (the exact string passed to
    try_claim_generation, e.g. "segment:{id}"/"preview:{id}"/"batch:{id}")
    so a cancel endpoint can later resolve it via get_generation_task_by_label."""
    _running_generations[label] = task


def get_generation_task_by_label(label: str) -> asyncio.Task | None:
    return _running_generations.get(label)


def is_generation_running_by_label(label: str) -> bool:
    """True if `label` has a live (not-yet-done) task registered."""
    task = _running_generations.get(label)
    return task is not None and not task.done()


def is_generation_running(project_id: str) -> bool:
    """Back-compat for generate_project: delegates to the "batch:{id}"
    label."""
    return is_generation_running_by_label(f"batch:{project_id}")


def get_generation_task(project_id: str) -> asyncio.Task | None:
    """Back-compat for generate_project/delete_project: delegates to the
    "batch:{id}" label."""
    return get_generation_task_by_label(f"batch:{project_id}")


async def push_generation_event(project_id: str, event_type: str, payload: dict) -> None:
    """Push an event directly onto `project_id`'s progress queue. Used by
    main.py's cancel endpoint: once a run_batch_generation task is
    cancelled it must NOT push its own terminal event (asyncio.CancelledError
    propagates past both `except Exception` blocks below untouched) — the
    cancel endpoint owns settling the stream instead."""
    queue = _get_generation_queue(project_id)
    await queue.put((event_type, payload))


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

    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise RuntimeError(f"project {project_id} not found — join blocked")
        fmt = project.output_format
        # D-07: only the latest output persists on disk — delete the
        # previous joined file before writing the new one.
        if project.output_path and Path(project.output_path).is_file():
            logger.info(f"project {project_id}: deleting previous output {project.output_path}")
            Path(project.output_path).unlink(missing_ok=True)

    wav_paths = [s.audio_path for s in segments if s.audio_path is not None]
    out_dir = Path(settings.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Server-generated uuid filename — never derived from any client string
    # (T-03-06); output_filename is display-only, applied at download time.
    out_path = str(out_dir / f"{uuid.uuid4().hex}.{fmt}")
    await run_in_threadpool(join_wavs, wav_paths, out_path, fmt)

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
    segments' audio (Open Question 1).

    Cancellation: main.py's POST /projects/{id}/generate/cancel (T-03-27,
    extended 04-03 for GEN-08) stops this loop via consume_stop_requested,
    checked at the top of each iteration — NOT via task.cancel(), which
    would abandon whatever segment is currently mid-run_in_threadpool
    without waiting for it to truly finish (Pitfall 2; see
    generation_worker._stop_requested's docstring for why). The cancel
    endpoint owns the post-cancel row reset and terminal event push
    (push_generation_event); this function pushes neither on a stop.
    delete_project is the one remaining caller that still uses a raw
    task.cancel() (T-03-27's original mechanism) — acceptable there
    because the project and its rows are being deleted regardless of
    exactly when the lock frees, so asyncio.CancelledError (a
    BaseException, uncaught by the `except Exception` blocks below) is
    still a valid way to unwind this coroutine early in that one case."""
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
            # 04-03/Pitfall 2: checked at the TOP of each iteration so the
            # currently-settling segment (whatever cancel_generation just
            # interrupted via tts_client.cancel()) always finishes its own
            # try/except below before the loop honors a stop request — this
            # is what actually stops progression to the next segment now
            # that cancel handlers no longer call task.cancel() (see
            # generation_worker._stop_requested's docstring).
            if consume_stop_requested(f"batch:{project_id}"):
                logger.info(
                    f"batch generation for project {project_id} stopped by cancel request"
                )
                return
            with Session(engine) as session:
                segment = session.get(Segment, segment_id)
                if segment is None:
                    continue
                # No status-based skip here (CR-01): a segment's effective
                # speaker can change via bulk-reassign/merge/voice-preset
                # edit without its generation_status being reset, so
                # "complete" is not sufficient proof the cached audio is
                # still valid. Always defer to regenerate_segment's own
                # live cache-key recompute below, which cache-hits (no
                # synth call) when nothing actually changed and correctly
                # detects a stale speaker otherwise.
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
