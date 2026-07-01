# Narrator

Local AI voice generator for long-form narration and audiobook-style content. Runs entirely on-device using Apple Silicon (MLX) with the Qwen3-TTS model — no cloud APIs, no subscriptions.

---

## Features

- **Web Dashboard** — live browser UI with script editor, real-time progress, audio player
- **Batch generation** — turn a full script into a single stitched audio file
- **Single clip mode** — quickly test a piece of text
- **Voice comparison** — generate the same text with all 9 available voices
- **Voice cloning** — use a reference WAV to clone a custom voice
- **Per-chunk overrides** — change voice or emotion on any line with `[voice:X]` `[emotion:X]` tags
- **Silence padding** — configurable pause between chunks for natural pacing
- **Loudness normalization** — EBU R128 standard for consistent volume
- **MP3 export** — auto-convert final output alongside WAV
- **Auto-resume** — interrupted batch runs pick up where they left off
- **Reference voice upload** — drag-and-drop new voice files in the web UI

---

## Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| macOS | Apple Silicon (M1/M2/M3/M4) | Required for MLX |
| Python | 3.11+ | |
| mlx-audio | 0.4.4+ | `pip install mlx-audio` |
| FastAPI | 0.100+ | `pip install fastapi uvicorn` |
| ffmpeg | 7.0+ | `brew install ffmpeg` |

> **Memory:** The 1.7B model uses ~11 GB peak RAM during generation. 16 GB Macs will work but may swap. 24+ GB recommended for comfortable batch runs.

---

## Project Structure

```
narrator/
├── config.py              # All settings (voice, speed, paths, pipeline)
├── core/
│   ├── __init__.py
│   ├── model.py           # TTS model loading
│   ├── audio.py           # Generation, stitching, normalization, MP3
│   └── script.py          # Script parsing with per-chunk overrides
├── server.py              # FastAPI web dashboard backend
├── web/
│   ├── index.html         # Dashboard UI
│   ├── style.css          # Dark glassmorphism theme
│   └── app.js             # Client-side logic + SSE
├── generate_batch.py      # CLI: script.txt → full episode audio
├── generate_single.py     # CLI: inline text → single clip
├── test_voices.py         # CLI: compare all voices side by side
├── script.txt             # Your narration script
├── ref/                   # Reference voice files
├── models/                # TTS model weights (gitignored)
└── outputs/               # Generated audio (gitignored)
```

---

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url> narrator
cd narrator
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install mlx-audio fastapi uvicorn python-multipart
```

### 4. Install ffmpeg (if not already installed)

```bash
brew install ffmpeg
```

### 5. Download the model

Download the Qwen3-TTS-12Hz-1.7B model with CustomVoice support and place it in the `models/` directory:

```
models/
└── 1.7B-CustomVoice/
    ├── config.json
    ├── model.safetensors
    ├── tokenizer_config.json
    ├── vocab.json
    ├── merges.txt
    ├── speech_tokenizer/
    └── ...
```

### 6. Add a reference voice (for voice cloning)

Place your reference WAV file in the `ref/` directory. The reference audio should be:

- **5–15 seconds** of clear speech
- **Single speaker**, no background noise
- **WAV format**, any sample rate (22050 Hz recommended)

Update `config.py` with the matching transcript:

```python
REF_AUDIO = "ref/ref_voice_male.wav"
REF_TEXT = "Exact transcript of what is spoken in the reference audio."
```

Or upload via the web dashboard (see below).

---

## Usage

### 🖥️ Web Dashboard (recommended)

The web dashboard gives you a full visual interface to write scripts, configure settings, generate audio, and play results — all in the browser.

**Start the server:**

```bash
python3 server.py
```

**Open in browser:**

```
http://127.0.0.1:8000
```

#### Dashboard Features

| Area | What it does |
|------|-------------|
| **Script Editor** | Write/edit your narration with line numbers. Each line = one chunk. |
| **Voice & Style** | Pick voice, adjust speed, write emotion instructions |
| **Audio Pipeline** | Set silence padding, toggle normalization and MP3 export |
| **Reference Voice** | See current ref, upload new voices via drag-and-drop |
| **Generate** | Click to start batch generation with real-time progress bar |
| **Chunk List** | See all generated chunks, click to play individual ones |
| **Audio Player** | Play the final stitched output, seek, download WAV/MP3 |

#### Real-time Progress

Generation progress is streamed live via Server-Sent Events (SSE):
- Progress bar updates as each chunk completes
- Chunk pills appear with duration and timing info
- Status indicator shows model state (loading/generating/done)
- You can cancel mid-generation with the Stop button

#### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+S` / `Ctrl+S` | Save script |

---

### Generate a full episode (CLI)

**Step 1 — Write your script in `script.txt`:**

```
The day Paul Reston shook my hand, I believed him. That was my first mistake.

I came to Hargrove & Associates three years out of Northwestern with a finance degree.

[voice:serena] [emotion:Whispered, fearful] I heard footsteps behind me.

Paul hired me out of a pool of forty-seven candidates.
```

> **Format:** Each non-empty line = one chunk. Blank lines are separators (ignored). Use `[voice:X]` and `[emotion:X]` tags to override per line.

**Step 2 — Run:**

```bash
python3 generate_batch.py
```

**Step 3 — Output:**

```
outputs/
├── final_episode.wav      # Stitched full audio (normalized)
├── final_episode.mp3      # MP3 version (if enabled)
└── chunks/
    ├── chunk_0000.wav
    ├── chunk_0001.wav
    └── ...
```

**Step 4 — Play:**

```bash
afplay outputs/final_episode.wav
```

#### Auto-resume

If the process is interrupted, just re-run the same command. Already-generated chunks are detected and skipped automatically.

#### Re-generating from scratch

```bash
rm -rf outputs/chunks/
python3 generate_batch.py
```

---

### Generate a single clip (CLI)

Edit the text directly inside `generate_single.py`, then run:

```bash
python3 generate_single.py
```

Output: `outputs/test_output.wav`

---

### Compare all voices (CLI)

```bash
python3 test_voices.py
```

Output: `voice_tests/` with one WAV per voice. Listen to each and update `VOICE` in `config.py`.

---

## Configuration

All settings live in **`config.py`**. The web dashboard also lets you change these at runtime.

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL_PATH` | `models/1.7B-CustomVoice` | Path to the Qwen3-TTS model |
| `VOICE` | `aiden` | Voice preset to use |
| `REF_AUDIO` | `ref/ref_voice_male.wav` | Reference audio for voice cloning |
| `REF_TEXT` | *(transcript)* | Exact transcript of the reference audio |
| `SPEED` | `1.0` | Playback speed multiplier |
| `EMOTION` | *(see below)* | Emotional/style instruction for the model |
| `SILENCE_PADDING` | `0.8` | Seconds of silence between chunks |
| `NORMALIZE_AUDIO` | `True` | EBU R128 loudness normalization |
| `EXPORT_MP3` | `True` | Also export MP3 alongside WAV |
| `SCRIPT_FILE` | `script.txt` | Input script file for batch mode |
| `OUTPUT_FILE` | `outputs/final_episode.wav` | Final stitched output path |
| `CHUNKS_DIR` | `outputs/chunks` | Directory for individual chunks |
| `SERVER_HOST` | `127.0.0.1` | Web dashboard host |
| `SERVER_PORT` | `8000` | Web dashboard port |

### Emotion / Instruct

The `EMOTION` string controls the model's tone, pacing, and emotional delivery. Examples:

```python
# Cinematic narration
EMOTION = "Deep, serious, and emotionally controlled. Speak slowly with gravitas and natural pauses."

# Warm and conversational
EMOTION = "Warm, friendly, and approachable. Speak at a natural pace like telling a story to a close friend."

# News anchor
EMOTION = "Professional and authoritative. Clear enunciation, steady pacing, neutral tone."

# Thriller / suspense
EMOTION = "Tense and urgent. Start with a whisper, build intensity. Short pauses for suspense."
```

### Per-Chunk Overrides

Change voice or emotion for specific lines using inline tags:

```
Normal narration line with default voice and emotion.

[voice:serena] This line uses Serena's voice instead.

[emotion:Whispered, fearful] This line uses a different emotion.

[voice:ryan] [emotion:Angry and intense] This combines both overrides.
```

### Available Voices

| Voice | Style |
|-------|-------|
| `aiden` | Male, deep, cinematic |
| `ryan` | Male, clear, neutral |
| `eric` | Male, warm |
| `dylan` | Male, young |
| `serena` | Female, smooth |
| `vivian` | Female, expressive |
| `ono_anna` | Female, calm |
| `sohee` | Female, soft |
| `uncle_fu` | Male, character voice |

---

## Script Writing Tips

### Formatting

- **One line = one chunk.** The model generates each line independently.
- **Blank lines** between chunks are ignored (use them for readability).
- Keep each chunk under **~200 words** for consistent quality.
- Use `[voice:X]` and `[emotion:X]` for per-line overrides.

### For best results

- Write in full sentences with natural punctuation.
- Use em dashes (—) for dramatic pauses.
- Use ellipsis (...) for trailing off.
- Avoid abbreviations — write "Mister" not "Mr."
- Spell out numbers in narration — "forty-seven" not "47".
- Start a new line at natural scene or paragraph breaks.

---

## Audio Pipeline

The audio pipeline runs automatically after all chunks are generated:

```
Chunks → Silence Padding → Stitch (ffmpeg) → Normalize (EBU R128) → MP3 Export
```

| Stage | Setting | What it does |
|-------|---------|-------------|
| Silence Padding | `SILENCE_PADDING = 0.8` | Inserts 0.8s of silence between chunks for natural pacing |
| Normalization | `NORMALIZE_AUDIO = True` | Applies EBU R128 loudness normalization (target -16 LUFS) |
| MP3 Export | `EXPORT_MP3 = True` | Converts final WAV to MP3 at 192kbps |

All settings are configurable in `config.py` or the web dashboard.

---

## Performance

Benchmarks on Apple Silicon (M-series, 16 GB RAM):

| Metric | Typical Value |
|--------|---------------|
| Model load time | ~30 seconds |
| Generation speed | ~0.7–0.9x real-time |
| 1 min of audio | ~60–90 seconds to generate |
| Peak memory | ~11 GB |
| 30 min episode | ~45–60 min total processing |

> Generation runs entirely on the Neural Engine / GPU via MLX. No internet connection needed after model download.

---

## Troubleshooting

### "Stitch failed or no chunks"
- Make sure `ffmpeg` is installed: `brew install ffmpeg`
- Check that `outputs/chunks/` contains `.wav` files

### Model loading errors
- Verify the model is at `models/1.7B-CustomVoice/` and contains `model.safetensors`
- Check available RAM — the model needs ~11 GB

### Web dashboard won't start
- Check that FastAPI is installed: `pip install fastapi uvicorn python-multipart`
- Check port 8000 isn't in use: `lsof -i :8000`

### Audio quality issues
- Try a shorter chunk (fewer words per line)
- Adjust the `EMOTION` instruction
- Test different voices with `test_voices.py`
- Ensure the reference audio is clean (no background noise, single speaker)

### Interrupted generation
- Just re-run the same command — it auto-resumes from the last completed chunk

---

## License

For personal use. The Qwen3-TTS model has its own license — check the model repository for terms.
