# ============================================================
# core/script.py — Script file parsing with per-chunk overrides
# ============================================================

import re
from pathlib import Path

# Regex for inline override tags: [voice:xyz] [emotion:some text here]
_TAG_RE = re.compile(r"\[(voice|emotion):([^\]]+)\]", re.IGNORECASE)


def parse_chunk_overrides(line: str) -> dict:
    """Extract [voice:X], [emotion:X], or shorthand [X] tags from a line.

    Returns a dict with keys:
        text     — the cleaned text with tags removed
        voice    — override voice or None
        emotion  — override emotion or None
    """
    overrides = {"voice": None, "emotion": None}
    emotions = []

    def _extract(match):
        content = match.group(1).strip()
        if ":" in content:
            parts = content.split(":", 1)
            key = parts[0].strip().lower()
            val = parts[1].strip()
            if key == "voice":
                overrides["voice"] = val
            elif key == "emotion":
                emotions.append(val)
        else:
            # Shorthand emotion direction, e.g. [Bitter laugh]
            emotions.append(content)
        return ""

    # Replace all [...] blocks
    clean = re.sub(r"\[([^\]]+)\]", _extract, line).strip()
    
    # Collapse multiple spaces left by removed tags
    clean = re.sub(r"\s{2,}", " ", clean)

    if emotions:
        overrides["emotion"] = ", ".join(emotions)

    return {"text": clean, **overrides}


def parse_script(filepath: str) -> list[dict]:
    """Read a script file and return chunks with optional overrides.

    Each non-empty line is one chunk. Blank lines are ignored.
    Lines can contain optional override tags:
        [voice:serena] [emotion:Whispered, fearful] I heard footsteps.

    Returns a list of dicts:
        [{"text": "...", "voice": None, "emotion": None}, ...]
    """
    text = Path(filepath).read_text(encoding="utf-8")
    chunks = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        chunk = parse_chunk_overrides(stripped)
        if chunk["text"]:  # skip lines that were only tags
            chunks.append(chunk)
    return chunks
