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
    LLM_BACKEND: str
    XAI_API_KEY: str
    GROK_MODEL: str
    DATABASE_URL: str
    ANALYSIS_TOKEN_LIMIT: int


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
        LLM_BACKEND=os.environ.get("LLM_BACKEND", "mock"),
        XAI_API_KEY=os.environ.get("XAI_API_KEY", ""),
        GROK_MODEL=os.environ.get("GROK_MODEL", "grok-4.3"),
        DATABASE_URL=os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL),
        ANALYSIS_TOKEN_LIMIT=_env_int("ANALYSIS_TOKEN_LIMIT", 500_000),
    )


# Module-level singleton. Read once at import time; tests that need different
# env vars should reload the module, or use
# `monkeypatch.setattr(app.config, "settings", Settings(...))` to swap the
# whole singleton — individual fields can't be patched since `Settings` is
# frozen (IN-01).
settings = load_settings()
