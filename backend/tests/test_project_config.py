"""Project config PATCH + download route tests (Phase 6, CFG-06/07/08).

PATCH /projects/{id}: format validated against CODEC_TABLE (422 for
anything outside flac/mp3/opus, including the retired "wav"), and
output_filename is sanitized server-side (illegal chars + any user-typed
extension stripped) before it's persisted.

GET /projects/{id}/download: serves the joined file with the correct
Content-Type + a Content-Disposition filename built from the sanitized
stem + current format's extension; 409 when no output is ready, 404 for an
unknown project.

Runs entirely against TTS_BACKEND=mock/LLM_BACKEND=mock — no GPU needed.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.audio_join import CODEC_TABLE  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Project  # noqa: E402

init_db()
client = TestClient(app)


def _seed_project() -> str:
    project_id = uuid.uuid4().hex
    with Session(engine) as session:
        session.add(
            Project(
                id=project_id,
                filename="my_book.epub",
                source_text="hello",
                status="ready",
            )
        )
        session.commit()
    return project_id


def test_patch_output_format_persists_and_returns_project():
    project_id = _seed_project()

    response = client.patch(f"/projects/{project_id}", json={"output_format": "opus"})

    assert response.status_code == 200
    assert response.json()["output_format"] == "opus"


def test_patch_output_format_rejects_unsupported_value():
    project_id = _seed_project()

    response = client.patch(f"/projects/{project_id}", json={"output_format": "wav"})

    assert response.status_code == 422


def test_patch_output_filename_strips_illegal_chars_and_extension():
    project_id = _seed_project()

    response = client.patch(
        f"/projects/{project_id}", json={"output_filename": 'a/b:my*book.mp3'}
    )

    assert response.status_code == 200
    assert response.json()["output_filename"] == "a_b_mybook"


def test_download_returns_409_when_output_not_ready():
    project_id = _seed_project()

    response = client.get(f"/projects/{project_id}/download")

    assert response.status_code == 409


def test_download_returns_404_for_unknown_project():
    response = client.get(f"/projects/{uuid.uuid4().hex}/download")

    assert response.status_code == 404


def test_download_serves_file_with_correct_content_type_and_filename(tmp_path):
    project_id = _seed_project()
    output_file = tmp_path / "joined.opus"
    output_file.write_bytes(b"not real audio, just bytes for the download route")

    with Session(engine) as session:
        project = session.get(Project, project_id)
        project.output_format = "opus"
        project.output_path = str(output_file)
        project.output_filename = "my great book"
        session.add(project)
        session.commit()

    response = client.get(f"/projects/{project_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(CODEC_TABLE["opus"]["content_type"])
    # Starlette's FileResponse RFC-6266-encodes a space-containing filename
    # as filename*=utf-8''..., percent-escaping spaces rather than a bare
    # ASCII filename= — assert on the decoded, URL-escaped form instead of
    # a literal substring match.
    assert "my%20great%20book.opus" in response.headers["content-disposition"]
