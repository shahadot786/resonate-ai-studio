# ============================================================
# core/music_ducking.py — Background music sidechain ducking
# ============================================================

import os
import subprocess

def mix_audio_ducked(
    voice_path: str,
    music_path: str,
    out_path: str,
    music_volume: float = 0.12,
    duck_ratio: float = 4.0,
) -> bool:
    """
    Mix background music with a voiceover track.
    Applies a sidechain compressor filter: whenever the voiceover is active,
    the background music volume automatically ducks (attenuates) to avoid drowning the voice.
    
    If the music file doesn't exist, we fall back to copying the voiceover directly.
    """
    if not os.path.exists(voice_path):
        print(f"  ⚠ Voiceover path not found: {voice_path}")
        return False
        
    if not music_path or not os.path.exists(music_path):
        print(f"  ⚠ Background music file not found or disabled: '{music_path}'. Using clean voiceover.")
        # Just copy/convert voiceover to out_path
        try:
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", voice_path, "-c:a", "pcm_s16le", out_path],
                capture_output=True,
                timeout=30
            )
            return r.returncode == 0
        except Exception as e:
            print(f"  ⚠ Failed to copy voiceover: {e}")
            return False

    print(f"  🎵 Mixing background music: '{music_path}' (vol={music_volume}, ratio={duck_ratio})")
    
    # FFmpeg sidechaincompress filter graph:
    # 1. Loop the music indefinitely (-stream_loop -1) to fit any voiceover length.
    # 2. Adjust background music volume: [0:a]volume=music_volume[bg]
    # 3. Split voiceover audio: [1:a]asplit[sc][voice] (sc for control, voice for final mix)
    # 4. Compress background music using the voiceover split as control:
    #    [bg][sc]sidechaincompress=threshold=0.12:ratio=duck_ratio:attack=50:release=600[ducked]
    # 5. Mix the ducked music and voiceover, matching the duration of the voiceover:
    #    [ducked][voice]amix=inputs=2:duration=first[mixed]
    filter_expr = (
        f"[0:a]volume={music_volume}[bg]; "
        f"[1:a]asplit[sc][voice]; "
        f"[bg][sc]sidechaincompress=threshold=0.12:ratio={duck_ratio}:attack=50:release=600[ducked]; "
        f"[ducked][voice]amix=inputs=2:duration=first[mixed]"
    )
    
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", music_path,
                "-i", voice_path,
                "-filter_complex", filter_expr,
                "-map", "[mixed]",
                "-c:a", "pcm_s16le",
                out_path
            ],
            capture_output=True,
            timeout=120
        )
        if r.returncode == 0:
            print(f"  ✓ Mixed and ducked audio saved: {out_path}")
            return True
        else:
            print(f"  ⚠ FFmpeg audio mixing failed (code {r.returncode}): {r.stderr.decode('utf-8', errors='ignore')[:300]}")
            # Fallback to copy voiceover only
            subprocess.run(["ffmpeg", "-y", "-i", voice_path, "-c:a", "pcm_s16le", out_path], capture_output=True)
            return True
            
    except Exception as e:
        print(f"  ⚠ Audio mixing exception: {e}")
        return False
