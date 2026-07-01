# ============================================================
# core/audio.py — Audio generation, stitching, and post-processing
# ============================================================

import gc
import os
import shutil
import struct
import subprocess
import wave

from mlx_audio.tts.generate import generate_audio


# ── Single chunk generation ──────────────────────────────────


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


# ── Silence generation ───────────────────────────────────────


def generate_silence(duration: float, output_path: str, sample_rate: int = 24000) -> str:
    """Create a silent WAV file of the given duration.

    Returns the output path.
    """
    num_samples = int(sample_rate * duration)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with wave.open(output_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))

    return output_path


# ── Loudness normalization ───────────────────────────────────


def normalize_wav(input_path: str, output_path: str | None = None) -> bool:
    """Apply EBU R128 loudness normalization via ffmpeg.

    If output_path is None, normalizes in-place.
    Returns True on success.
    """
    if output_path is None:
        output_path = input_path

    tmp = input_path + ".norm.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            tmp,
        ],
        capture_output=True,
    )

    if result.returncode == 0:
        shutil.move(tmp, output_path)
        return True

    # Clean up on failure
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


# ── Format conversion ────────────────────────────────────────


def convert_to_mp3(wav_path: str, mp3_path: str | None = None, bitrate: str = "192k") -> bool:
    """Convert WAV to MP3 via ffmpeg.

    If mp3_path is None, uses the same name with .mp3 extension.
    Returns True on success.
    """
    if mp3_path is None:
        mp3_path = os.path.splitext(wav_path)[0] + ".mp3"

    os.makedirs(os.path.dirname(mp3_path) or ".", exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", wav_path,
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
            mp3_path,
        ],
        capture_output=True,
    )
    return result.returncode == 0


# ── Stitching ────────────────────────────────────────────────


def stitch_wavs(
    wav_files: list[str],
    output_path: str,
    *,
    silence_padding: float = 0.0,
    sample_rate: int = 24000,
    normalize: bool = False,
    export_mp3: bool = False,
) -> bool:
    """Concatenate WAV files into a single file using ffmpeg.

    Options:
        silence_padding — seconds of silence to insert between chunks
        normalize       — apply EBU R128 loudness normalization to final output
        export_mp3      — also export an MP3 copy

    Returns True on success.
    """
    if not wav_files:
        return False

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    list_file = output_path + ".concat.txt"
    silence_file = None

    try:
        # Generate silence WAV if padding requested
        if silence_padding > 0:
            silence_file = output_path + ".silence.wav"
            generate_silence(silence_padding, silence_file, sample_rate)

        # Write concat list (interleaving silence if needed)
        with open(list_file, "w") as f:
            for i, path in enumerate(wav_files):
                f.write(f"file '{os.path.abspath(path)}'\n")
                if silence_file and i < len(wav_files) - 1:
                    f.write(f"file '{os.path.abspath(silence_file)}'\n")

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

        if result.returncode != 0:
            return False

        # Post-process
        if normalize:
            normalize_wav(output_path)

        if export_mp3:
            convert_to_mp3(output_path)

        return True

    finally:
        if os.path.exists(list_file):
            os.remove(list_file)
        if silence_file and os.path.exists(silence_file):
            os.remove(silence_file)


# ── Duration query ───────────────────────────────────────────


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


def get_duration_secs(wav_path: str) -> float:
    """Return duration in seconds via ffprobe, or 0.0 on error."""
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
        return float(result.stdout.strip())
    except Exception:
        return 0.0
