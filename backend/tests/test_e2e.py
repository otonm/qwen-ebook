"""End-to-end test for the upload -> chunk -> synthesize -> join -> download pipeline.

Runs against the mock TTS backend (TTS_BACKEND=mock) so it requires no GPU.
This is the RED test for Task 1: it must fail before app.main exists, and
pass once Task 2 implements the happy-path pipeline. Task 3 extends it with
upload-rejection cases (oversized upload, non-UTF-8 body).
"""

import os

os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SAMPLE_TEXT = (
    "This is the first paragraph of the sample text. It is short.\n\n"
    "This is the second paragraph. It follows a blank line, so it is a\n"
    "separate paragraph under the chunker's paragraph-splitting rule.\n\n"
    "A third and final short paragraph closes out the sample document."
)


def test_upload_txt_returns_playable_wav():
    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}

    response = client.post("/projects", files=files)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/")

    body = response.content
    assert body[0:4] == b"RIFF"
    assert body[8:12] == b"WAVE"


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
