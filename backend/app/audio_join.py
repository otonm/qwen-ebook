"""Join per-chunk WAV files into one output audio file via ffmpeg's concat
demuxer, invoked through subprocess.run with an explicit argument list.

Security note (RESEARCH.md Security Domain, T-01-03): never invoke a shell
here (no shell mode, no string-interpolated commands), even though the
inputs are filenames this app generates itself rather than raw user text.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def join_wavs(wav_paths: list[str], out_path: str, fmt: str = "wav") -> str:
    """Concatenate `wav_paths` (in order) into a single file at `out_path`.

    fmt="wav" does a stream copy (-c copy); fmt="mp3" re-encodes to MP3
    (-c:a libmp3lame), since a copy can't change container/codec.
    Returns out_path on success; raises RuntimeError on ffmpeg failure.
    """
    if not wav_paths:
        raise ValueError("wav_paths must not be empty")

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
        codec_args = ["-c", "copy"] if fmt == "wav" else ["-c:a", "libmp3lame"]
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
