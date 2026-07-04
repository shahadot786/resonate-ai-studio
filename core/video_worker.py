#!/usr/bin/env python3
# ============================================================
# core/video_worker.py — B-Roll video generation worker
#
# Runs as a subprocess (like core/worker.py) so it can be
# spawned by the FastAPI server without blocking it.
#
# Usage: python3 core/video_worker.py <config.json>
# Outputs: JSON progress lines to stdout
# ============================================================

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["TOKENIZERS_PARALLELISM"] = "false"

import warnings
warnings.filterwarnings("ignore")


def progress(event: str, **data):
    """Write a JSON progress line to stdout."""
    print(json.dumps({"event": event, **data}), flush=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 core/video_worker.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        cfg = json.load(f)

    # ── Load config ──────────────────────────────────────────
    pexels_key          = cfg.get("pexels_api_key", "")
    pixabay_key         = cfg.get("pixabay_api_key", "")
    coverr_key          = cfg.get("coverr_api_key", "")
    gemini_key          = cfg.get("gemini_api_key", "")
    youtube_key         = cfg.get("youtube_api_key", "")
    keyword_mode        = cfg.get("keyword_mode", "rake")
    resolution          = cfg.get("resolution", "1920x1080")
    fps                 = cfg.get("fps", 30)
    script_file         = cfg.get("script_file", "script.txt")
    chunks_dir          = cfg.get("chunks_dir", "outputs/chunks")
    segments_dir        = cfg.get("segments_dir", "outputs/video/segments")
    output_file         = cfg.get("output_file", "outputs/video/final_video.mp4")
    audio_file          = cfg.get("audio_file", "outputs/final_episode.wav")
    clip_interval       = float(cfg.get("clip_interval", 0))
    review_before_merge = bool(cfg.get("review_before_merge", True))
    merge_trigger_file  = cfg.get("merge_trigger_file", "outputs/.merge_trigger")

    # ── Import modules ───────────────────────────────────────
    from core.script import parse_script
    from core.video import build_segment, merge_segments_with_audio

    # ── Parse script ─────────────────────────────────────────
    progress("status", status="loading", message="Parsing script…")

    if not os.path.exists(script_file):
        progress("error", message=f"Script file not found: {script_file}")
        sys.exit(1)

    if not os.path.exists(audio_file):
        progress("error", message=f"Audio file not found: {audio_file}. Generate audio first.")
        sys.exit(1)

    chunks = parse_script(script_file)
    total = len(chunks)

    if total == 0:
        progress("error", message="Script has no chunks")
        sys.exit(1)

    os.makedirs(segments_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_file) or "outputs/video", exist_ok=True)

    progress("status", status="searching",
             message=f"Processing {total} chunks…",
             total_chunks=total, current_chunk=0)

    # ── Build segments ────────────────────────────────────────
    segment_paths = []
    segments_done = []

    for i, chunk in enumerate(chunks):
        text = chunk["text"]
        preview = text[:70]

        # Audio chunk path (must exist from TTS generation)
        audio_chunk = os.path.join(chunks_dir, f"chunk_{i:04d}.wav")
        if not os.path.exists(audio_chunk):
            progress("segment_skip", index=i,
                     message=f"Audio chunk {i} not found, skipping")
            continue

        seg_path = os.path.join(segments_dir, f"segment_{i:04d}.mp4")

        # Skip if already built (use cached)
        if os.path.exists(seg_path) and os.path.getsize(seg_path) > 1024:
            segment_paths.append(seg_path)
            entry = {"index": i, "keyword": "cached", "source": "cache",
                     "type": "cached", "ok": True, "skipped": True}
            segments_done.append(entry)
            progress("segment_done", **entry,
                     current_chunk=i + 1, total_chunks=total,
                     segments_done=segments_done)
            continue

        progress("status", status="searching",
                 message=f'Chunk {i + 1}/{total}: "{preview}…"',
                 current_chunk=i + 1, total_chunks=total)

        def _cb(idx, msg, _i=i, _total=total, _preview=preview):
            progress("segment_progress", index=_i,
                     message=msg, current_chunk=_i + 1, total_chunks=_total)

        t0 = time.time()
        result = build_segment(
            index=i,
            text=text,
            audio_path=audio_chunk,
            out_path=seg_path,
            pexels_key=pexels_key,
            pixabay_key=pixabay_key,
            coverr_key=coverr_key,
            gemini_key=gemini_key,
            youtube_key=youtube_key,
            keyword_mode=keyword_mode,
            resolution=resolution,
            fps=fps,
            segments_dir=segments_dir,
            clip_interval=clip_interval,
            progress_cb=_cb,
        )

        elapsed = time.time() - t0
        result["time"] = f"{elapsed:.1f}s"
        result["skipped"] = False
        segments_done.append(result)

        if result["ok"]:
            segment_paths.append(seg_path)

        progress("segment_done", **result,
                 current_chunk=i + 1, total_chunks=total,
                 segments_done=segments_done)

    # ── All segments ready — pause for review if enabled ──────
    if not segment_paths:
        progress("error", status="error",
                 message="No video segments were created",
                 segments_done=segments_done)
        sys.exit(1)

    if review_before_merge:
        # Remove stale trigger file if it exists
        if os.path.exists(merge_trigger_file):
            os.remove(merge_trigger_file)

        # Emit review_ready — server/UI will show the Review Panel
        progress("review_ready", status="review_ready",
                 message=f"All {len(segment_paths)} clips ready. Review and click 'Merge Now' to continue.",
                 current_chunk=total, total_chunks=total,
                 segments_done=segments_done)

        # Poll for merge trigger file (server writes it when user clicks Merge)
        poll_interval = 1.0
        timeout = 3600  # 1 hour max wait
        waited = 0
        while waited < timeout:
            if os.path.exists(merge_trigger_file):
                try:
                    os.remove(merge_trigger_file)
                except Exception:
                    pass
                break
            # Also check for cancellation flag
            cancel_file = merge_trigger_file.replace(".merge_trigger", ".cancel_trigger")
            if os.path.exists(cancel_file):
                try:
                    os.remove(cancel_file)
                except Exception:
                    pass
                progress("error", status="cancelled",
                         message="Video generation cancelled by user.",
                         segments_done=segments_done)
                sys.exit(0)
            time.sleep(poll_interval)
            waited += poll_interval

        if waited >= timeout:
            progress("error", status="error",
                     message="Review timed out (1 hour). Run again to merge.",
                     segments_done=segments_done)
            sys.exit(1)

    # ── Merge ─────────────────────────────────────────────────
    # Re-scan segments_dir to pick up any replacements made during review
    final_paths = []
    for i, chunk in enumerate(chunks):
        seg_path = os.path.join(segments_dir, f"segment_{i:04d}.mp4")
        if os.path.exists(seg_path) and os.path.getsize(seg_path) > 1024:
            final_paths.append(seg_path)

    if not final_paths:
        final_paths = segment_paths  # fallback to original list

    progress("status", status="merging",
             message=f"Merging {len(final_paths)} segments with audio…",
             current_chunk=total, total_chunks=total)

    ok = merge_segments_with_audio(final_paths, audio_file, output_file, fps)

    if ok:
        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        progress("done", status="done",
                 message=f"Video ready! {len(final_paths)} segments, {size_mb:.1f} MB",
                 output_file=output_file,
                 segments_done=segments_done,
                 total_chunks=total,
                 current_chunk=total)
    else:
        progress("error", status="error",
                 message="Final merge failed",
                 segments_done=segments_done)


if __name__ == "__main__":
    main()
