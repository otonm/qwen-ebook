<!-- generated-by: gsd-doc-writer -->
# Getting Started

This project is a self-hosted, single-user app: one Podman pod (a CPU backend
container plus a GPU TTS container) served over Tailscale, with no public
internet exposure and no separate auth layer. The fastest way to get a working
instance is the local bring-up script below.

## Prerequisites

- **Podman** — the only supported container runtime for this project (not
  Docker). `deploy/bootstrap-vm.sh` installs it via `apt-get` on Debian 13;
  on other distros, install it with your package manager.
- **An AMD GPU with a working ROCm driver.** Production targets an RX 9070 XT
  (`gfx1201`, RDNA4, officially ROCm 7.2+-supported, 16GB VRAM). Other AMD
  GPUs may work but are not verified — see `backend/GPU-ENABLEMENT.md` for
  the fallback-ladder investigation done on an unsupported `gfx1103`
  integrated GPU, including workaround flags (`HSA_OVERRIDE_GFX_VERSION`,
  `--security-opt label=disable`) that dev hosts outside the supported
  architecture list may need.
- **Tailscale**, if you intend to reach the app from another device — the
  app is designed to be exposed only via `tailscale serve`, never a public
  port. Not required for purely local (`127.0.0.1`) bring-up.
- **An OpenRouter API key** — required for the LLM step that casts
  characters and segments text. Get one at openrouter.ai and put it in
  `backend/.env` as `OPENROUTER_API_KEY=...` (this file is gitignored and
  read by both local `uv run` and the production Quadlet unit).
- **`uv`** and **Node.js/npm**, only if you want to run the backend or
  frontend directly on the host instead of through the container pod (see
  "Backend-only / frontend-only dev" below).
- `git`, for cloning the repo.

## Installation steps

```bash
git clone https://github.com/otonm/qwen-ebook
cd qwen-ebook
```

Add your OpenRouter key before first run:

```bash
echo "OPENROUTER_API_KEY=sk-or-..." > backend/.env
```

<!-- VERIFY: confirm the OpenRouter key format/prefix and that no other
variables must go in backend/.env for a fresh clone — the file is gitignored
so there is no committed .env.example to diff against. -->

## First run

The one-command path builds both container images (backend and TTS), starts
the two-container pod, and waits for the TTS service to report healthy:

```bash
bash deploy/run-local.sh
```

First run downloads the Qwen TTS model weights (multi-GB) into a named
Podman volume (`qwen-ebook-tts-hf-cache`) — this can take several minutes,
which is why the script's health-check timeout defaults to 900 seconds
(`HEALTH_TIMEOUT_SECONDS`). Every run after the first is fast, since the
volume persists the cached weights.

Once the script reports the TTS service healthy, the app is listening on
`http://127.0.0.1:8000` (use `127.0.0.1`, not `localhost` — see
`deploy/README.md` for why). Open it in a browser, or exercise the API
directly:

```bash
curl -F file=@your-book.txt http://127.0.0.1:8000/projects -o audiobook.wav
```

Tear the pod down with:

```bash
sudo podman pod rm -f qwen-ebook
```

## Backend-only / frontend-only dev

For iterating on backend code without rebuilding the container image, keep
the TTS container from the pod running (there is no mock/offline TTS mode —
synthesis always needs the real TTS container reachable at
`TTS_SERVICE_URL`) and run the FastAPI app directly:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

This needs a TTS service reachable at `TTS_SERVICE_URL` (defaults to
`http://localhost:8001` — see `docs/CONFIGURATION.md`).

For frontend UI iteration with hot reload, in a separate terminal:

```bash
cd frontend
npm run dev
```

The Vite dev server proxies API paths (`/projects`, `/characters`,
`/voices`, `/segments`, `/generation-status`) to `http://localhost:8000`
(`frontend/vite.config.ts`), so a backend must already be listening on port
8000 (either via `deploy/run-local.sh` or `uv run uvicorn` above).

## Common setup issues

- **Analysis requests fail with an OpenRouter error.** `OPENROUTER_API_KEY`
  is not validated at startup — the backend process starts fine without it,
  but every cast/segment analysis call will fail. Confirm the key is set in
  `backend/.env` and, for the container pod, that the Quadlet/`run-local.sh`
  path is actually reading that file.
- **First run seems to hang.** The TTS container is downloading multi-GB
  model weights on a cold cache. This is expected and can take several
  minutes; `run-local.sh`'s default 900s health timeout accounts for it.
  Subsequent runs are fast because the download is cached in the
  `qwen-ebook-tts-hf-cache` volume.
- **`curl http://localhost:8000/...` fails to connect but `127.0.0.1` works.**
  Known rootless-Podman `pasta` port-forwarding quirk on some hosts — use
  `127.0.0.1` explicitly (see `deploy/README.md`).
- **Real TTS synthesis crashes the GPU on non-`gfx1201` hardware.** Some AMD
  GPUs outside the officially supported ROCm architecture list can pass a
  basic GPU smoke test but still crash on real model inference. See
  `backend/GPU-ENABLEMENT.md` for the full investigation and accepted
  workaround/limitation on an unsupported dev GPU; this is not expected on
  the production RX 9070 XT target.

## Next steps

- `docs/CONFIGURATION.md` — full environment variable reference for the
  backend and TTS service.
- `ARCHITECTURE.md` — component breakdown, data flow, and design decisions.
- `deploy/README.md` — full deployment instructions, including the
  permanent Podman Quadlet (systemd-managed) production setup and its
  post-deploy verification checklist.
