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
