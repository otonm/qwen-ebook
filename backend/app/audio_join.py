"""Join per-chunk WAV files into one output audio file via ffmpeg's concat
demuxer, invoked through subprocess.run with an explicit argument list.

Security note (RESEARCH.md Security Domain, T-01-03): never invoke a shell
here (no shell mode, no string-interpolated commands), even though the
inputs are filenames this app generates itself rather than raw user text.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Phase 6 (CFG-06/D-09/D-10): the three supported final-output formats and
# the exact ffmpeg codec args verified present in the deploy build
# (06-RESEARCH.md). No catch-all fallback — an unlisted fmt raises rather
# than silently landing on mp3.
CODEC_TABLE: dict[str, dict[str, object]] = {
    "flac": {
        "codec_args": ["-c:a", "flac", "-compression_level", "8"],
        "content_type": "audio/flac",
    },
    "mp3": {
        "codec_args": ["-c:a", "libmp3lame"],
        "content_type": "audio/mpeg",
    },
    "opus": {
        # ffmpeg's opus encoder always muxes into an Ogg container (there is
        # no bare .opus muxer) — content_type is audio/ogg, not audio/opus.
        "codec_args": ["-c:a", "libopus", "-b:a", "48k", "-vbr", "on", "-application", "voip"],
        "content_type": "audio/ogg",
    },
}


def join_wavs(wav_paths: list[str], out_path: str, fmt: str = "mp3") -> str:
    """Concatenate `wav_paths` (in order) into a single file at `out_path`,
    re-encoded per `fmt` using CODEC_TABLE's codec args.

    Raises ValueError if `fmt` isn't a CODEC_TABLE key (flac/mp3/opus).
    Returns out_path on success; raises RuntimeError on ffmpeg failure.
    """
    if not wav_paths:
        raise ValueError("wav_paths must not be empty")
    if fmt not in CODEC_TABLE:
        raise ValueError(f"unsupported output format: {fmt!r}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as list_file:
        for wav_path in wav_paths:
            abs_path = str(Path(wav_path).resolve())
            escaped = abs_path.replace("'", "'\\''")
            list_file.write(f"file '{escaped}'\n")
        list_file_path = list_file.name

    try:
        codec_args = CODEC_TABLE[fmt]["codec_args"]
        logger.debug(f"join_wavs: joining {len(wav_paths)} wavs into {out_path} as {fmt}")
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file_path,
                *codec_args,
                "-f",
                fmt,
                out_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed (exit {result.returncode}): {result.stderr}")
    finally:
        Path(list_file_path).unlink(missing_ok=True)

    return out_path
