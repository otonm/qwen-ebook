"""Upload-validation tests for POST /projects.

Phase 1's synchronous "upload -> chunk -> synthesize -> join -> download"
shape of this endpoint is retired as of Plan 02-01: POST /projects now
returns 201 {id, status} immediately and runs analysis in the background
(see test_analysis_pipeline.py for that full flow). The bounded-upload/
UTF-8/empty-body validation this endpoint still performs on the way in is
unchanged from Phase 1, so those checks are kept here.
"""

import os

os.environ.setdefault("TTS_BACKEND", "mock")
os.environ.setdefault("LLM_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)


def test_oversized_upload_is_rejected():
    oversized = b"a" * (settings.MAX_UPLOAD_BYTES + 1)
    files = {"file": ("big.txt", oversized, "text/plain")}

    response = client.post("/projects", files=files)

    assert response.status_code in (400, 413)


def test_non_utf8_upload_is_rejected_with_400():
    non_utf8_bytes = b"\xff\xfe\x00\x01invalid-utf8"
    files = {"file": ("bad-encoding.txt", non_utf8_bytes, "text/plain")}

    response = client.post("/projects", files=files)

    assert response.status_code == 400


def test_empty_upload_is_rejected_with_400():
    files = {"file": ("empty.txt", b"   \n\n  ", "text/plain")}

    response = client.post("/projects", files=files)

    assert response.status_code == 400
