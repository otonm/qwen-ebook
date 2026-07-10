"""Tests for the real xai-sdk analyze() wiring (Task 1) and the multi-chunk
fallback + cross-chunk reconciliation path (Task 2).

Task 1 tests are selected by `pytest -k "prompt or role or parse"` per
02-03-PLAN.md's Task 1 <verify> — they fake xai_sdk entirely (via
sys.modules injection) so no network call happens even under a non-mock
LLM_BACKEND.

Task 2 tests run the whole file under LLM_BACKEND=mock and drive
app.analysis_worker.run_analysis() directly against a real (SQLite) test
DB, monkeypatching `analysis_worker.analyze` to a fake that returns two
chunks with an overlapping character so the reconciliation-by-name path is
exercised deterministically.
"""

from __future__ import annotations

import asyncio
import sys
import types
import uuid
from dataclasses import replace

from sqlmodel import Session, select

from app import analysis_client, analysis_worker
from app.config import settings
from app.db import engine, init_db
from app.models import Character, Project, Segment
from app.schemas import CastAnalysisResult, CharacterSuggestion, SegmentSuggestion

init_db()


def _make_project(text: str) -> str:
    project_id = uuid.uuid4().hex
    with Session(engine) as session:
        session.add(
            Project(id=project_id, filename="book.txt", source_text=text, status="analyzing")
        )
        session.commit()
    return project_id


# ---------------------------------------------------------------------------
# Task 1: real analyze() — system prompt content + role separation + parse()
# ---------------------------------------------------------------------------


def test_system_prompt_covers_required_elements():
    prompt = analysis_client.CAST_ANALYSIS_SYSTEM_PROMPT
    assert "narrator" in prompt.lower()
    assert "character" in prompt.lower()
    assert "description" in prompt.lower()  # trait inference target field
    assert "segments" in prompt.lower()
    assert "voice_instructions" in prompt.lower()
    assert "running_cast" in prompt.lower()  # cross-chunk reconciliation (D-08)


def _install_fake_xai_sdk(monkeypatch, fake_result: CastAnalysisResult) -> dict:
    """Patch sys.modules so `from xai_sdk import AsyncClient` and
    `from xai_sdk.chat import system, user` (both used lazily, inside
    analysis_client._real_analyze) resolve to fakes — no real xai_sdk
    network call, no real dependency on the installed package's behavior."""
    calls: dict = {}

    class FakeChat:
        def __init__(self) -> None:
            self.appended: list[dict] = []

        def append(self, message: dict) -> None:
            self.appended.append(message)

        async def parse(self, shape: type) -> tuple[object, CastAnalysisResult]:
            calls["parse_shape"] = shape
            return object(), fake_result

    class FakeChatNamespace:
        def create(self, model: str, messages: list[dict]) -> FakeChat:
            calls["create_model"] = model
            calls["create_messages"] = messages
            chat = FakeChat()
            calls["chat"] = chat
            return chat

    class FakeAsyncClient:
        def __init__(self, api_key: str) -> None:
            calls["api_key"] = api_key
            self.chat = FakeChatNamespace()

    fake_xai_sdk = types.ModuleType("xai_sdk")
    fake_xai_sdk.AsyncClient = FakeAsyncClient
    fake_chat_module = types.ModuleType("xai_sdk.chat")
    fake_chat_module.system = lambda text: {"role": "system", "content": text}
    fake_chat_module.user = lambda text: {"role": "user", "content": text}
    fake_xai_sdk.chat = fake_chat_module

    monkeypatch.setitem(sys.modules, "xai_sdk", fake_xai_sdk)
    monkeypatch.setitem(sys.modules, "xai_sdk.chat", fake_chat_module)

    monkeypatch.setattr(
        analysis_client,
        "settings",
        replace(settings, LLM_BACKEND="grok", XAI_API_KEY="fake-key"),
    )
    return calls


def test_real_backend_keeps_system_prompt_and_book_text_in_separate_roles(monkeypatch):
    fake_result = CastAnalysisResult(
        characters=[CharacterSuggestion(name="Narrator", description="calm", is_narrator=True)],
        segments=[
            SegmentSuggestion(
                order=0, character_name="Narrator", text="Hi.", voice_instructions="calm"
            )
        ],
    )
    calls = _install_fake_xai_sdk(monkeypatch, fake_result)

    book_text = "BOOK TEXT MARKER: once upon a time."
    result = asyncio.run(analysis_client.analyze(book_text))

    assert result is fake_result
    assert calls["parse_shape"] is CastAnalysisResult

    # System message carries only the fixed system prompt — never the book
    # text (T-02-07 prompt-injection mitigation).
    system_messages = calls["create_messages"]
    assert len(system_messages) == 1
    assert system_messages[0]["role"] == "system"
    assert system_messages[0]["content"] == analysis_client.CAST_ANALYSIS_SYSTEM_PROMPT
    assert book_text not in system_messages[0]["content"]

    # Book text arrives in a separate, later user() message via chat.append.
    appended = calls["chat"].appended
    assert len(appended) == 1
    assert appended[0]["role"] == "user"
    assert book_text in appended[0]["content"]


def test_real_backend_passes_continuity_context_in_user_message_not_system(monkeypatch):
    fake_result = CastAnalysisResult(characters=[], segments=[])
    calls = _install_fake_xai_sdk(monkeypatch, fake_result)

    running_cast = [CharacterSuggestion(name="Captain Reyes", description="an old sailor")]
    recent_segments = [
        SegmentSuggestion(
            order=0,
            character_name="Captain Reyes",
            text="The sea remembers.",
            voice_instructions="gravelly",
        )
    ]

    asyncio.run(
        analysis_client.analyze(
            "new chunk text", running_cast=running_cast, recent_segments=recent_segments
        )
    )

    system_content = calls["create_messages"][0]["content"]
    assert "Captain Reyes" not in system_content

    appended_content = calls["chat"].appended[0]["content"]
    assert "Captain Reyes" in appended_content
    assert "The sea remembers." in appended_content
    assert "new chunk text" in appended_content


# ---------------------------------------------------------------------------
# Task 2: multi-chunk fallback + reconciliation
# ---------------------------------------------------------------------------


def test_should_chunk_boundary_is_strictly_greater_than_limit(monkeypatch):
    monkeypatch.setattr(analysis_worker, "settings", replace(settings, ANALYSIS_TOKEN_LIMIT=10))
    assert analysis_worker._should_chunk("x" * 40) is False  # 40 // 4 == 10, not > 10
    assert analysis_worker._should_chunk("x" * 44) is True  # 44 // 4 == 11 > 10


def test_group_chunks_never_merges_across_a_chapter_blank_line_boundary():
    ch1 = "Chapter one opens on a quiet harbor at dawn"
    ch2 = "Chapter two follows the crew into the storm"
    ch3 = "Chapter three brings them safely home again"
    chunks = [ch1, ch2, ch3]

    # Budget fits exactly two chapters joined with "\n\n" but not three.
    budget = len(ch1) + len(ch2) + 2

    groups = analysis_worker._group_chunks(chunks, budget)

    assert groups == [f"{ch1}\n\n{ch2}", ch3]
    # No group is a mid-chapter fragment — every group, split back on the
    # blank-line boundary, recovers only whole original chunks.
    recovered = [piece for group in groups for piece in group.split("\n\n")]
    assert recovered == chunks


def test_run_analysis_multi_chunk_reconciles_duplicate_and_orders_segments_globally(monkeypatch):
    monkeypatch.setattr(
        analysis_worker,
        "settings",
        replace(settings, ANALYSIS_TOKEN_LIMIT=1, CHUNK_TARGET_LEN=40),
    )

    calls: list[dict] = []

    async def fake_analyze(text, running_cast=None, recent_segments=None):
        # Snapshot (not alias) — analysis_worker mutates its own lists
        # in-place after this call returns.
        calls.append(
            {
                "text": text,
                "running_cast": list(running_cast) if running_cast else running_cast,
                "recent_segments": list(recent_segments) if recent_segments else recent_segments,
            }
        )
        if len(calls) == 1:
            return CastAnalysisResult(
                characters=[
                    CharacterSuggestion(name="Narrator", description="calm", is_narrator=True),
                    CharacterSuggestion(name="Marcus", description="an old sailor"),
                ],
                segments=[
                    SegmentSuggestion(
                        order=0,
                        character_name="Narrator",
                        text="Once there was an old sailor.",
                        voice_instructions="calm",
                    ),
                    SegmentSuggestion(
                        order=1,
                        character_name="Marcus",
                        text="The sea remembers everything.",
                        voice_instructions="gravelly",
                    ),
                ],
            )
        return CastAnalysisResult(
            characters=[
                # Same name as chunk 1 -> must reconcile, not duplicate (D-08).
                CharacterSuggestion(name="Marcus", description="an old sailor"),
                CharacterSuggestion(name="Elena", description="a young apprentice"),
            ],
            segments=[
                SegmentSuggestion(
                    order=0,
                    character_name="Marcus",
                    text="He nodded slowly.",
                    voice_instructions="gravelly",
                ),
                SegmentSuggestion(
                    order=1,
                    character_name="Elena",
                    text="I believe you.",
                    voice_instructions="soft",
                ),
            ],
        )

    monkeypatch.setattr(analysis_worker, "analyze", fake_analyze)

    # Two short paragraphs, each under CHUNK_TARGET_LEN=40 alone but not
    # merge-able together within the tiny ANALYSIS_TOKEN_LIMIT-derived
    # per-call char budget -> exactly two sequential analyze() calls.
    text = "Sailor paragraph one text here.\n\nApprentice paragraph two text here."
    project_id = _make_project(text)

    asyncio.run(analysis_worker.run_analysis(project_id))

    assert len(calls) == 2
    # Chunk 2's call received the running cast + resolved segments from
    # chunk 1 as continuity context (D-07).
    assert [c.name for c in calls[1]["running_cast"]] == ["Narrator", "Marcus"]
    assert [s.character_name for s in calls[1]["recent_segments"]] == ["Narrator", "Marcus"]

    with Session(engine) as session:
        characters = list(
            session.exec(select(Character).where(Character.project_id == project_id)).all()
        )
        segments = list(
            session.exec(select(Segment).where(Segment.project_id == project_id)).all()
        )
        project = session.get(Project, project_id)

    assert project.status == "ready"
    # No duplicate "Marcus" entry despite chunk 2 re-mentioning it.
    assert sorted(c.name for c in characters) == ["Elena", "Marcus", "Narrator"]

    orders = sorted(s.order for s in segments)
    assert orders == [0, 1, 2, 3]  # globally monotonic across both chunks
    assert len(segments) == 4


def test_run_analysis_multi_chunk_emits_per_chunk_sse_progress(monkeypatch):
    monkeypatch.setattr(
        analysis_worker,
        "settings",
        replace(settings, ANALYSIS_TOKEN_LIMIT=1, CHUNK_TARGET_LEN=40),
    )

    async def fake_analyze(text, running_cast=None, recent_segments=None):
        return CastAnalysisResult(
            characters=[CharacterSuggestion(name="Narrator", description="calm", is_narrator=True)],
            segments=[
                SegmentSuggestion(
                    order=0, character_name="Narrator", text=text[:20], voice_instructions="calm"
                )
            ],
        )

    monkeypatch.setattr(analysis_worker, "analyze", fake_analyze)

    text = "Sailor paragraph one text here.\n\nApprentice paragraph two text here."
    project_id = _make_project(text)

    asyncio.run(analysis_worker.run_analysis(project_id))

    queue = analysis_worker._get_queue(project_id)
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    chunk_events = [payload for event_type, payload in events if payload.get("stage") == "chunk"]
    assert {"stage": "chunk", "n": 1, "total": 2} in chunk_events
    assert {"stage": "chunk", "n": 2, "total": 2} in chunk_events
    assert events[-1] == ("done", {"status": "ready"})
