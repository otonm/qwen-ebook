"""Unit tests for app.config.load_settings().

WR-04: OUTPUT_FORMAT must be validated against the only two formats
main.py/audio_join.py actually know how to handle ("wav"/"mp3") — an
unrecognized value should fail fast at settings-load time, not produce a
silent codec/container/Content-Type mismatch at request time.
"""

from __future__ import annotations

import pytest

from app.config import load_settings


def test_load_settings_accepts_wav_and_mp3(monkeypatch):
    monkeypatch.setenv("OUTPUT_FORMAT", "wav")
    assert load_settings().OUTPUT_FORMAT == "wav"

    monkeypatch.setenv("OUTPUT_FORMAT", "mp3")
    assert load_settings().OUTPUT_FORMAT == "mp3"


def test_load_settings_rejects_unsupported_output_format(monkeypatch):
    monkeypatch.setenv("OUTPUT_FORMAT", "flac")

    with pytest.raises(ValueError, match="OUTPUT_FORMAT"):
        load_settings()


def test_load_settings_honors_persistent_data_volume_overrides(monkeypatch):
    """T-03-20: the Quadlet unit/run-local.sh point DATABASE_URL/UPLOAD_DIR/
    OUTPUT_DIR at the persistent /data volume — prove those env overrides are
    actually honored and that PREVIEW_DIR derives from the overridden
    OUTPUT_DIR, not the image-baked default.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite:////data/projects.db")
    monkeypatch.setenv("UPLOAD_DIR", "/data/uploads")
    monkeypatch.setenv("OUTPUT_DIR", "/data/output")

    settings = load_settings()

    assert settings.DATABASE_URL == "sqlite:////data/projects.db"
    assert settings.UPLOAD_DIR == "/data/uploads"
    assert settings.OUTPUT_DIR == "/data/output"
    assert settings.PREVIEW_DIR == "/data/output/previews"
