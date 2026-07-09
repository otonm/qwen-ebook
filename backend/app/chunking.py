"""Greedy paragraph-merge chunker (D-01/D-02).

Splits text on blank-line paragraph boundaries and greedily merges
consecutive paragraphs up to `target_len` characters. No NLP library
(stdlib regex only, per D-01). A single paragraph that alone exceeds
`target_len` is further split at sentence boundaries and greedily
re-merged, so no chunk is pathologically long.
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_oversized_paragraph(paragraph: str, target_len: int) -> list[str]:
    """Split a single paragraph longer than target_len at sentence boundaries,
    greedily re-merging sentences back up to target_len."""
    sentences = [s for s in _SENTENCE_SPLIT.split(paragraph) if s]
    if len(sentences) <= 1:
        # No sentence boundaries found (e.g. one giant run-on sentence) —
        # nothing safe to split on without risking mid-word breaks; return
        # the paragraph as-is rather than fabricating a boundary.
        return [paragraph]

    pieces: list[str] = []
    buf = ""
    for sentence in sentences:
        if buf and len(buf) + len(sentence) + 1 > target_len:
            pieces.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}" if buf else sentence
    if buf:
        pieces.append(buf)
    return pieces


def chunk_paragraphs(text: str, target_len: int = 800) -> list[str]:
    """Split `text` into chunks of ~target_len chars on paragraph boundaries.

    - Empty or whitespace-only input returns [].
    - Consecutive short paragraphs are merged until adding the next one
      would exceed target_len.
    - A single paragraph longer than target_len is split at sentence
      boundaries and greedily re-merged so each resulting chunk stays
      <= target_len wherever a sentence boundary makes that possible.
    """
    stripped = text.strip()
    if not stripped:
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(stripped) if p.strip()]

    chunks: list[str] = []
    buf = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_len:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_split_oversized_paragraph(paragraph, target_len))
            continue

        if buf and len(buf) + len(paragraph) + 2 > target_len:
            chunks.append(buf)
            buf = paragraph
        else:
            buf = f"{buf}\n\n{paragraph}" if buf else paragraph

    if buf:
        chunks.append(buf)

    return chunks
