<!-- generated-by: gsd-doc-writer -->
# Qwen Ebook Narrator

A self-hosted web app that turns long text (ebooks, articles) into a multi-voice narrated audiobook using Qwen TTS.

Give it a `.txt` or `.epub` file. An LLM (via OpenRouter) reads the text, auto-detects the cast of characters — narrator plus speaking characters, inferred from names, ages, and personalities in the text — and splits the text into narration/dialogue segments with per-segment voice instructions. You review and tweak everything in a spreadsheet-like table (reassign a narrator, edit voice instructions, fix a line of text), then generate and download a single joined audio file.

Built for personal use: converting text you own into audio for a commute or a workout.

## Why

Turning a book into a listenable audiobook usually means either paying for narration or listening to a single flat text-to-speech voice for ten hours. This app does the tedious part — figuring out who's talking and how they should sound — automatically, so you only have to fine-tune the result instead of building it from scratch.

## How it works, briefly

1. Upload a `.txt` or `.epub` file to create a project.
2. An LLM (OpenRouter, default model `x-ai/grok-4.3`) analyzes the text, proposes a cast of characters, and splits the text into narration/dialogue segments with suggested voice instructions.
3. You review and adjust the cast (rename, merge, edit descriptions, assign a preset voice or write free-text voice instructions) in a wizard.
4. You review and edit the segment table — narrator, voice instructions, and text are all editable per row.
5. Each row's audio is generated on demand via a self-hosted Qwen TTS model running on the local GPU. Generated audio is cached and only invalidated when a row's content actually changes — nothing regenerates automatically on edit.
6. Once you're happy with the segments, generate the remaining audio and download the final joined MP3 or WAV.

Projects (source text, cast, segment table, generated audio) are saved automatically and can be reopened later.

For a deeper look at the components, data flow, and design decisions, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Project structure

```
qwen-ebook/
├── backend/            FastAPI app — the single process that owns upload, LLM calls,
│                        EPUB parsing, the TTS queue, ffmpeg join, and SQLite persistence
│   ├── app/             API routes, chunking, EPUB parsing, LLM client, TTS client, DB models
│   ├── tts_service/     Self-hosted Qwen TTS inference server (runs in its own GPU container)
│   ├── tests/           Backend test suite
│   ├── Containerfile.backend   CPU-only backend image (no GPU deps)
│   └── Containerfile.tts       GPU-scoped TTS inference image (ROCm + Qwen TTS)
├── frontend/            React + TypeScript UI (the segment table, cast wizard, config panel)
│   └── src/
└── deploy/              Podman deployment: Quadlet unit files, pod manifest, bring-up scripts
    ├── qwen-ebook.pod
    ├── qwen-ebook-backend.container
    ├── qwen-ebook-tts.container
    ├── run-local.sh
    ├── bootstrap-vm.sh
    └── README.md
```

The backend serves the built frontend itself (`frontend/dist` is copied into the backend image at build time), so in production it's a single HTTP surface — no separate static host.

## Deployment

This app is deployed as two Podman containers in one pod: a CPU-only `backend` container (API, LLM calls, EPUB parsing, ffmpeg join, SQLite) and a GPU-scoped `tts` container (Qwen TTS inference, with `/dev/kfd`/`/dev/dri` passed through). It's designed to run on a VM with an AMD GPU (developed against an RX 9070 XT, 16GB VRAM) under ROCm, and exposed only over Tailscale — no public internet exposure, no separate auth layer.

Full deployment instructions — local bring-up, one-time VM bootstrap, and the permanent Podman Quadlet (systemd-managed) production setup — live in [deploy/README.md](deploy/README.md). In short:

**Local/dev bring-up** (builds both images, starts the pod):
```bash
bash deploy/run-local.sh
```

**Production VM**, once bootstrapped (`deploy/bootstrap-vm.sh`) and joined to your Tailscale tailnet, install the Quadlet units and start the pod:
```bash
sudo cp deploy/qwen-ebook.pod deploy/qwen-ebook-tts.container deploy/qwen-ebook-backend.container \
  /etc/containers/systemd/
sudo systemctl daemon-reload
sudo systemctl start qwen-ebook-backend.service
sudo tailscale serve --bg 8000   # one-time: exposes the app on your tailnet
```

The backend's writable state (SQLite DB, uploads, generated audio) lives on a persistent `/data` volume that survives container restarts and reboots. See `deploy/README.md` for the full post-deploy verification checklist and troubleshooting notes (GPU device isolation, rootful-vs-rootless Podman, restart/self-heal behavior).

### Required configuration

The backend needs an OpenRouter API key for text analysis:

- `OPENROUTER_API_KEY` — your OpenRouter API key
- `OPENROUTER_MODEL` — optional, overrides the default LLM model (`x-ai/grok-4.3`)

<!-- VERIFY: where OPENROUTER_API_KEY / OPENROUTER_MODEL should be set for the production Quadlet deployment (e.g. an env file referenced by deploy/qwen-ebook-backend.container) -->

## License

No license file is currently included in this repository — this is a personal, self-hosted project.
