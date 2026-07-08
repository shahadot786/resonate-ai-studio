#!/usr/bin/env python3
# ============================================================
# core/shorts_worker.py — Automated Shorts generation worker
# ============================================================

import json
import os
import sys
import time

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["TOKENIZERS_PARALLELISM"] = "false"

import warnings
warnings.filterwarnings("ignore")

def progress(event: str, **data):
    """Write a JSON progress line to stdout."""
    print(json.dumps({"event": event, **data}), flush=True)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 core/shorts_worker.py <config.json>", file=sys.stderr)
        sys.exit(1)

    # ── 1. Load config ───────────────────────────────────────
    with open(sys.argv[1]) as f:
        cfg = json.load(f)

    title               = cfg.get("title", "Untitled Short")
    target_duration     = int(cfg.get("duration", 60))
    style_preset        = cfg.get("style_preset", "cinematic")
    image_provider      = cfg.get("image_provider", "free_api")
    music_enabled       = bool(cfg.get("music_enabled", True))
    music_file          = cfg.get("music_file", "ref/bg_music.mp3")
    music_volume        = float(cfg.get("music_volume", 0.12))
    captions_enabled    = bool(cfg.get("captions_enabled", True))
    transitions_enabled = bool(cfg.get("transitions_enabled", True))
    transition_style    = cfg.get("transition_style", "crossfade")
    auto_voice          = bool(cfg.get("auto_voice", True))
    default_voice       = cfg.get("default_voice", "am_adam")
    groq_keys           = cfg.get("groq_keys", [])
    available_voices    = cfg.get("available_voices", [])
    model_path          = cfg.get("model_path", "models/kokoro/kokoro-v1.0.onnx")
    
    # Clean working directories
    chunks_dir          = "outputs/chunks/shorts"
    shorts_dir          = "outputs/video/shorts"
    os.makedirs(chunks_dir, exist_ok=True)
    os.makedirs(shorts_dir, exist_ok=True)
    
    final_output_file   = cfg.get("output_file", "outputs/video/final_video.mp4")

    # Temp files
    voiceover_raw       = os.path.join(shorts_dir, "voiceover_raw.wav")
    voiceover_mixed     = os.path.join(shorts_dir, "voiceover_mixed.wav")
    video_no_audio      = os.path.join(shorts_dir, "video_no_audio.mp4")
    video_subbed        = os.path.join(shorts_dir, "video_subbed.mp4")
    subtitles_ass       = os.path.join(shorts_dir, "subtitles.ass")
    subtitles_vtt       = os.path.join(shorts_dir, "subtitles.vtt")

    # ── Imports ──────────────────────────────────────────────
    from core.script import generate_shorts_script_from_title
    from core.model import load_tts_model
    from core.audio import generate_chunk, stitch_wavs, get_duration_secs
    from core.image_generator import generate_image
    from core.video import image_to_video_dynamic, compile_transitions_xfade, generate_ass_file, generate_vtt_file, burn_subtitles_into_video

    from core.music_ducking import mix_audio_ducked

    # ── Step A: Generate Script ──────────────────────────────
    progress("status", status="generating_script", message="Writing script & visual recommendations using Groq AI...")
    
    try:
        shorts_data = generate_shorts_script_from_title(
            title=title,
            target_duration=target_duration,
            style_preset=style_preset,
            groq_keys=groq_keys,
            available_voices=available_voices
        )
    except Exception as e:
        progress("error", message=f"Script generation failed: {str(e)}")
        sys.exit(1)

    segments = shorts_data.get("segments", [])
    tone = shorts_data.get("tone_analysis", "General narrative")
    rec_voice = shorts_data.get("recommended_voice", default_voice)
    rec_style = shorts_data.get("recommended_style", "cinematic")
    rec_transition = shorts_data.get("recommended_transition", "crossfade")
    creation_tip = shorts_data.get("creation_tip", "Make visuals engaging.")

    # Override settings with recommended options if set to "auto"
    if style_preset == "auto":
        style_preset = rec_style
    if transition_style == "auto":
        transition_style = rec_transition
    active_voice = rec_voice if auto_voice else default_voice

    progress(
        "script_ready",
        tone=tone,
        recommended_voice=rec_voice,
        recommended_style=rec_style,
        recommended_transition=rec_transition,
        creation_tip=creation_tip,
        active_voice=active_voice,
        segments=segments,
        segments_count=len(segments)
    )


    # Save script draft for debugging or reference
    with open(os.path.join(shorts_dir, "script_draft.json"), "w") as sf:
        json.dump(shorts_data, sf, indent=2)

    # ── Step B: Voiceover Synthesis ──────────────────────────
    progress("status", status="loading_tts", message="Initializing speech synthesis engine...")
    try:
        model = load_tts_model(model_path)
    except Exception as e:
        progress("error", message=f"Failed to load TTS model: {str(e)}")
        sys.exit(1)

    total_segments = len(segments)
    chunk_paths = []
    chunk_durations = []

    for i, seg in enumerate(segments):
        progress("status", status="generating_speech", 
                 message=f"Voicing segment {i+1}/{total_segments}...", 
                 current=i+1, total=total_segments)
        
        chunk_path = os.path.join(chunks_dir, f"shorts_chunk_{i:04d}.wav")
        
        ok = generate_chunk(
            model=model,
            text=seg["text"],
            output_path=chunk_path,
            voice=active_voice,
            verbose=False
        )
        
        if not ok:
            progress("error", message=f"Failed to voice chunk {i}: {seg['text']}")
            sys.exit(1)
            
        dur = get_duration_secs(chunk_path)
        # Prevent zero-length chunk issues
        if dur <= 0:
            dur = 2.0 
            
        chunk_paths.append(chunk_path)
        chunk_durations.append(dur)
        
    # Stitch raw audio with a tiny silence pad for snappy shorts pacing
    progress("status", status="stitching_audio", message="Stitching voiceover track...")
    ok_stitch = stitch_wavs(
        wav_files=chunk_paths,
        output_path=voiceover_raw,
        silence_padding=0.15,
        sample_rate=24000,
        normalize=True
    )
    if not ok_stitch:
        progress("error", message="Failed to compile voiceover master audio track.")
        sys.exit(1)

    # ── Step C & D: Compile Scene Clips (AI Generated Images or Stock Footage) ──────
    clip_paths = []
    
    pexels_key = cfg.get("pexels_api_key", "")
    pixabay_key = cfg.get("pixabay_api_key", "")
    coverr_key = cfg.get("coverr_api_key", "")
    clip_interval = float(cfg.get("clip_interval", 0.0))

    if image_provider == "stock":
        for i, seg in enumerate(segments):
            progress("status", status="rendering_clip", 
                     message=f"Searching stock footage for scene {i+1}/{total_segments}...", 
                     current=i+1, total=total_segments)
                     
            clip_path = os.path.join(shorts_dir, f"clip_{i:04d}.mp4")
            segment_duration = chunk_durations[i] + (0.15 if i < len(chunk_durations) - 1 else 0.0)
            sentence_audio = os.path.join(shorts_dir, f"sentence_{i:04d}.wav")
            
            from core.video import build_segment
            build_segment(
                index=i,
                text=seg["text"],
                audio_path=sentence_audio,
                out_path=clip_path,
                pexels_key=pexels_key,
                pixabay_key=pixabay_key,
                coverr_key=coverr_key,
                groq_keys=groq_keys,
                keyword_mode="groq",
                resolution="1080x1920", # vertical portrait for shorts
                fps=30,
                segments_dir=os.path.join(shorts_dir, "stock_segments"),
                clip_interval=clip_interval,
                progress_cb=lambda idx, msg: progress("status", status="rendering_clip", 
                                                      message=f"Scene {idx+1}: {msg}", 
                                                      current=idx+1, total=total_segments)
            )
            
            if not os.path.exists(clip_path):
                from core.video import create_color_segment
                create_color_segment(clip_path, segment_duration, color="darkgray", resolution="1080x1920")
                
            clip_paths.append(clip_path)
            
    else:
        # AI Generated Images
        image_paths = []
        for i, seg in enumerate(segments):
            progress("status", status="generating_images", 
                     message=f"Generating image {i+1}/{total_segments}...", 
                     current=i+1, total=total_segments)
                     
            img_path = os.path.join(shorts_dir, f"image_{i:04d}.jpg")
            ok_img = generate_image(
                prompt=seg["image_prompt"],
                out_path=img_path,
                provider=image_provider,
                style_preset=style_preset
            )
            
            if not ok_img:
                # Generate solid color fallback on failure
                progress("status", status="warning", message=f"Image generation failed for segment {i+1}. Creating color fallback.")
                from core.video import create_color_segment
                # Create dummy clip of required duration (with padding alignment)
                dummy_clip = os.path.join(shorts_dir, f"clip_{i:04d}.mp4")
                dummy_dur = chunk_durations[i] + (0.15 if i < len(chunk_durations) - 1 else 0.0)
                create_color_segment(dummy_clip, dummy_dur, color="blue", resolution="1080x1920")
                image_paths.append(img_path)  # Just keep track
                continue
                
            image_paths.append(img_path)

        for i, img in enumerate(image_paths):
            # If dummy clip was already created, reuse it
            dummy_clip = os.path.join(shorts_dir, f"clip_{i:04d}.mp4")
            if os.path.exists(dummy_clip):
                clip_paths.append(dummy_clip)
                continue
                
            progress("status", status="rendering_motion", 
                     message=f"Applying motion effects to image {i+1}/{total_segments}...", 
                     current=i+1, total=total_segments)
                     
            clip_path = os.path.join(shorts_dir, f"clip_{i:04d}.mp4")
            
            # Grab attention immediately in the first 1s: Force zoom in/out for the first scene
            motion_effect = "random"
            if i == 0:
                import random
                motion_effect = random.choice(["zoom_in", "zoom_out"])
                
            segment_duration = chunk_durations[i] + (0.15 if i < len(chunk_durations) - 1 else 0.0)
            
            ok_motion = image_to_video_dynamic(
                img_path=img,
                out_path=clip_path,
                duration=segment_duration,
                motion=motion_effect,
                resolution="1080x1920",
                fps=30
            )
            if not ok_motion:
                from core.video import create_color_segment
                create_color_segment(clip_path, segment_duration, color="darkgray", resolution="1080x1920")
                
            clip_paths.append(clip_path)

    # ── Step E: Compile transitions and merge video ─────────
    progress("status", status="compiling_video", message="Assembling clips with crossfades...")
    
    padded_durations = [chunk_durations[k] + (0.15 if k < len(chunk_durations) - 1 else 0.0) for k in range(len(chunk_durations))]
    style_t = transition_style if transitions_enabled else "none"
    ok_merge = compile_transitions_xfade(
        clips=clip_paths,
        durations=padded_durations,
        transition_style=style_t,
        out_path=video_no_audio,
        resolution="1080x1920"
    )
    if not ok_merge:
        progress("error", message="Failed to compile transitions/videos.")
        sys.exit(1)

    # ── Step F: Mix Ducked background music ─────────────────
    progress("status", status="mixing_music", message="Mixing background music (auto-ducking)...")
    ok_music = mix_audio_ducked(
        voice_path=voiceover_raw,
        music_path=music_file if music_enabled else "",
        out_path=voiceover_mixed,
        music_volume=music_volume
    )
    if not ok_music:
        progress("error", message="Audio mix & sidechain ducking failed.")
        sys.exit(1)

    # ── Step G: Dynamic Captions Subtitles ───────────────────
    if captions_enabled:
        progress("status", status="adding_subtitles", message="Formatting and burning subtitles...")
        generate_ass_file(segments, chunk_durations, subtitles_ass)
        generate_vtt_file(segments, chunk_durations, subtitles_vtt)
        ok_sub = burn_subtitles_into_video(video_no_audio, subtitles_ass, video_subbed)
        if not ok_sub:
            # Fallback to un-captioned video
            import shutil
            shutil.copy2(video_no_audio, video_subbed)
    else:
        import shutil
        shutil.copy2(video_no_audio, video_subbed)
        # Write empty WebVTT file so browser track doesn't error out
        with open(subtitles_vtt, "w", encoding="utf-8") as vf:
            vf.write("WEBVTT\n\n")

    # ── Step H: Mux Final Video ──────────────────────────────
    progress("status", status="final_mux", message="Muxing final video and audio tracks...")
    
    final_voiceover_duration = get_duration_secs(voiceover_mixed)
    
    try:
        import subprocess
        # Mux combined video stream and mixed audio stream (Encode audio to AAC for browser compatibility)
        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", video_subbed,
                "-i", voiceover_mixed,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-t", str(final_voiceover_duration),
                final_output_file
            ],
            capture_output=True,
            timeout=120
        )
        if r.returncode != 0:
            progress("error", message=f"Final mux failed: {r.stderr.decode()}")
            sys.exit(1)
    except Exception as e:
        progress("error", message=f"Final mux exception: {str(e)}")
        sys.exit(1)

    # ── Clean working cache files ────────────────────────────
    try:
        # Clean temp mp4 clips and wav files to save space
        for clip in clip_paths:
            if os.path.exists(clip):
                os.remove(clip)
        for img in image_paths:
            if os.path.exists(img):
                os.remove(img)
        for temp in [voiceover_raw, voiceover_mixed, video_no_audio, video_subbed, subtitles_ass]:
            if os.path.exists(temp):
                os.remove(temp)
    except Exception:
        pass

    size_mb = os.path.getsize(final_output_file) / (1024 * 1024)
    print(f"  ✓ Dynamic Short created successfully: {final_output_file} ({size_mb:.2f} MB)")
    
    progress("done", status="done", message="Dynamic Short compiled successfully!", output_file=final_output_file)

if __name__ == "__main__":
    main()
