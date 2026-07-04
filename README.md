# Resonate AI Studio 🎙️

Local, production-grade AI voice narration and automated cinematic B-Roll video studio. Powered by **Kokoro-82M ONNX** for instant, studio-quality human voice synthesis, and integrated with context-aware visual B-Roll generation. Runs entirely on-device with zero subscriptions, zero cloud APIs, and zero configuration.

---

## 🚀 Key Features

* **AI Voice Advisor (Voice Suggestion)**: Paste a short summary description of your narrative character, emotional arc, and pacing. The local intelligent advisor immediately suggests the optimal voice profile, emotion preset, speed, and custom tone prompt, applying them instantly to your session.
* **Voice Browser (Rich Picker Modal)**: Visual search and category filters (US/UK, Male/Female) across all 28 studio voice profiles. Play instant sample audio previews and apply narrator profiles with a single click.
* **Pro 3-Column Layout**: A modern, percentage-based grid layout:
  * **20% Width Left Panel**: Studio settings (Pipeline Mode, Narrators, Emotion tags, Pacing, Aspect Ratios, Clip Intervals).
  * **50% Width Middle Workspace**: High-performance script text editor with live gutter numbers, word counters, and quick speaker tag insertion shelf.
  * **30% Width Output Console**: Controls for starting/cancelling generation, detailed progress timelines, interactive Segment Previewer, and the master audio playback suite.
* **Interactive Statistics Drawer (`📊 Stats`)**: A sliding console displaying real-time statistics:
  * **Groq API Counters**: Total requests made, successful completions, and rate limits (429) hit.
  * **Rotating Keys Status**: Tracking pool prefixes, current status (Active vs. Rate-limited), call counts, and relative time since the last call for all 7 keys.
  * **Disk Resources Table**: Current script word count, output segments count, video segments size, and local B-roll raw video cache size.
  * **Stock Integration**: Connected APIs status (Pexels, Pixabay, Coverr).
* **Audio-Synced Segment Previews**: Clicking on a generated clip plays both the B-roll footage and the matching voiceover WAV chunk (`chunk_XXXX.wav`) simultaneously. Features an auto-alignment sync listener (150ms tolerance) that adjusts playback speeds to keep narration and visuals locked in.
* **Automatic Multi-Key Groq Rotation**: Completely removed Gemini and RAKE. The pipeline extracts visual search queries using **only Groq** (Llama-3.3-70B). Up to 7 keys can be pasted comma-separated inside the env variables or the settings drawer; if any key hits a 429 rate limit, it rotates instantly to the next active key.

---

## 🛠️ Production-Grade Robustness Upgrades

* **HTTP Retry Session Adapter**: Integrated requests-based exponential backoff retry sessions for media downloads, preventing transient network drops (500/502/503/504) or stock API rate limits (429) from halting the pipeline.
* **FFmpeg Transcode Concat Fallback**: If the fast, lossless `concat` demuxer fails (due to custom clip uploads or codec mismatch), the system automatically executes a fallback transcoding `-filter_complex` merge to guarantee a compiled output video.
* **Disk Space Cache Purging**: The background video worker automatically deletes the temporary downloads directory (`outputs/video/segments/raw`) after a successful compilation, saving gigabytes of local storage.
* **Generative Cache Flushing**: Starting a new generation clears out the previous `.wav` chunks inside `outputs/chunks/` and deletes the old `outputs/final_episode.wav`/`final_video.mp4` to prevent leaks or overlapping audios.
* **Playback Cache-Busting**: The frontend player appends a dynamic timestamp query parameter (`?t=Date.now()`) to the master audio URL on play, forcing the browser to fetch the freshly stitched narration instead of playing cached memory blocks.
* **Subprocess Deadlock Prevention**: Set subprocess execution parameters to inherit parent streams (`stderr=None`) instead of piping stdout/stderr into unconsumed buffers, eliminating python pipe deadlock freezes.

---

## System Workflow

```
[ Script Editor ] ➔ 🎙 Kokoro-82M ONNX ➔ [ WAV Chunks ] ➔ 🎛 Silence & Stitch ➔ [ final_episode.wav ]
                                                                                   │
[ final_video.mp4 ] 🏓 Concat / Filter Fallback ⚡ Rotating Groq Keywords ➔ [ Auto-Archive / History ]
```

1. **Kokoro-82M ONNX Engine**: High-performance ONNX implementation of Kokoro-82M. It loads instantly, runs CPU/GPU, and produces hyper-realistic voice synthesis.
2. **Pipeline Mode Selector**:
   - 🎙 **Audio Only**: Generates narration speech audio files.
   - ✨ **Both**: Generates high-quality audio, then immediately searches, downloads, and stitches B-Roll clips to render a finished video.
   - 🎬 **Video Only**: Skips the audio synthesis step and builds B-Roll matching your existing audio track.

---

## Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| macOS / Win / Linux | Any | Runs locally on CPU/GPU via ONNX |
| Python | 3.10+ | Tested on Python 3.11 |
| kokoro-onnx | 0.5.0+ | `pip install kokoro-onnx` |
| soundfile | 0.12+ | Handles high-fidelity audio writing |
| FastAPI | 0.110+ | Web dashboard backend |
| requests | 2.31+ | Handles API calls and retry sessions |
| ffmpeg | 7.0+ | stitch WAVs and merge B-roll clips |

---

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url> narrator
cd narrator
```

### 2. Set up Virtual Environment & Dotenv

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the root directory:

```env
PEXELS_API_KEY=your_pexels_key
PIXABAY_API_KEY=your_pixabay_key
COVERR_API_KEY=your_coverr_key
GROQ_API_KEYS=key_1,key_2,key_3,key_4,key_5,key_6,key_7
```

*(Ensure `ffmpeg` is installed on your system. For macOS: `brew install ffmpeg`)*

### 3. Model Weights Auto-Download

The application checks for weights on startup. The first time you generate audio, it will automatically pull the files from GitHub Releases and place them in:
- `models/kokoro/kokoro-v1.0.onnx` (~300MB)
- `models/kokoro/voices-v1.0.bin` (~27MB)

Run the server:
```bash
python3 server.py
```
Open [http://localhost:8000](http://localhost:8000) in your browser.

---

## Audio Generation & Styling Guide

Kokoro is a style-based model that derives its emotion, speed, and pausing directly from **punctuation, spacing, and voice presets**. Below is a complete guide to generating the most human-like delivery.

### 1. Controlling Prosody & Emotions via Punctuation

Kokoro is highly sensitive to text structure. You can design custom emotional pacing using standard punctuation:

*   **Commas (`,`)**: Creates a natural, short pause (approx. 200–300ms). Perfect for breathing breaks.
*   **Periods (`.`) / Em-Dashes (`—`)**: Triggers longer, dramatic pauses (approx. 500–800ms) to let thoughts settle.
*   **Ellipses (`...` or `…`)**: Forces a soft, trailing-off pause. Excellent for suspenseful transitions.
*   **Exclamation Marks (`!`)**: Inject energy and emphasis into the sentence, raising the emotional peak.
*   **Question Marks (`?`)**: Elevate the pitch contour towards the end of the sentence for a realistic questioning lift.

### 2. Script Example with Emotional Tags & Presets

You can format your script in the workspace to target specific voices per line:

```text
The day Paul Reston shook my hand and called me the most talented analyst he'd ever worked with, I believed him. 

[voice:am_adam] That was my first mistake. 

[voice:af_bella] My second was letting him be the only person in that building... who knew exactly how good I was.

[voice:bf_emma] Did you really think you could get away with it? 
```

*   **Inline Speakers**: Add `[voice:voice_id]` at the beginning of any line to change speakers on the fly.
*   **Optimal Speed**: Adjust the speed slider between **0.95x and 1.05x**. Values below 1.0x make the voice sound more reflective and serious; values above 1.0x sound more urgent and conversational.

---

## Available Kokoro Voices

You can choose from 28 studio-grade voices directly in the Web UI:

| Gender / Accent | Voice ID | Description |
|-----------------|----------|-------------|
| **US Female**   | `af_sarah` | Soft & narrative |
|                 | `af_bella` | Expressive & warm |
|                 | `af_heart` | Warm & friendly |
|                 | `af_nicole` | Clear & professional |
|                 | `af_sky` | Bright & energetic |
|                 | `af_alloy` | Balanced & natural |
|                 | `af_aoede` | Narrative storyteller |
|                 | `af_jessica`| Crisp & articulate |
|                 | `af_kore` | Sweet & gentle |
|                 | `af_nova` | High-energy |
|                 | `af_river` | Calm & conversational |
| **US Male**     | `am_adam` | Deep & cinematic |
|                 | `am_michael`| Natural & relaxed |
|                 | `am_fenrir` | Rich & authoritative |
|                 | `am_puck` | Animated & lively |
|                 | `am_echo` | Corporate presenter |
|                 | `am_eric` | Conversational |
|                 | `am_liam` | Friendly & warm |
|                 | `am_onyx` | Deep authority |
|                 | `am_santa` | Festive & classic |
| **UK Female**   | `bf_alice` | Gentle & narrative |
|                 | `bf_emma` | Elegant & polished |
|                 | `bf_isabella`| Storyteller |
|                 | `bf_lily` | Bright |
| **UK Male**     | `bm_daniel` | Warm |
|                 | `bm_fable` | Dramatic |
|                 | `bm_george` | Classic & formal |
|                 | `bm_lewis` | Conversational |

---

## Project Structure

```
narrator/
├── config.py              # Configuration (Voices, paths, video APIs)
├── server.py              # FastAPI server orchestrator
├── architecture.md        # Mermaid workflows and subprocess diagrams
├── core/
│   ├── model.py           # Kokoro-ONNX loader & auto-downloader
│   ├── audio.py           # Synthesis, normalization, stitching, MP3
│   ├── script.py          # Script tag parsers
│   └── video.py           # B-Roll video extraction & stitching engine
├── web/
│   ├── index.html         # Workspace dashboard interface
│   ├── style.css          # Glassmorphic dark styling
│   └── app.js             # SSE state manager & mode selector UI
├── voice_tests/           # Folder containing generated voice previews (gitignored)
└── requirements.txt       # Project python dependencies
```
