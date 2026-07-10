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
from dataclasses import replace

from app import analysis_client
from app.config import settings
from app.schemas import CastAnalysisResult, CharacterSuggestion, SegmentSuggestion

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
