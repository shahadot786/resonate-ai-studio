# ============================================================
# core/script.py — Script file parsing
# ============================================================

from pathlib import Path


def parse_script(filepath: str) -> list[str]:
    """Read a script file and return chunks.

    Each non-empty line is treated as one chunk.
    Blank lines are ignored.
    """
    text = Path(filepath).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]
