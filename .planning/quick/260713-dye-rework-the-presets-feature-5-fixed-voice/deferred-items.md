# Deferred Items — 260713-dye

Out-of-scope discoveries logged during execution (not fixed, per the
scope-boundary rule: only auto-fix issues directly caused by this task's
changes).

## `tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined` fails locally

Environmental, not a rework regression. This dev sandbox has an unrelated
live backend process bound to `127.0.0.1:8000` (`ps aux` shows a
`uvicorn app.main:app` process owned by a different working tree/session,
plus a separate real `tts_service` on port 8001). `test_integration.py`'s
`requires_pod` marker probes `GET /docs` on that URL and, finding it
reachable, runs the real-pod integration test instead of skipping — the
failure (`201 != 200` on a multi-chunk upload) comes from that external
process's behavior, not from any file this plan touched. Confirmed
unrelated to the preset rework: none of `voices.py`/`schemas.py`/
`analysis_client.py`/`analysis_worker.py`/`main.py` are exercised by that
assertion in a way this task's diff could regress.
