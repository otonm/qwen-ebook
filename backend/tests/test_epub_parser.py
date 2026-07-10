"""Tests for epub_parser.extract_text (ING-02) and the POST /projects
.epub upload branch.

RED for Task 2 of Plan 02-02: must fail before app/epub_parser.py exists
and main.py gains the .txt-vs-.epub branch; passes once both are
implemented.
"""

from __future__ import annotations

import os

os.environ.setdefault("TTS_BACKEND", "mock")
os.environ.setdefault("LLM_BACKEND", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.epub_parser import EpubParseError, extract_text  # noqa: E402
from app.main import app  # noqa: E402
from tests.fixtures.epub_builder import (  # noqa: E402
    CHAPTER1_VISIBLE_TEXT,
    CHAPTER2_VISIBLE_TEXT,
    COPYRIGHT_TEXT,
    FOOTNOTE_BODY_TEXT,
    LINEAR_NO_TEXT,
    build_broken_chapter_epub,
    build_valid_epub,
)

init_db()
client = TestClient(app)


def test_extract_text_returns_narrative_chapters_in_spine_order():
    text = extract_text(build_valid_epub())

    chap1_index = text.find(CHAPTER1_VISIBLE_TEXT)
    chap2_index = text.find(CHAPTER2_VISIBLE_TEXT)

    assert chap1_index != -1
    assert chap2_index != -1
    assert chap1_index < chap2_index


def test_extract_text_skips_cover_and_copyright():
    text = extract_text(build_valid_epub())

    assert "Cover" not in text
    assert COPYRIGHT_TEXT not in text


def test_extract_text_strips_footnote_marker_and_note_body():
    text = extract_text(build_valid_epub())

    assert FOOTNOTE_BODY_TEXT not in text
    # The visible sentence right before the marker must survive untouched.
    assert CHAPTER1_VISIBLE_TEXT in text


def test_extract_text_respects_linear_no_exclusion():
    text = extract_text(build_valid_epub())

    assert LINEAR_NO_TEXT not in text


def test_extract_text_preserves_chapter_boundary_as_blank_line():
    text = extract_text(build_valid_epub())

    boundary = f"{CHAPTER1_VISIBLE_TEXT}\n\n{CHAPTER2_VISIBLE_TEXT}"
    assert boundary in text


def test_extract_text_raises_on_unrecoverable_chapter():
    with pytest.raises(EpubParseError):
        extract_text(build_broken_chapter_epub())


def test_post_projects_with_valid_epub_returns_201_with_clean_text():
    files = {
        "file": ("book.epub", build_valid_epub(), "application/epub+zip"),
    }

    response = client.post("/projects", files=files)

    assert response.status_code == 201
    project_id = response.json()["id"]

    project_response = client.get(f"/projects/{project_id}")
    assert project_response.status_code == 200
    # source_text isn't in the serialized response; re-fetch straight from
    # the DB row via the same Session/engine the app uses.
    from sqlmodel import Session

    from app.db import engine
    from app.models import Project

    with Session(engine) as session:
        project = session.get(Project, project_id)
        assert project is not None
        assert CHAPTER1_VISIBLE_TEXT in project.source_text
        assert COPYRIGHT_TEXT not in project.source_text


def test_post_projects_with_broken_epub_returns_400_with_reason():
    files = {
        "file": ("broken.epub", build_broken_chapter_epub(), "application/epub+zip"),
    }

    response = client.post("/projects", files=files)

    assert response.status_code == 400
    assert response.json()["detail"]
