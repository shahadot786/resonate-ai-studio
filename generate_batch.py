# ============================================================
# generate_batch.py — Batch generate from script.txt → stitched WAV
# ============================================================

import os
import time

from config import (
    CHUNKS_DIR,
    EMOTION,
    EXPORT_MP3,
    MODEL_PATH,
    NORMALIZE_AUDIO,
    OUTPUT_FILE,
    REF_AUDIO,
    REF_TEXT,
    SAMPLE_RATE,
    SCRIPT_FILE,
    SILENCE_PADDING,
    SPEED,
    VOICE,
)
from core.audio import generate_chunk, get_duration, stitch_wavs
from core.model import load_tts_model
from core.script import parse_script


def main():
    # Validate required files
    for path in [SCRIPT_FILE, REF_AUDIO]:
        if not os.path.exists(path):
            print(f"Missing: {path}")
            return

    os.makedirs(CHUNKS_DIR, exist_ok=True)
    os.makedirs("outputs", exist_ok=True)

    # Parse script — each non-empty line is one chunk (with optional overrides)
    chunks = parse_script(SCRIPT_FILE)
    total = len(chunks)

    print("=" * 50)
    print("  Narrator — Batch Generator")
    print("=" * 50)
    print(f"  Script:     {SCRIPT_FILE}")
    print(f"  Voice:      {VOICE}")
    print(f"  Chunks:     {total}")
    print(f"  Silence:    {SILENCE_PADDING}s between chunks")
    print(f"  Normalize:  {'yes' if NORMALIZE_AUDIO else 'no'}")
    print(f"  MP3 export: {'yes' if EXPORT_MP3 else 'no'}")
    print("=" * 50)

    model = load_tts_model(MODEL_PATH)

    made = []
    start = time.time()

    for i, chunk in enumerate(chunks):
        chunk_path = os.path.join(CHUNKS_DIR, f"chunk_{i:04d}.wav")

        # Resume: skip already-generated chunks
        if os.path.exists(chunk_path):
            print(f"  [{i + 1}/{total}] Skipping (exists) → chunk_{i:04d}.wav")
            made.append(chunk_path)
            continue

        preview = chunk["text"][:60].replace("\n", " ")
        voice = chunk["voice"] or VOICE
        emotion = chunk["emotion"] or EMOTION

        if chunk["voice"]:
            print(f"  [{i + 1}/{total}] [voice:{voice}] \"{preview}...\"")
        else:
            print(f"  [{i + 1}/{total}] \"{preview}...\"")

        ok = generate_chunk(
            model,
            chunk["text"],
            chunk_path,
            voice=voice,
            ref_audio=REF_AUDIO,
            ref_text=REF_TEXT,
            instruct=emotion,
            speed=SPEED,
        )

        if ok:
            made.append(chunk_path)
            print(f"           ✓ chunk_{i:04d}.wav")

    # Stitch
    print("\nStitching chunks...")
    if made and stitch_wavs(
        made,
        OUTPUT_FILE,
        silence_padding=SILENCE_PADDING,
        sample_rate=SAMPLE_RATE,
        normalize=NORMALIZE_AUDIO,
        export_mp3=EXPORT_MP3,
    ):
        elapsed = time.time() - start
        duration = get_duration(OUTPUT_FILE)
        print("\n" + "=" * 50)
        print("  ✓ COMPLETE")
        print("=" * 50)
        print(f"  Output:   {OUTPUT_FILE}")
        if EXPORT_MP3:
            print(f"  MP3:      {OUTPUT_FILE.replace('.wav', '.mp3')}")
        print(f"  Duration: {duration}")
        print(f"  Time:     {int(elapsed // 60)}m {int(elapsed % 60)}s")
        print(f"\n  Play: afplay {OUTPUT_FILE}")
        print("=" * 50)
    else:
        print("Stitch failed or no chunks generated.")
        print(f"Individual chunks saved in: {CHUNKS_DIR}/")


if __name__ == "__main__":
    main()
