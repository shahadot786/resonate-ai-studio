# ============================================================
# core/audio.py — Audio generation and stitching
# ============================================================

import gc
import os
import shutil
import subprocess

from mlx_audio.tts.generate import generate_audio


def generate_chunk(
    model,
    text: str,
    output_path: str,
    *,
    voice: str = "aiden",
    ref_audio: str | None = None,
    ref_text: str | None = None,
    instruct: str | None = None,
    speed: float = 1.0,
    verbose: bool = True,
) -> bool:
    """Generate a single WAV chunk and save it to *output_path*.

    Uses a temporary directory internally and cleans up on success or failure.
    Returns True if the WAV was created successfully.
    """
    tmp_dir = output_path + ".tmp"
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        generate_audio(
            model=model,
            text=text,
            voice=voice,
            ref_audio=ref_audio,
            ref_text=ref_text,
            instruct=instruct,
            speed=speed,
            output_path=tmp_dir,
            save=True,
            verbose=verbose,
        )

        wavs = sorted(f for f in os.listdir(tmp_dir) if f.endswith(".wav"))
        if wavs:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            shutil.move(os.path.join(tmp_dir, wavs[0]), output_path)
            return True

        print(f"  ✗ No WAV produced for: {text[:50]}...")
        return False

    except Exception as e:
        print(f"  ✗ Generation error: {e}")
        return False

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        gc.collect()


def stitch_wavs(wav_files: list[str], output_path: str) -> bool:
    """Concatenate WAV files into a single file using ffmpeg.

    Returns True on success.
    """
    if not wav_files:
        return False

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    list_file = output_path + ".concat.txt"

    try:
        with open(list_file, "w") as f:
            for path in wav_files:
                f.write(f"file '{os.path.abspath(path)}'\n")

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                output_path,
            ],
            capture_output=True,
        )
        return result.returncode == 0

    finally:
        if os.path.exists(list_file):
            os.remove(list_file)


def get_duration(wav_path: str) -> str:
    """Return a human-readable duration string (e.g. '3m 24s') via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                wav_path,
            ],
            capture_output=True,
            text=True,
        )
        secs = float(result.stdout.strip())
        return f"{int(secs // 60)}m {int(secs % 60)}s"
    except Exception:
        return "unknown"
