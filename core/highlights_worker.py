#!/usr/bin/env python3
# ============================================================
# core/highlights_worker.py — Highlight clipping worker
# ============================================================

import os
import sys
import json
import subprocess
import requests
import time

def progress(event: str, **data):
    """Emit a JSON progress line to stdout."""
    print(json.dumps({"event": event, **data}), flush=True)

def _get_duration_secs(video_path: str) -> float:
    """Get video duration using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def _has_audio_stream(video_path: str) -> bool:
    """Check if the video has an audio track using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return "audio" in r.stdout.lower()
    except Exception:
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 core/highlights_worker.py <config.json>", file=sys.stderr)
        sys.exit(1)

    # 1. Load configuration
    config_path = sys.argv[1]
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    video_path     = cfg.get("video_path", "")
    clip_count     = int(cfg.get("clip_count", 3))
    clip_duration  = int(cfg.get("clip_duration", 30))
    groq_keys      = cfg.get("groq_keys", [])
    highlights_dir = cfg.get("highlights_dir", "outputs/highlights")

    if not video_path or not os.path.exists(video_path):
        progress("error", message=f"Video file not found: {video_path}")
        sys.exit(1)

    if not groq_keys:
        progress("error", message="No Groq API keys available for transcription.")
        sys.exit(1)

    os.makedirs(highlights_dir, exist_ok=True)
    video_base = os.path.splitext(os.path.basename(video_path))[0]

    # Verify audio stream presence
    if not _has_audio_stream(video_path):
        progress("error", message="The uploaded video does not contain any audio tracks. Highlights extraction requires speech transcription to identify viral sections.")
        sys.exit(1)

    # ── Step A: Extract highly compressed audio ─────────────────
    progress("status", status="extracting_audio", message="Extracting compressed audio track...")
    audio_path = os.path.join(highlights_dir, f"{video_base}_temp_audio.mp3")
    
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except Exception:
            pass

    cmd_audio = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-ab", "32k",
        audio_path
    ]
    
    try:
        r = subprocess.run(cmd_audio, capture_output=True, timeout=180)
        if r.returncode != 0 or not os.path.exists(audio_path):
            progress("error", message=f"Audio extraction failed: {r.stderr.decode('utf-8', errors='ignore')}")
            sys.exit(1)
    except Exception as e:
        progress("error", message=f"Audio extraction timed out or failed: {e}")
        sys.exit(1)

    # ── Step B: Transcribe audio using Groq Whisper ─────────────
    progress("status", status="transcribing", message="Transcribing audio with timestamps (Groq Whisper)...")
    
    transcript_data = None
    transcription_success = False

    for key in groq_keys:
        try:
            with open(audio_path, "rb") as af:
                files = {
                    "file": (os.path.basename(audio_path), af, "audio/mpeg")
                }
                data = {
                    "model": "whisper-large-v3",
                    "response_format": "verbose_json"
                }
                headers = {"Authorization": f"Bearer {key}"}
                
                resp = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60
                )
                
                # Log stats
                try:
                    from core.video import _update_groq_stats
                    if resp.status_code == 200:
                        _update_groq_stats(key, success=True, rate_limited=False)
                    elif resp.status_code == 429:
                        _update_groq_stats(key, success=False, rate_limited=True)
                except Exception:
                    pass

                if resp.status_code == 200:
                    transcript_data = resp.json()
                    transcription_success = True
                    break
                elif resp.status_code == 429:
                    print(f"  ⚠ Key {key[:12]}... rate-limited, rotating...", file=sys.stderr)
                    continue
                else:
                    print(f"  ⚠ Groq Whisper API error ({resp.status_code}): {resp.text}", file=sys.stderr)
                    continue
        except Exception as e:
            print(f"  ⚠ Groq Whisper request exception: {e}", file=sys.stderr)
            continue

    # Cleanup temp audio
    try:
        if os.path.exists(audio_path):
            os.remove(audio_path)
    except Exception:
        pass

    if not transcription_success or not transcript_data:
        progress("error", message="Failed to transcribe audio. All Groq keys failed or returned errors.")
        sys.exit(1)

    # ── Step C: Format transcription segments ───────────────────
    segments = transcript_data.get("segments", [])
    if not segments:
        progress("error", message="No speech detected in the video transcript.")
        sys.exit(1)

    formatted_transcript = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end   = float(seg.get("end", 0.0))
        text  = seg.get("text", "").strip()
        formatted_transcript.append(f"[{start:.2f}s - {end:.2f}s]: {text}")

    transcript_text = "\n".join(formatted_transcript)

    # ── Step D: Analyze transcript with Llama-3.3-70B ───────────
    progress("status", status="analyzing", message="Analyzing transcript for highlights (Groq Llama)...")

    system_prompt = f"""You are an expert AI video editor and viral clips coordinator.
Your task is to analyze the timestamped transcription of a long video and extract exactly {clip_count} highlights for YouTube Shorts/TikTok.

Instructions:
1. Identify the most interesting, surprising, funny, or self-contained highlight clips.
2. DURATION LIMIT: The target duration for each clip is {clip_duration} seconds. Each clip MUST be between 15 seconds and 60 seconds (minimum 15.0s, maximum 60.0s). Choose conversational boundaries (starts/ends of sentences) that are as close to {clip_duration} seconds as possible, but strictly within the 15s to 60s limit. Do NOT recommend any clip shorter than 15 seconds.
3. Ensure each clip represents a cohesive segment (e.g., covers a complete thought, story, or joke).
4. The clips must NOT overlap. Start times must be strictly sequential.
5. Provide a short, catchy, viral title for each highlight clip.

Return a raw JSON object matching the schema below. Do NOT write any markdown blocks (like ```json), introduction, or follow-up notes. Write ONLY the JSON object.

JSON Schema:
{{
  "highlights": [
    {{
      "title": "catchy viral title",
      "start_time": float,
      "end_time": float,
      "reason": "short explanation of why this segment is an engaging highlight"
    }}
  ]
}}"""

    user_prompt = f"Here is the timestamped transcript:\n\n{transcript_text}\n\nSelect exactly {clip_count} dynamic highlights."

    highlights_list = None
    analysis_success = False

    for key in groq_keys:
        try:
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 1200
            }
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            try:
                from core.video import _update_groq_stats
                if resp.status_code == 200:
                    _update_groq_stats(key, success=True, rate_limited=False)
                elif resp.status_code == 429:
                    _update_groq_stats(key, success=False, rate_limited=True)
            except Exception:
                pass

            if resp.status_code == 200:
                response_content = resp.json()["choices"][0]["message"]["content"].strip()
                # Clean up potential markdown formatting wrapping the JSON
                if response_content.startswith("```"):
                    lines = response_content.splitlines()
                    if lines[0].startswith("```json") or lines[0].startswith("```"):
                        response_content = "\n".join(lines[1:-1]).strip()
                
                try:
                    res_json = json.loads(response_content)
                    highlights_list = res_json.get("highlights", [])
                    if len(highlights_list) > 0:
                        analysis_success = True
                        break
                except json.JSONDecodeError:
                    print(f"  ⚠ Llama output failed to parse as JSON: {response_content[:150]}...", file=sys.stderr)
                    continue
            elif resp.status_code == 429:
                print(f"  ⚠ Key {key[:12]}... rate-limited, rotating...", file=sys.stderr)
                continue
        except Exception as e:
            print(f"  ⚠ Llama completion request failed: {e}", file=sys.stderr)
            continue

    if not analysis_success or not highlights_list:
        progress("error", message="Failed to analyze transcript. Check your Llama API limits.")
        sys.exit(1)

    # ── Step E: Clip Video Segments ─────────────────────────────
    video_total_duration = _get_duration_secs(video_path)
    final_clips_meta = []

    for idx, highlight in enumerate(highlights_list):
        title      = highlight.get("title", f"Clip {idx+1}").strip()
        start_time = float(highlight.get("start_time", 0.0))
        end_time   = float(highlight.get("end_time", 0.0))
        reason     = highlight.get("reason", "").strip()

        # Sanitize boundaries
        if start_time < 0.0:
            start_time = 0.0
        if end_time > video_total_duration:
            end_time = video_total_duration
        
        duration = end_time - start_time
        
        # Enforce target clip duration limit by expanding boundaries symmetrically
        target_len = min(float(clip_duration), video_total_duration)
        if duration < target_len:
            needed = target_len - duration
            push_back = needed / 2.0
            start_time -= push_back
            end_time += push_back
            
            if start_time < 0.0:
                leftover = -start_time
                start_time = 0.0
                end_time += leftover
                
            if end_time > video_total_duration:
                leftover = end_time - video_total_duration
                end_time = video_total_duration
                start_time = max(0.0, start_time - leftover)
                
            duration = end_time - start_time
        if duration <= 1.0:
            print(f"  ⚠ Skipping clip {idx+1} due to zero or short duration ({duration:.1f}s)", file=sys.stderr)
            continue

        progress("status", status="clipping", 
                 message=f"Cutting highlight {idx+1}/{len(highlights_list)} ({duration:.1f}s): «{title}»...", 
                 current=idx+1, total=len(highlights_list))

        clip_filename = f"{video_base}_highlight_{idx+1}_{int(time.time())}.mp4"
        clip_path     = os.path.join(highlights_dir, clip_filename)

        # Lossless stream copy cut
        cmd_cut = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.3f}",
            "-i", video_path,
            "-t", f"{duration:.3f}",
            "-c", "copy",
            clip_path
        ]

        try:
            r = subprocess.run(cmd_cut, capture_output=True, timeout=60)
            if r.returncode == 0 and os.path.exists(clip_path):
                # Save metadata
                meta = {
                    "id":          f"{video_base}_clip_{idx+1}",
                    "title":       title,
                    "filename":    clip_filename,
                    "start_time":  start_time,
                    "end_time":    end_time,
                    "duration":    duration,
                    "reason":      reason,
                    "created":     time.strftime("%Y-%m-%d %H:%M:%S")
                }
                meta_path = os.path.join(highlights_dir, f"{os.path.splitext(clip_filename)[0]}.json")
                with open(meta_path, "w", encoding="utf-8") as mf:
                    json.dump(meta, mf, indent=2)
                
                final_clips_meta.append(meta)
            else:
                print(f"  ⚠ Failed cutting clip {idx+1}: {r.stderr.decode('utf-8', errors='ignore')}", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Exception during clipping {idx+1}: {e}", file=sys.stderr)

    if not final_clips_meta:
        progress("error", message="Failed to extract any highlight clips successfully.")
        sys.exit(1)

    progress("done", message=f"Successfully extracted {len(final_clips_meta)} highlight clips!", clips=final_clips_meta)

if __name__ == "__main__":
    main()
