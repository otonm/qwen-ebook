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

import httpx
from pydantic import ValidationError
from sqlmodel import Session

from app.analysis_client import analyze
from app.chunking import chunk_paragraphs
from app.config import settings
from app.db import engine
from app.models import Character, Project, Segment
from app.schemas import CastAnalysisResult, CharacterSuggestion, SegmentSuggestion
from app.token_estimate import estimate_tokens

logger = logging.getLogger(__name__)

# Keyed by project_id — each analysis run gets its own progress queue for
# its lifetime, popped once a terminal ("done"/"error") event is drained.
_progress_queues: dict[str, asyncio.Queue] = {}

# D-07: last-20-resolved-segments continuity window fed to each subsequent
# chunk's analyze() call.
_RECENT_SEGMENTS_LIMIT = 20

# content-loss fix (debug/llm-analysis-content-loss.md): formatting is
# allowed to be normalized, so segment text is never expected to be
# byte-identical in length to its source — but a ratio this low is a signal
# of real content loss, not cosmetic whitespace/blank-line collapsing.
_CONTENT_COVERAGE_WARN_RATIO = 0.85

# content-loss fix round 2 (debug/llm-analysis-content-loss.md): real-key
# testing showed the SAME input can swing from 59% to 98% coverage between
# calls (finish_reason="stop" but the model self-truncated the transcription
# task early) — a bounded retry turns that measured non-determinism into a
# real mitigation instead of just a log line. 1 initial attempt + 2 retries.
_MAX_ANALYZE_ATTEMPTS = 3


def _coverage_ratio(source_text: str, result: CastAnalysisResult) -> float:
    """Fraction of `source_text`'s length reproduced across `result`'s
    segments — the content-loss tripwire's core measurement, shared by the
    retry gate below."""
    source_len = len(source_text)
    if source_len == 0:
        return 1.0
    return sum(len(s.text) for s in result.segments) / source_len


async def _analyze_with_retry(
    label: str,
    text: str,
    running_cast: list[CharacterSuggestion] | None = None,
    recent_segments: list[SegmentSuggestion] | None = None,
) -> CastAnalysisResult:
    """Calls `analyze()`, retrying up to `_MAX_ANALYZE_ATTEMPTS` times when
    the result covers too little of `text` — promotes the old log-only
    coverage tripwire to an enforced gate: a persistently incomplete result
    now fails loud (raises, caller's except sets project.status="error" with
    an informative error_detail) instead of silently persisting as if
    nothing were missing, which is the exact silent failure mode this
    debug session's second round diagnosed.

    content-loss fix round 3: also retries on `analyze()` itself raising —
    real-key testing on a large/dense chunk showed the provider
    occasionally return malformed structured-output JSON near the
    completion-token ceiling (`CastAnalysisResult.model_validate_json()`
    raises `ValidationError`) instead of just a low-coverage-but-valid
    result. That's the same non-determinism the coverage retry already
    mitigates, so it gets the same bounded-retry treatment rather than
    failing the whole chunk on one bad sample."""
    ratio = 0.0
    last_error: Exception | None = None
    for attempt in range(1, _MAX_ANALYZE_ATTEMPTS + 1):
        try:
            result = await analyze(
                text, running_cast=running_cast, recent_segments=recent_segments
            )
        except (ValidationError, httpx.HTTPError) as exc:
            last_error = exc
            logger.warning(
                f"{label}: attempt {attempt}/{_MAX_ANALYZE_ATTEMPTS} raised "
                f"{type(exc).__name__} — "
                + ("retrying" if attempt < _MAX_ANALYZE_ATTEMPTS else "giving up")
            )
            continue
        ratio = _coverage_ratio(text, result)
        if ratio >= _CONTENT_COVERAGE_WARN_RATIO:
            return result
        last_error = None
        logger.warning(
            f"{label}: attempt {attempt}/{_MAX_ANALYZE_ATTEMPTS} covered only "
            f"{ratio:.0%} of source text — "
            + ("retrying" if attempt < _MAX_ANALYZE_ATTEMPTS else "giving up")
        )
    if last_error is not None:
        raise RuntimeError(
            f"{label}: analysis repeatedly failed ({_MAX_ANALYZE_ATTEMPTS} attempts, "
            f"last error: {last_error}) — provider may be returning malformed output "
            "near the completion-token ceiling; try a smaller ANALYSIS_TOKEN_LIMIT"
        ) from last_error
    raise RuntimeError(
        f"{label}: analysis repeatedly returned incomplete content ({ratio:.0%} "
        f"coverage after {_MAX_ANALYZE_ATTEMPTS} attempts) — try a smaller "
        "ANALYSIS_TOKEN_LIMIT/CHUNK_TARGET_LEN"
    )


def _get_queue(project_id: str) -> asyncio.Queue:
    return _progress_queues.setdefault(project_id, asyncio.Queue())


def has_pending_queue(project_id: str) -> bool:
    """True if `project_id` still has a live progress queue — i.e. its
    terminal ("done"/"error") event hasn't been drained yet (WR-02). Used
    by the SSE endpoint to tell "analysis finished, but nobody's consumed
    the buffered events yet" apart from "already fully drained by an
    earlier subscriber" without creating a fresh (permanently empty) queue
    as a side effect."""
    return project_id in _progress_queues


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


def _should_chunk(text: str) -> bool:
    """D-05/D-06: prefer single-shot; only fall back to multi-chunk once
    the chars/4 estimate exceeds the ~50%-of-context safety margin."""
    return estimate_tokens(text) > settings.ANALYSIS_TOKEN_LIMIT


def _group_chunks(chunks: list[str], budget_chars: int) -> list[str]:
    """Greedily merge `chunk_paragraphs()` output up to `budget_chars` per
    group, joined back with a blank line so every paragraph/chapter break
    chunk_paragraphs already respects stays visible between merged pieces.

    Never slices through a chunk_paragraphs() atom — only ever concatenates
    whole ones — so a group boundary always falls on one of those original
    breaks, never mid-chapter (D-12 / RESEARCH.md anti-pattern: don't
    concatenate-then-reblind-chunk across chapter boundaries).
    """
    groups: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for chunk in chunks:
        added = len(chunk) + (2 if buf else 0)  # "\n\n" separator
        if buf and buf_len + added > budget_chars:
            groups.append("\n\n".join(buf))
            buf = [chunk]
            buf_len = len(chunk)
        else:
            buf.append(chunk)
            buf_len += added
    if buf:
        groups.append("\n\n".join(buf))
    return groups


def _persist_result(
    session: Session,
    project_id: str,
    result: CastAnalysisResult,
    name_to_id: dict[str, str],
    order_start: int,
) -> int:
    """Persist `result`'s characters (reconciled onto `name_to_id` by exact
    name match) and segments (globally ordered starting at `order_start`).
    Returns the next free order value.

    # ponytail: name-equality reconciliation is the deliberate ceiling —
    # the LLM is prompted (D-08) to reuse an existing character's exact
    # name for a confident repeat; the wizard's merge tool (WIZ-02) is the
    # human upgrade path for anything it gets wrong. No fuzzy-matching.
    """
    for suggestion in result.characters:
        if suggestion.name in name_to_id:
            continue
        character = Character(
            id=uuid.uuid4().hex,
            project_id=project_id,
            name=suggestion.name,
            description=suggestion.description,
            is_narrator=suggestion.is_narrator,
            # PRESET-REWORK: persist the LLM's own preset pick rather than
            # leaving it unset (best_guess_preset only kicks in for
            # manually-added/edited characters with no preset).
            voice_preset=suggestion.voice_preset,
            # D-16: pre-fill from the LLM's adapted, per-character
            # description as an editable default — this is the character's
            # base voice, merged with each dialogue segment's own delivery
            # instruction at TTS time (voices.merge_instructions).
            voice_instructions=suggestion.description,
        )
        session.add(character)
        name_to_id[suggestion.name] = character.id

    order = order_start
    # WR-04: sort by the LLM's own `suggestion.order` rather than trusting
    # list-iteration position — `.order` is part of the structured-output
    # contract precisely so a provider that ever returns `result.segments`
    # out of its intended sequence doesn't silently persist segments in the
    # wrong order with nothing catching the mismatch.
    for suggestion in sorted(result.segments, key=lambda s: s.order):
        character_id = name_to_id.get(suggestion.character_name)
        if character_id is None:
            # The LLM referenced a character name not in its own cast
            # list — skip rather than violate the FK. Logged (WR-03) so an
            # LLM prompt-adherence regression leaves a trace instead of
            # silently losing narration/dialogue with no way to diagnose it.
            logger.warning(
                f"project {project_id}: dropping segment for unknown "
                f"character_name {suggestion.character_name!r}"
            )
            continue
        session.add(
            Segment(
                id=uuid.uuid4().hex,
                project_id=project_id,
                order=order,
                character_id=character_id,
                text=suggestion.text,
                voice_instructions=suggestion.voice_instructions,
            )
        )
        order += 1

    return order


async def _run_chunked_analysis(project_id: str, text: str, queue: asyncio.Queue) -> None:
    """D-07/D-08 multi-chunk fallback: chunk_paragraphs() as the base unit,
    grouped up to a per-call char budget, each subsequent call re-supplied
    with the running resolved cast + last-20-resolved-segments continuity
    context so the LLM can reconcile repeat characters across chunks."""
    chunks = chunk_paragraphs(text, target_len=settings.CHUNK_TARGET_LEN)
    budget_chars = settings.ANALYSIS_TOKEN_LIMIT * 4  # chars ~= tokens*4, same D-06 budget logic
    groups = _group_chunks(chunks, budget_chars)
    total = len(groups)

    name_to_id: dict[str, str] = {}
    running_cast: list[CharacterSuggestion] = []
    running_cast_names: set[str] = set()
    recent_segments: list[SegmentSuggestion] = []
    order = 0

    for index, group_text in enumerate(groups, start=1):
        await queue.put(("progress", {"stage": "chunk", "n": index, "total": total}))
        result = await _analyze_with_retry(
            f"project {project_id} chunk {index}/{total}",
            group_text,
            running_cast=running_cast or None,
            recent_segments=recent_segments or None,
        )

        with Session(engine) as session:
            order = _persist_result(session, project_id, result, name_to_id, order)
            session.commit()

        for suggestion in result.characters:
            if suggestion.name not in running_cast_names:
                running_cast.append(suggestion)
                running_cast_names.add(suggestion.name)
        recent_segments.extend(result.segments)
        recent_segments = recent_segments[-_RECENT_SEGMENTS_LIMIT:]


async def run_analysis(project_id: str) -> None:
    queue = _get_queue(project_id)
    try:
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            text = project.source_text

        await queue.put(("progress", {"stage": "estimating"}))
        token_count = estimate_tokens(text)
        logger.info(f"project {project_id} estimated at {token_count} tokens")

        if _should_chunk(text):
            await _run_chunked_analysis(project_id, text, queue)
        else:
            await queue.put(("progress", {"stage": "analyzing"}))
            result = await _analyze_with_retry(f"project {project_id}", text)
            with Session(engine) as session:
                _persist_result(session, project_id, result, {}, order_start=0)
                session.commit()

        with Session(engine) as session:
            project = session.get(Project, project_id)
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
