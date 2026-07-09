"""End-to-end test for the upload -> chunk -> synthesize -> join -> download pipeline.

Runs against the mock TTS backend (TTS_BACKEND=mock) so it requires no GPU.
This is the RED test for Task 1: it must fail before app.main exists, and
pass once Task 2 implements the happy-path pipeline.
"""

import os

os.environ.setdefault("TTS_BACKEND", "mock")

from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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
