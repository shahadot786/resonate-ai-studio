# ============================================================
# test_voices.py — Compare all available voices
# ============================================================

import os
import shutil

from config import EMOTION, MODEL_PATH, REF_AUDIO, REF_TEXT, SPEED, VOICES
from core.audio import generate_chunk
from core.model import load_tts_model


TEXT = """\
I never imagined the person I trusted most
would become the reason I lost everything.
Looking back now, every warning sign was there.\
"""

OUTPUT_ROOT = "voice_tests"


def main():
    model = load_tts_model(MODEL_PATH)

    if os.path.exists(OUTPUT_ROOT):
        shutil.rmtree(OUTPUT_ROOT)
    os.makedirs(OUTPUT_ROOT, exist_ok=True)

    total = len(VOICES)

    for i, voice in enumerate(VOICES):
        print("-" * 50)
        print(f"[{i + 1}/{total}] Testing voice: {voice}")
        print("-" * 50)

        output_path = os.path.join(OUTPUT_ROOT, f"{voice}.wav")

        ok = generate_chunk(
            model,
            TEXT.strip(),
            output_path,
            voice=voice,
            ref_audio=REF_AUDIO,
            ref_text=REF_TEXT,
            instruct=EMOTION,
            speed=SPEED,
        )

        if ok:
            print(f"  ✓ {voice}.wav")
        else:
            print(f"  ✗ Failed: {voice}")

        print()

    print("=" * 50)
    print("  ✓ Finished!")
    print("=" * 50)
    print(f"\n  Results in: {OUTPUT_ROOT}/")
    for voice in VOICES:
        print(f"    ├── {voice}.wav")


if __name__ == "__main__":
    main()