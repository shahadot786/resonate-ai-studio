# ============================================================
# generate_single.py — Generate a single audio clip
# ============================================================

import os

from config import EMOTION, MODEL_PATH, REF_AUDIO, REF_TEXT, SPEED, VOICE
from core.audio import generate_chunk
from core.model import load_tts_model


# ── Edit this text to generate a single clip ─────────────────

TEXT = """\
She had been my best friend for twelve years.
I trusted her with everything — my secrets, my dreams, my darkest fears.
So when I found out what she had done, it didn't just break my heart.
It shattered every version of reality I had ever believed in.\
"""

OUTPUT = "outputs/test_output.wav"

# ──────────────────────────────────────────────────────────────


def main():
    model = load_tts_model(MODEL_PATH)
    os.makedirs("outputs", exist_ok=True)

    print(f"\nGenerating → {OUTPUT}\n")

    ok = generate_chunk(
        model,
        TEXT.strip(),
        OUTPUT,
        voice=VOICE,
        ref_audio=REF_AUDIO,
        ref_text=REF_TEXT,
        instruct=EMOTION,
        speed=SPEED,
    )

    if ok:
        print(f"\n✓ Done: {OUTPUT}")
        print(f"  Play: afplay {OUTPUT}")
    else:
        print("\n✗ Generation failed.")


if __name__ == "__main__":
    main()