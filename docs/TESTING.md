<!-- generated-by: gsd-doc-writer -->
# Testing

This project has **no unit test suite and no mock backends**. Testing is
end-to-end against the real deployment: bring up the two-container pod with
`deploy/run-local.sh`, then exercise upload -> analysis -> review ->
generation -> join -> download through the UI or `curl`.

There are two small stdlib self-checks and two static checks (lint,
typecheck). That's the full toolbox — nothing else runs automatically.

## Self-checks

Two backend modules carry a tiny `assert`-based self-check in their
`__main__` block. Run them directly with `python`:

```bash
cd backend
uv run python -m app.voices
uv run python -m app.cache_key
```

- `backend/app/voices.py` — asserts `merge_instructions` combines/strips
  base + delivery text correctly, `preset_speaker` falls back to the
  default speaker for empty/unknown preset ids, and the preset roster has
  the expected 6 entries. Prints `voices self-check passed`.
- `backend/app/cache_key.py` — asserts `compute_cache_key` is deterministic
  for identical inputs and changes when the text or `model_id` changes
  (the property the segment-generation cache depends on). Prints
  `cache_key self-check passed`.

Run these after touching either module — they're the only thing standing
between a silent logic regression and a bad audio cache hit.

## Lint gate (required)

```bash
cd backend && uv run ruff check .
```

Strict rule set (`E, F, I, UP, B` per `backend/pyproject.toml`). Apply
`--fix` for auto-fixable issues, then fix any remaining warnings by hand.
Do not commit with outstanding ruff warnings. See CLAUDE.md conventions for
the `# noqa` policy (non-test code needs a justifying comment; test files
may use `noqa` freely).

## Frontend typecheck

```bash
cd frontend && npm run typecheck
```

Runs `tsc --noEmit`. `npm run lint` (ESLint) and `npm run build` (`tsc -b
&& vite build`) are also available in `frontend/package.json` and worth
running before a release, but typecheck is the required gate.

## End-to-end smoke checklist

Requires the pod running (GPU-backed TTS container + backend container).
Bring it up with:

```bash
bash deploy/run-local.sh
```

This builds both images, starts the pod, and waits (up to
`HEALTH_TIMEOUT_SECONDS`, default 900s — first run downloads the model
from Hugging Face) for the TTS container's `/healthz` to report ready.

Once the script prints "Pod is up", exercise the flow manually:

1. **Health checks**
   ```bash
   curl -i http://127.0.0.1:8000/healthz          # backend: 200 only if it can reach the TTS service
   sudo podman exec qwen-ebook-tts curl -i http://localhost:8001/healthz  # TTS: 200 only once the model is resident
   ```
2. **Upload** — a small `.txt` file (or `.epub`) and confirm a project is created:
   ```bash
   curl -F file=@sample.txt http://127.0.0.1:8000/projects
   ```
3. **Analysis** — watch the LLM cast/segment the text via the SSE stream
   (`GET /projects/{project_id}/analysis-stream`), or just poll
   `GET /projects/{project_id}` until characters/segments are populated.
4. **Review** — open the frontend (served by the backend itself) and
   confirm the character list and segment table render, and that editing a
   segment (`PATCH /segments/{segment_id}`) and previewing a character
   voice (`POST /characters/{character_id}/preview`) both work.
5. **Single-segment generate** — trigger one segment
   (`POST /segments/{segment_id}/generate`) and confirm
   `GET /segments/{segment_id}/audio.wav` returns audio once generation
   status flips to done.
6. **Full generate + join + download** — trigger the whole project
   (`POST /projects/{project_id}/generate`), watch progress via
   `GET /projects/{project_id}/generation-stream`, then download the
   joined file:
   ```bash
   curl http://127.0.0.1:8000/projects/{project_id}/download -o audiobook.wav
   ```
   Play it back and confirm narration and character voices sound correct
   and segments join without gaps or clicks.

Tear down with `sudo podman pod rm -f qwen-ebook` when done.
