"""GPU-scoped Qwen3-TTS inference service.

This package is isolated from the main `backend/app` (CPU-only) package.
It is the only part of the codebase that imports `torch`/`qwen_tts` and is
built into its own Podman image (see `backend/Containerfile.tts`) with
`/dev/kfd` + `/dev/dri` GPU device passthrough.
"""
