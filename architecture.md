# 🏗️ Resonate AI Studio Architecture & Flow Diagrams

This document details the architectural design, component interactions, data flows, and concurrency protections of the Resonate AI voice and video generation studio.

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

## 4. Key Component Definitions

### A. Subprocess Pipe Communication
* Subprocesses write standard progress lines to standard output:
  `print(json.dumps({"event": "status", "status": "generating", "message": "..."}), flush=True)`
* The server reads standard output asynchronously line-by-line:
  `line = await _video_worker_process.stdout.readline()`
* To prevent deadlocks, child processes inherit the parent's error output (`stderr=None`), which outputs warning logs directly to the main terminal console instead of plugging a capped pipe buffer.

### B. Dynamic Groq Key Rotation Pool
* Keeps a state tracker in `outputs/.groq_stats.json`.
* If a request throws `HTTP 429` (Rate Limited), the extraction loop catches the exception, updates the key's state in the stats file, and seamlessly retries the API request with the next active key prefix.

### C. Standardized FFmpeg Normalization (`_scale_clip`)
* To ensure that the fast demuxer concat doesn't crash, every downloaded raw file is scaled, padded, and frame-rate aligned:
  ```bash
  ffmpeg -y -i raw.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30" -c:v libx264 -preset ultrafast -crf 28 -an standardized.mp4
  ```
