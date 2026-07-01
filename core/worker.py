#!/usr/bin/env python3
# ============================================================
# core/worker.py — Generation worker (runs as a subprocess)
#
# MLX requires GPU operations on the main thread of a process.
# The FastAPI server spawns this script as a subprocess so MLX
# gets its own process with full GPU access.
#
# Usage: python3 core/worker.py <config.json>
# Outputs: JSON progress lines to stdout
# ============================================================

import json
import os
import sys
import time

# Ensure project root is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["TOKENIZERS_PARALLELISM"] = "false"

import warnings
warnings.filterwarnings("ignore")


def progress(event: str, **data):
    """Write a JSON progress line to stdout."""
    print(json.dumps({"event": event, **data}), flush=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 core/worker.py <config.json>", file=sys.stderr)
        sys.exit(1)

    # Load config from JSON file
    with open(sys.argv[1]) as f:
        cfg = json.load(f)

    mode = cfg.get("mode", "batch")
    voice = cfg.get("voice", "aiden")
    speed = cfg.get("speed", 1.0)
    emotion = cfg.get("emotion", "")
    ref_audio = cfg.get("ref_audio", "")
    ref_text = cfg.get("ref_text", "")
    script_file = cfg.get("script_file", "script.txt")
    output_file = cfg.get("output_file", "outputs/final_episode.wav")
    chunks_dir = cfg.get("chunks_dir", "outputs/chunks")
    silence_padding = cfg.get("silence_padding", 0.8)
    sample_rate = cfg.get("sample_rate", 24000)
    normalize_audio = cfg.get("normalize_audio", True)
    export_mp3 = cfg.get("export_mp3", True)
    model_path = cfg.get("model_path", "models/1.7B-CustomVoice")
    single_text = cfg.get("text", "")

    # ── Load model ───────────────────────────────────────────
    progress("status", status="loading", message="Loading TTS model...")

    from core.model import load_tts_model
    from core.audio import generate_chunk, stitch_wavs, get_duration
    from core.script import parse_script

    model = load_tts_model(model_path)

    # ── Parse chunks ─────────────────────────────────────────
    if mode == "single" and single_text:
        chunks = [{"text": single_text, "voice": None, "emotion": None}]
        output_file = "outputs/single_output.wav"
    else:
        if not os.path.exists(script_file):
            progress("error", message=f"Script file not found: {script_file}")
            sys.exit(1)
        chunks = parse_script(script_file)

    total = len(chunks)
    if total == 0:
        progress("error", message="No text to generate")
        sys.exit(1)

    os.makedirs(chunks_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_file) or "outputs", exist_ok=True)

    progress("status", status="generating", message=f"Generating {total} chunks...",
             total_chunks=total, current_chunk=0)

    # ── Generate chunks ──────────────────────────────────────
    made = []
    chunks_done = []

    for i, chunk in enumerate(chunks):
        chunk_path = os.path.join(chunks_dir, f"chunk_{i:04d}.wav")
        chunk_voice = chunk["voice"] or voice
        chunk_emotion = chunk["emotion"] or emotion
        preview = chunk["text"][:80]

        progress("status", status="generating",
                 message=f'Generating chunk {i + 1}/{total}: "{preview}..."',
                 current_chunk=i + 1, total_chunks=total)

        # Skip existing
        if os.path.exists(chunk_path):
            made.append(chunk_path)
            entry = {
                "index": i,
                "file": f"chunk_{i:04d}.wav",
                "duration": get_duration(chunk_path),
                "skipped": True,
            }
            chunks_done.append(entry)
            progress("chunk_done", **entry, chunks_done=chunks_done)
            continue

        t0 = time.time()
        ok = generate_chunk(
            model,
            chunk["text"],
            chunk_path,
            voice=chunk_voice,
            ref_audio=ref_audio,
            ref_text=ref_text,
            instruct=chunk_emotion,
            speed=speed,
            verbose=True,
        )

        if ok:
            made.append(chunk_path)
            elapsed = time.time() - t0
            entry = {
                "index": i,
                "file": f"chunk_{i:04d}.wav",
                "duration": get_duration(chunk_path),
                "time": f"{elapsed:.1f}s",
                "skipped": False,
            }
            chunks_done.append(entry)
            progress("chunk_done", **entry, chunks_done=chunks_done)
        else:
            entry = {"index": i, "file": f"chunk_{i:04d}.wav", "error": True}
            chunks_done.append(entry)
            progress("chunk_error", **entry, chunks_done=chunks_done)

    # ── Stitch ───────────────────────────────────────────────
    progress("status", status="stitching", message="Stitching chunks...",
             current_chunk=total, total_chunks=total)

    if made and stitch_wavs(
        made,
        output_file,
        silence_padding=silence_padding,
        sample_rate=sample_rate,
        normalize=normalize_audio,
        export_mp3=export_mp3,
    ):
        duration = get_duration(output_file)
        progress("done", status="done",
                 message=f"Complete! Duration: {duration}",
                 output_file=output_file, duration=duration,
                 chunks_done=chunks_done)
    else:
        progress("error", status="error", message="Stitching failed",
                 chunks_done=chunks_done)


if __name__ == "__main__":
    main()
