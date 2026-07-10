"""chars/4 token estimate — no tokenizer dependency.

No official Grok tokenizer is public; chars/4 is an honest, wide-margin
heuristic (~10-28% error per RESEARCH.md Pitfall 3), absorbed by D-06's
~50%-of-context ANALYSIS_TOKEN_LIMIT safety margin. Do not treat the
return value as exact.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    return len(text) // 4
