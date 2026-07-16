<!-- generated-by: gsd-doc-writer -->
# Development

This project has two independently-versioned parts — a Python/FastAPI `backend`
(including the GPU-isolated `tts_service`) and a React/TypeScript `frontend` —
plus a `deploy/` directory of Podman Quadlet units and bring-up scripts. There
is no unit test suite; verification is done by running the real pod (backend +
TTS container) via `deploy/run-local.sh` and exercising the app directly. See
[README.md](../README.md) for the project overview and
[ARCHITECTURE.md](../ARCHITECTURE.md) for how the pieces fit together.

## Local setup

### Full stack (backend + TTS + frontend, matches production)

The most reliable way to run the whole app locally is the same script used
for production bring-up:

```bash
bash deploy/run-local.sh
```

This builds both container images (`backend/Containerfile.backend`,
`backend/Containerfile.tts`), starts a two-container Podman pod, waits for the
TTS service's `/healthz` to report ready, and serves the app (backend +
built frontend) on `http://127.0.0.1:8000`. It requires Podman and a GPU
capable of running Qwen TTS under ROCm — see
[backend/GPU-ENABLEMENT.md](../backend/GPU-ENABLEMENT.md) for GPU-passthrough
troubleshooting on non-production hardware.

### Backend only (API iteration, no GPU)

For iterating on API routes, EPUB parsing, chunking, or LLM analysis logic
without rebuilding containers:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Configuration is read from environment variables (see
[docs/CONFIGURATION.md](CONFIGURATION.md)); at minimum set `OPENROUTER_API_KEY`
for LLM analysis to work. `backend/.env` is the local `EnvironmentFile` also
used in production (`deploy/qwen-ebook-backend.container`). Requests that hit
the TTS service (`TTS_SERVICE_URL`, default `http://localhost:8001`) will fail
unless a TTS container is also running — there is no mock TTS backend in this
codebase.

### Frontend only (UI iteration)

```bash
cd frontend
npm install
npm run dev
```

Vite's dev server proxies `/projects`, `/characters`, `/voices`, `/segments`,
and `/generation-status` to `http://localhost:8000` (see
`frontend/vite.config.ts`), so a backend must already be running on port 8000
(either the full pod or `uv run uvicorn` above) for the UI to have data to
render.

## Build commands

### Backend (`backend/`, via `uv`)

| Command | Description |
|---|---|
| `uv sync` | Install/update the backend's locked dependencies (`pyproject.toml` + `uv.lock`). |
| `uv run uvicorn app.main:app --reload --port 8000` | Run the FastAPI app with autoreload for local development. |
| `uv run ruff check .` | Lint (required gate — see Code style below). |

### Frontend (`frontend/`, via `npm`)

| Command | Description |
|---|---|
| `npm run dev` | Start the Vite dev server with hot reload. |
| `npm run build` | Type-check (`tsc -b`) then produce a production build in `frontend/dist`. |
| `npm run preview` | Serve the production build locally. |
| `npm run lint` | Run ESLint over the project. |
| `npm run format` | Format all `.ts`/`.tsx` files with Prettier. |
| `npm run typecheck` | Run `tsc --noEmit` only. |

### Containers

| Command | Description |
|---|---|
| `podman build -f backend/Containerfile.backend -t localhost/qwen-ebook-backend:dev .` (repo root context) | Build the CPU-only backend image, which also builds and embeds the frontend (`frontend/dist`) as static assets. |
| `podman build -f backend/Containerfile.tts -t localhost/qwen-ebook-tts:dev backend` | Build the GPU-scoped TTS inference image. |
| `bash deploy/run-local.sh` | Build both images and bring up the full pod (wraps the two commands above). |

## Code style

- **Backend (Python):** [ruff](https://docs.astral.sh/ruff/) is the linter and
  formatter, configured in `backend/pyproject.toml` (rule sets `E`, `F`, `I`,
  `UP`, `B`; `line-length = 100`; `target-version = "py312"`). Run
  `cd backend && uv run ruff check .` before committing — this is the
  project's required lint gate (see `CLAUDE.md`). Apply `--fix` for
  auto-fixable issues, then resolve the rest manually. `# noqa` suppressions
  are discouraged outside test files and must carry a comment explaining why
  they're unavoidable.
- **Backend conventions:** use the `logging` module (never `print()`), and use
  f-strings for all string interpolation including log calls.
- **Frontend (TypeScript/React):** [ESLint](https://eslint.org/) is configured
  in `frontend/eslint.config.js` (`@eslint/js` recommended rules,
  `typescript-eslint` recommended, `eslint-plugin-react-hooks`,
  `eslint-plugin-react-refresh`). Run `npm run lint` in `frontend/`.
  [Prettier](https://prettier.io/) is configured in `frontend/.prettierrc`
  (no semicolons, double quotes off/`singleQuote: false`, 2-space tabs,
  80-char print width, `prettier-plugin-tailwindcss` for class sorting). Run
  `npm run format` in `frontend/`. `npm run typecheck` runs `tsc --noEmit`
  independently of the build.
- Neither lint step currently runs in CI — there is no `.github/workflows/`
  directory in this repository. Run both gates locally before committing.

## Branch conventions

No branch naming convention is documented in this repository, and development
so far has happened directly on `master` (no other local or remote branches
exist). Commit messages follow a loose Conventional Commits style (`feat:`,
`fix:`, `chore:`, `refactor:`, `docs:` prefixes, per `git log`).

## PR process

There is no `.github/PULL_REQUEST_TEMPLATE.md` or CI workflow in this
repository, so there is no enforced PR process. If opening a pull request:

- Run the full lint gate first: `cd backend && uv run ruff check .` and
  `cd frontend && npm run lint && npm run typecheck`.
- Since there is no automated test suite, manually verify the change against
  the real pod (`bash deploy/run-local.sh`) before requesting review —
  see the note in [README.md](../README.md#project-structure).
- Keep commit messages in the existing Conventional-Commits-style format
  (`type: short description`).
