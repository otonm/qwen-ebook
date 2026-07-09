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


def load_settings() -> Settings:
    return Settings(
        TTS_BACKEND=os.environ.get("TTS_BACKEND", "mock"),
        TTS_SERVICE_URL=os.environ.get("TTS_SERVICE_URL", "http://localhost:8001"),
        TTS_DEFAULT_SPEAKER=os.environ.get("TTS_DEFAULT_SPEAKER", ""),
        CHUNK_TARGET_LEN=_env_int("CHUNK_TARGET_LEN", 800),
        MAX_UPLOAD_BYTES=_env_int("MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        OUTPUT_FORMAT=os.environ.get("OUTPUT_FORMAT", "wav"),
        UPLOAD_DIR=os.environ.get("UPLOAD_DIR", _DEFAULT_UPLOAD_DIR),
        OUTPUT_DIR=os.environ.get("OUTPUT_DIR", _DEFAULT_OUTPUT_DIR),
    )


# Module-level singleton. Read once at import time; tests that need different
# env vars should reload the module or monkeypatch `settings` attributes.
settings = load_settings()
