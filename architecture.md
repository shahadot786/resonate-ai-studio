# 🏗️ Resonate AI Studio Architecture & Flow Diagrams

This document details the architectural design, component interactions, data flows, folder structures, and runtime specs of the Resonate AI voice and video generation studio.

---

## 1. High-Level Process Architecture

The system is designed with **strict process isolation** to isolate high-CPU/GPU operations (ONNX neural synthesis and FFmpeg transcoding) from the main web server process.

```mermaid
graph TD
    UI[Web Browser UI] <-->|HTTP / SSE Events| Server[FastAPI Server server.py]
    Server -.->|Spawn subprocess| AudioWorker[Audio Worker core/worker.py]
    Server -.->|Spawn subprocess| VideoWorker[Video Worker core/video_worker.py]
    
    subgraph Audio Generation Pipeline
        AudioWorker -->|Load ONNX| KokoroModel[Kokoro ONNX Engine]
        AudioWorker -->|Parse tags| ScriptParser[Script Parser core/script.py]
        AudioWorker -->|Stitch WAVs| FFmpegAudio[FFmpeg Audio Stitcher]
    end

    subgraph Video Generation Pipeline
        VideoWorker -->|Rotate 7 Keys| Groq[Groq API Keyword Resolver]
        VideoWorker -->|Search Stock APIs| StockAPIs[Pexels / Pixabay / Coverr]
        VideoWorker -->|Download & Scale| FFmpegScale[FFmpeg Normalizer]
        VideoWorker -->|Final Concatenation| FFmpegMerge[FFmpeg Merger & Muxer]
    end
```

---

## 2. Audio Generation Pipeline Workflow

The audio generation worker parses the storytelling script, extracts speaker/emotion metadata tags, synthesizes WAV chunk clips locally using Kokoro-ONNX, and stitches them with configured silence padding.

```mermaid
sequenceDiagram
    participant UI as Web Frontend
    participant Server as FastAPI Server
    participant Worker as Audio Worker
    participant Kokoro as Kokoro ONNX
    participant FFmpeg as FFmpeg Stitcher

    UI->>Server: POST /api/generate (script text, config)
    Note over Server: Delete old chunks & final_episode.wav
    Server->>Worker: Spawn core/worker.py with config.json
    Server-->>UI: return {"ok": true} (running=true)
    
    Loop For each chunk in script
        Worker->>Kokoro: create(text, voice, speed)
        Kokoro-->>Worker: return raw audio samples
        Worker->>Worker: Write outputs/chunks/chunk_XXXX.wav
        Worker-->>Server: stdout progress (chunk_done)
        Server-->>UI: SSE progress update
    end

    Worker->>FFmpeg: Concatenate WAV list + silence pad
    FFmpeg-->>Worker: final_episode.wav created
    Worker-->>Server: stdout progress (done)
    Note over Server: Archive generation
    Server-->>UI: SSE progress update (done)
    Note over UI: Reveal audio master player (cache-busted)
```

---

## 3. Video B-Roll Generation Pipeline Workflow

The video pipeline extracts visual search queries using the 7-key Groq pool, queries stock video providers, scales clips to the target format, waits for user review, and compiles the final video.

```mermaid
sequenceDiagram
    participant UI as Web Frontend
    participant Server as FastAPI Server
    participant Worker as Video Worker
    participant Groq as Groq (Llama 3.3)
    participant Stock as Stock APIs
    participant FFmpeg as FFmpeg Engine

    UI->>Server: POST /api/video/create
    Note over Server: Clear outputs/video/segments/*.mp4
    Server->>Worker: Spawn core/video_worker.py
    
    Loop For each segment
        Worker->>Groq: Request 5 visual keywords (handles 429 rotation)
        Groq-->>Worker: return keywords
        Worker->>Stock: Search stock videos (Pexels, Pixabay, Coverr)
        Stock-->>Worker: return video download URL
        Worker->>Worker: Download with retry session
        Worker->>FFmpeg: Normalise clip (scale, letterbox, fps, strip audio)
        Worker-->>Server: stdout progress (segment_done)
        Server-->>UI: SSE progress update
    end

    Worker-->>Server: stdout progress (review_ready)
    Server-->>UI: SSE status review_ready (Shows Review Panel)
    
    Note over UI: User adjusts keywords or clicks "Merge Now"
    UI->>Server: POST /api/video/merge
    Server->>Worker: Create outputs/.merge_trigger file
    
    Note over Worker: Detects .merge_trigger & breaks poll loop
    Worker->>FFmpeg: Attempt Concat Demuxer
    alt Concat demuxer fails
        Worker->>FFmpeg: Fallback to transcode concat (-filter_complex)
    end
    FFmpeg-->>Worker: raw_concat.mp4 created
    Worker->>FFmpeg: Mux raw_concat + final_episode.wav
    FFmpeg-->>Worker: final_video.mp4 created
    Note over Worker: Purge outputs/video/segments/raw cache
    Worker-->>Server: stdout progress (done)
    Server-->>UI: SSE status done (Displays Final Video)
```

---

## 4. Directory Manifest

Below is the file structure and organizational responsibilities across the studio project:

* **`/core`**: Core pipeline modules.
  * `audio.py`: Houses Kokoro TTS inference wraps, EBU R128 audio normalization, and segment stitching.
  * `model.py`: Model checkpoint verification and automatic weights downloader from GitHub Releases.
  * `script.py`: Script line tag regex parsers to separate speech overrides `[voice:af_sarah]` from raw script strings.
  * `video.py`: Media download engines, stock video API bridges, keyword extractor prompts, and FFmpeg transcode wraps.
  * `worker.py`: Background worker script spawned to perform sequential voice synthesis.
  * `video_worker.py`: Background worker script spawned to query keywords, download B-roll files, scale/pad segments, and perform final merging.
* **`/web`**: Pure vanilla HTML/CSS/JS frontend dashboard assets.
  * `index.html`: Responsive 3-column workspace structure and Stats drawer.
  * `style.css`: Glassmorphic dark styling.
  * `app.js`: Master JS coordinator mapping SSE streams, preview synchronization, and state management.
* **`/outputs`**: Local generated outputs and pipeline configs.
  * `/chunks/`: Houses individual generated WAV voice chunks.
  * `/video/segments/`: Houses scaled video B-roll clips (`segment_XXXX.mp4`).
  * `/video/segments/raw/`: Temporary stock downloads cache (automatically deleted on success).
  * `final_episode.wav`: Stitched, EBU R128 normalized master audio track.
  * `final_video.mp4`: Merged B-roll video with master voiceover.
  * `.groq_stats.json`: Internal stats database logging rotating API key metrics.
  * `history.json`: Archives of past generations.

---

## 5. JSON Schema & SSE Payload Specifications

### A. Groq Statistics Data (`outputs/.groq_stats.json`)
```json
{
  "gsk_key1prefix...": {
    "calls": 24,
    "success_calls": 23,
    "rate_limits": 1,
    "status": "active",
    "last_used": "2026-07-04T08:24:12Z"
  },
  "gsk_key2prefix...": {
    "calls": 12,
    "success_calls": 12,
    "rate_limits": 0,
    "status": "active",
    "last_used": "2026-07-04T08:25:01Z"
  }
}
```

### B. Live SSE Progress Stream Structure
Child worker processes write JSON strings to standard output, which the FastAPI server parses and streams to the client via Server-Sent Events (SSE):
```json
{
  "event": "status",
  "status": "generating",
  "message": "Voicing segment 3 of 8...",
  "current_chunk": 3,
  "total_chunks": 8
}
```

---

## 6. FFmpeg Codec & Command Reference

### A. Audio Segment Stitching with Silence Padding
Concats individual wav segments while inserting standard silent pauses (e.g., 0.5s gaps):
```bash
ffmpeg -y -i chunk_0000.wav -f lavfi -i anullsrc=r=24000:cl=mono -filter_complex "[0:a][1:a]concat=n=2:v=0:a=1[out]" -map "[out]" output.wav
```

### B. Standardized B-Roll Normalization (`_scale_clip`)
Forces mismatched stock video aspects or sizes into a consistent aspect ratio, resolution, and frame rate without audio streams:
```bash
ffmpeg -y -i raw.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30" -c:v libx264 -preset ultrafast -crf 28 -an standardized.mp4
```

### C. Concat Demuxer Fast Stitching
Lossless merge of pre-scaled video segments:
```bash
ffmpeg -y -f concat -safe 0 -i concat_file.txt -c:v libx264 -preset ultrafast -crf 28 -an output.mp4
```

### D. Transcode `-filter_complex` Fallback
Triggered dynamically if the concat demuxer fails due to custom uploaded content or frame rate mismatches:
```bash
ffmpeg -y -i segment_0000.mp4 -i segment_0001.mp4 -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0[outv]" -map "[outv]" -c:v libx264 -preset ultrafast -crf 28 output.mp4
```

---

## 7. Playback Micro-Sync Engine (Frontend)

To allow real-time previewing of segment B-rolls alongside their matching voiceovers, `web/app.js` runs a drift-checking loop:

1. **Trigger**: When a user clicks preview, both the video element and the audio element (`chunk_XXXX.wav`) are started simultaneously. The video track is muted.
2. **Monitoring**: A `timeupdate` listener continuously compares the current playhead locations:
   $$\text{Drift} = | \text{Audio.currentTime} - \text{Video.currentTime} |$$
3. **Adjustment**: If $\text{Drift} > 0.150\text{ seconds}$ (150ms):
   * If the audio is lagging, the video is paused momentarily until the audio catches up.
   * If the audio is leading, the audio's `currentTime` is adjusted to match the video's active playhead, restoring perfect alignment.
