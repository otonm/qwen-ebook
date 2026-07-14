"""Typed settings loaded from environment variables.

Kept dependency-light (plain os.environ.get + manual coercion) rather than
pulling in pydantic-settings, since this is a handful of scalar values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# backend/app/config.py -> parents[1] == backend/ -> parents[2] == repo root.
# Resolving UPLOAD_DIR/OUTPUT_DIR defaults as absolute paths anchored here
# (rather than the interface doc's literal relative string "backend/uploads")
# keeps them correct regardless of the process's cwd: tests and `uv run`
# invocations run with cwd=backend/, where a relative "backend/uploads"
# would double-nest into backend/backend/uploads.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_UPLOAD_DIR = str(_REPO_ROOT / "backend" / "uploads")
_DEFAULT_OUTPUT_DIR = str(_REPO_ROOT / "backend" / "output")
# Built React static assets (Containerfile.backend's frontend-build stage
# copies frontend/dist here). Only exists in the built image; local dev
# uses `npm run dev`'s own server instead, so a missing directory here is
# expected and handled by StaticFiles(check_dir=False) in main.py.
_DEFAULT_STATIC_DIR = str(_REPO_ROOT / "backend" / "static")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


# WR-04: the only two formats main.py/audio_join.py actually branch on
# ("wav" gets a stream copy + audio/wav; anything else is treated as mp3 —
# libmp3lame + audio/mpeg). Any other value (a typo, a future "flac") would
# silently produce a codec/container/Content-Type mismatch, so fail fast at
# settings-load time instead of at request time deep inside ffmpeg.
_ALLOWED_OUTPUT_FORMATS = {"wav", "mp3"}


_DEFAULT_DATABASE_URL = f"sqlite:///{_REPO_ROOT / 'backend' / 'projects.db'}"


@dataclass(frozen=True)
class Settings:
    TTS_BACKEND: str
    TTS_SERVICE_URL: str
    TTS_DEFAULT_SPEAKER: str
    CHUNK_TARGET_LEN: int
    MAX_UPLOAD_BYTES: int
    OUTPUT_FORMAT: str
    UPLOAD_DIR: str
    OUTPUT_DIR: str
    PREVIEW_DIR: str
    STATIC_DIR: str
    LLM_BACKEND: str
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str
    DATABASE_URL: str
    ANALYSIS_TOKEN_LIMIT: int
    LOG_LEVEL: str


def load_settings() -> Settings:
    output_format = os.environ.get("OUTPUT_FORMAT", "wav")
    if output_format not in _ALLOWED_OUTPUT_FORMATS:
        raise ValueError(
            f"OUTPUT_FORMAT={output_format!r} is not supported; "
            f"must be one of {sorted(_ALLOWED_OUTPUT_FORMATS)}"
        )

    output_dir = os.environ.get("OUTPUT_DIR", _DEFAULT_OUTPUT_DIR)

    return Settings(
        TTS_BACKEND=os.environ.get("TTS_BACKEND", "mock"),
        TTS_SERVICE_URL=os.environ.get("TTS_SERVICE_URL", "http://localhost:8001"),
        TTS_DEFAULT_SPEAKER=os.environ.get("TTS_DEFAULT_SPEAKER", ""),
        CHUNK_TARGET_LEN=_env_int("CHUNK_TARGET_LEN", 800),
        MAX_UPLOAD_BYTES=_env_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        OUTPUT_FORMAT=output_format,
        UPLOAD_DIR=os.environ.get("UPLOAD_DIR", _DEFAULT_UPLOAD_DIR),
        OUTPUT_DIR=output_dir,
        PREVIEW_DIR=os.environ.get("PREVIEW_DIR", f"{output_dir}/previews"),
        STATIC_DIR=os.environ.get("STATIC_DIR", _DEFAULT_STATIC_DIR),
        LLM_BACKEND=os.environ.get("LLM_BACKEND", "mock"),
        OPENROUTER_API_KEY=os.environ.get("OPENROUTER_API_KEY", ""),
        OPENROUTER_MODEL=os.environ.get("OPENROUTER_MODEL", "x-ai/grok-4.3"),
        DATABASE_URL=os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL),
        # content-loss fix round 2 (debug/llm-analysis-content-loss.md): D-05/
        # D-06 originally sized this off the model's ~1M-token CONTEXT window
        # (500K in, 500K of "headroom" for output). Real-key testing showed
        # the actual completion-token ceiling is unrelated to context size and
        # far smaller — a 110K-char single call hit finish_reason="length" at
        # ~68K completion tokens, and even well below that (30K chars) the
        # model sometimes self-truncates (finish_reason="stop" but only ~60%
        # coverage) on this long, repetitive verbatim-transcription task.
        # 6_000 tokens -> a 24_000-char per-call budget, comfortably under
        # both observed failure points, so most real documents now actually
        # get chunked instead of being sent as one call the model can't
        # reliably complete. Paired with the retry-then-fail-loud coverage
        # gate in analysis_worker.py.
        ANALYSIS_TOKEN_LIMIT=_env_int("ANALYSIS_TOKEN_LIMIT", 6_000),
        # Nothing configured logging.basicConfig() anywhere, so every
        # module's `logger = logging.getLogger(__name__)` call had no
        # handler to emit through and the root logger's default level
        # (WARNING) silently dropped INFO messages besides — CLAUDE.md's
        # "extensive debugging messages" convention was write-only. Set via
        # main.py at process startup, LOG_LEVEL="DEBUG" for maximum detail.
        LOG_LEVEL=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )


# Module-level singleton. Read once at import time; tests that need different
# env vars should reload the module, or use
# `monkeypatch.setattr(app.config, "settings", Settings(...))` to swap the
# whole singleton — individual fields can't be patched since `Settings` is
# frozen (IN-01).
settings = load_settings()
