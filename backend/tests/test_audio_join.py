"""Unit tests for app.audio_join.join_wavs' 3-way CODEC_TABLE dispatch.

CFG-06: join_wavs must produce a real flac/mp3/ogg(opus) container per the
selected format — verified against ffprobe's own format_name, not just "the
process exited 0" — and reject any format outside CODEC_TABLE (no silent
mp3 fallback for "wav" or other unknown values).
"""

from __future__ import annotations

import subprocess

import pytest

from app.audio_join import join_wavs


def _make_tone_wav(path: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            path,
        ],
        capture_output=True,
        check=True,
    )


def _ffprobe_format_name(path: str) -> str:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=format_name",
            "-of",
            "default=nk=1:nw=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def two_wavs(tmp_path):
    w1 = str(tmp_path / "a.wav")
    w2 = str(tmp_path / "b.wav")
    _make_tone_wav(w1)
    _make_tone_wav(w2)
    return [w1, w2]


@pytest.mark.parametrize(
    "fmt,expected_format_name",
    [
        ("flac", "flac"),
        ("mp3", "mp3"),
        ("opus", "ogg"),
    ],
)
def test_join_wavs_produces_correct_container(tmp_path, two_wavs, fmt, expected_format_name):
    out_path = str(tmp_path / f"out.{fmt}")
    join_wavs(two_wavs, out_path, fmt)
    assert _ffprobe_format_name(out_path) == expected_format_name


def test_join_wavs_rejects_unknown_format(tmp_path, two_wavs):
    out_path = str(tmp_path / "out.wav")
    with pytest.raises(ValueError, match="unsupported output format"):
        join_wavs(two_wavs, out_path, "wav")
