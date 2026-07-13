# Deferred Items — Phase 04 Immediate Cancellation

Out-of-scope discoveries logged during execution but not fixed (per executor
scope-boundary rules: only auto-fix issues directly caused by the current
task's changes).

## Pre-existing failing test: `test_upload_returns_valid_wav_with_multiple_chunks_joined`

- **Found during:** 04-02 Task 2 full-suite verification run (`uv run pytest -q`)
- **File:** `backend/tests/test_integration.py`
- **Symptom:** Asserts `POST /projects` (upload) returns `200` with a WAV body
  directly. The current API returns `201 {"id": ..., "status": "analyzing"}` —
  the async analyze/review-wizard flow introduced in Phase 2 changed the
  upload contract from synchronous audio generation to an async analysis
  pipeline. This test was last touched in `01-03` (`d4b874e`) and was never
  updated for the Phase 2 contract change.
- **Not fixed:** unrelated to 04-02's files (`backend/tts_service/server.py`,
  `backend/app/tts_client.py`); out of scope per the executor's scope
  boundary. Flagged here for a future test-cleanup pass.
