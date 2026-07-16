<!-- generated-by: gsd-doc-writer -->
# Configuration

All backend configuration is read from environment variables. There is no config file format
beyond environment variables — the backend loads them once at import time into a frozen
`Settings` dataclass (`backend/app/config.py`), and the TTS inference service reads its one
setting directly via `os.environ.get` (`backend/tts_service/server.py`).

## Environment variables

### Backend (`backend/app/config.py`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `TTS_SERVICE_URL` | Optional | `http://localhost:8001` | Base URL the backend calls to reach the internal TTS inference service. |
| `TTS_DEFAULT_SPEAKER` | Optional | `""` (empty string) | Fallback speaker/preset name used when a segment has no voice assigned. |
| `CHUNK_TARGET_LEN` | Optional | `800` | Target character length per text chunk sent to the TTS service. |
| `MAX_UPLOAD_BYTES` | Optional | `10485760` (10 MiB) | Maximum accepted size, in bytes, for an uploaded source file. |
| `UPLOAD_DIR` | Optional | `backend/uploads` (absolute, repo-root-anchored) | Directory where uploaded source files are written. |
| `OUTPUT_DIR` | Optional | `backend/output` (absolute, repo-root-anchored) | Directory where generated segment audio and joined audiobooks are written. |
| `PREVIEW_DIR` | Optional | `{OUTPUT_DIR}/previews` | Directory for per-segment voice preview clips. Defaults relative to the resolved `OUTPUT_DIR`, not a fixed path. |
| `STATIC_DIR` | Optional | `backend/static` (absolute, repo-root-anchored) | Directory the backend serves the built React frontend from. Only populated in the built container image (`Containerfile.backend`'s frontend-build stage); missing locally is expected — `StaticFiles(check_dir=False)` in `main.py` tolerates that. |
| `OPENROUTER_API_KEY` | **Required** (for LLM analysis) | `""` (empty string) | API key for OpenRouter, used for LLM-based cast/segment analysis. The app starts without it, but any analysis request will fail without a real key. |
| `OPENROUTER_MODEL` | Optional | `x-ai/grok-4.3` | OpenRouter model identifier used for cast and segment analysis. Swappable to any model OpenRouter routes to. |
| `DATABASE_URL` | Optional | `sqlite:///{repo_root}/backend/projects.db` | SQLAlchemy/SQLModel connection string for the single SQLite database. |
| `ANALYSIS_TOKEN_LIMIT` | Optional | `6000` | Per-call completion-token budget for LLM analysis chunking (~24,000 chars per call). Tuned against observed OpenRouter truncation behavior — see the inline comment in `config.py` for the history. |
| `LOG_LEVEL` | Optional | `INFO` | Root logging level, passed to `logging.basicConfig()` in `main.py`. Uppercased automatically. `httpx`/`httpcore` loggers are force-kept at `WARNING` regardless of this value, to avoid leaking `OPENROUTER_API_KEY` via request-header debug logs. |

### TTS service (`backend/tts_service/server.py`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GPU_KEEPALIVE_INTERVAL` | Optional | `15` (seconds) | Interval for a periodic keepalive matmul that prevents AMD ROCm's power management from downclocking an idle GPU (avoids latency spikes on the first request after a gap). |

### Dev-host GPU workarounds (`deploy/run-local.sh` only)

These two variables are read by `deploy/run-local.sh`, not by any Python process. They exist to
work around a gfx1103 development host; the gfx1201 production VM needs neither (see
`backend/GPU-ENABLEMENT.md`).

| Variable | Required | Default | Description |
|---|---|---|---|
| `GPU_SECURITY_OPT` | Optional | `""` (empty) | If set, passed as `--security-opt` to the TTS container's `podman run` (e.g. `label=disable`). |
| `HSA_OVERRIDE_GFX_VERSION` | Optional | `""` (empty) | If set, exported into the TTS container as `HSA_OVERRIDE_GFX_VERSION` (e.g. `11.0.0`) to force ROCm to treat the GPU as a different, supported gfx version. |


## Config file format

No config file (JSON/YAML/TOML) is used. All runtime configuration is environment variables only.

## Required vs optional settings

Nothing currently throws on startup if a required variable is missing — `Settings` fields all
have defaults (empty string or a sensible fallback), so the process always starts. In practice:

- `OPENROUTER_API_KEY` is functionally required: with the default empty string, any LLM
  cast/segment analysis call will fail against OpenRouter's API. It has no startup-time validation.
- Every other variable has a working default suitable for local development.

## Defaults

Defaults are defined directly in `load_settings()` in `backend/app/config.py`:

- Path-based defaults (`UPLOAD_DIR`, `OUTPUT_DIR`, `STATIC_DIR`, `DATABASE_URL`) are anchored to
  the repository root (`Path(__file__).resolve().parents[2]`) so they resolve correctly
  regardless of the process's working directory (both `uv run` from `backend/` and containerized
  invocations).
- `PREVIEW_DIR` derives its default from the *resolved* `OUTPUT_DIR` value (`f"{output_dir}/previews"`),
  not from a separate hardcoded path — so overriding `OUTPUT_DIR` alone shifts `PREVIEW_DIR` too.

## Per-environment overrides

There are no `.env.development` / `.env.production` files or `NODE_ENV`-style branching in
`config.py`. Each deployment mode instead sets environment variables directly at the process or
container level:

### Local (`uv run`)

Run the backend directly from `backend/` with `uv run`. Variables not set fall back to the
`backend/`-relative defaults above (uploads/output/db under `backend/`, TTS service assumed at
`http://localhost:8001`). `backend/.env` (gitignored, per `backend/.gitignore`) is the
conventional place to put `OPENROUTER_API_KEY` for this mode — it is not auto-loaded by
`config.py` itself, so it must be sourced or exported into the shell (or loaded by whatever
runs `uv run`) before starting the process.

### `deploy/run-local.sh` (two-container Podman pod, dev)

`run-local.sh` builds both images and starts a two-container pod (`qwen-ebook`), passing
overrides via `podman run -e`:

- Backend container: `TTS_SERVICE_URL=http://localhost:8001`, `DATABASE_URL=sqlite:////data/projects.db`,
  `UPLOAD_DIR=/data/uploads`, `OUTPUT_DIR=/data/output`, with `/data` backed by the named volume
  `qwen-ebook-data` (script-configurable via `DATA_VOLUME` env var) so state survives pod
  teardown/recreate.
- TTS container: no app-level env vars set by the script itself; GPU device passthrough
  (`--device /dev/kfd --device /dev/dri`, `--user 0:0`) is unconditional. `GPU_SECURITY_OPT` and
  `HSA_OVERRIDE_GFX_VERSION` are opt-in via shell environment variables for gfx1103 dev hosts only.
- Script-level tunables (bash variables, not passed into the containers): `POD_NAME`,
  `BACKEND_HOST_PORT` (default `8000`, only the backend port is published to the host — TTS port
  8001 stays pod-internal), `HEALTH_TIMEOUT_SECONDS` (default `900`), `HF_CACHE_VOLUME` (default
  `qwen-ebook-tts-hf-cache`).

### Quadlet production (`deploy/qwen-ebook-backend.container`, `deploy/qwen-ebook-tts.container`)

Systemd-managed production units, translating the same pod topology declaratively:

- Backend unit sets `Environment=TTS_SERVICE_URL=http://localhost:8001`,
  `Environment=DATABASE_URL=sqlite:////data/projects.db`, `Environment=UPLOAD_DIR=/data/uploads`,
  `Environment=OUTPUT_DIR=/data/output`, `Environment=LOG_LEVEL=DEBUG`, and mounts the persistent
  volume `qwen-ebook-data` at `/data` (not `/backend`, so it doesn't shadow the image-baked
  frontend bundle at `/backend/static`).
- Backend unit also declares `EnvironmentFile=/home/oton/qwen-ebook/backend/.env` (absolute path,
  since the unit runs as a root system service, not a user session) — this is where
  `OPENROUTER_API_KEY` is sourced from in production, kept in the same single gitignored file
  used for local dev rather than duplicated into the unit file.
  <!-- VERIFY: /home/oton/qwen-ebook/backend/.env is a host-specific absolute path baked into the committed unit file — confirm this matches the actual production VM's deployment path before relying on it. -->
- TTS unit sets no application env vars; it grants GPU device access (`AddDevice=/dev/kfd`,
  `AddDevice=/dev/dri`, `User=0`/`Group=0`) and mounts the Hugging Face cache volume
  `qwen-ebook-tts-hf-cache` to persist the multi-GB model download across restarts. The
  gfx1103-only `GPU_SECURITY_OPT`/`HSA_OVERRIDE_GFX_VERSION` workarounds are intentionally omitted
  here, since the production gfx1201 VM does not need them.
- Both units require `qwen-ebook-pod.service` (the shared pod) and restart `on-failure`.

<!-- VERIFY: exact `podman --version` on the production VM — the unit files carry a note that the Quadlet key set has shifted across Podman 4.4-5.x and should be reconfirmed over Tailscale SSH before relying on this syntax. -->
