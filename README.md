# Narrator

Local, production-grade AI voice studio and B-Roll video generator. Powered by **Kokoro-82M ONNX** for instant, studio-quality human voice synthesis, and integrated with an automated B-Roll video generator. Runs entirely on-device with zero-subscription, zero cloud APIs, and zero configuration.

---

## What We Implemented & How It Works

This project features a fully automated workflow that handles script writing, voice generation, visual B-roll selection, and final video editing:

```
[ Your Script ] ➔ 🎙 Kokoro-82M ONNX ➔ [ Audio Chunks ] ➔ 🎛 Silence & Stitch ➔ [ final_audio.wav ]
                                                                                   │
[ final_video.mp4 ] 🏓 Multi-Clip Merge 🏓 Keyword Search (Gemini/Pexels) 🏓 Auto-Start B-Roll (Optional)
```

1. **Kokoro-82M ONNX Engine**: Replaced the heavy, slow MLX Qwen3-TTS engine with a lightweight, high-performance ONNX implementation of Kokoro-82M. It loads instantly, runs seamlessly on CPU or GPU, and produces hyper-realistic, human-like voice synthesis.
2. **28 English Voice Profiles**: Expanded the active voice database to include 28 premium English voices grouped by region (US/UK) and narrative tone (soft, expressive, rich, conversational).
3. **Pipeline Mode Selector**: A dynamic controller that allows you to target your output format:
   - 🎙 **Audio Only**: Generates narration speech audio files. Hides video controls to keep the studio clean.
   - ✨ **Both**: Generates high-quality audio, then immediately starts search & download of context-aware B-Roll clips, rendering a finished video automatically.
   - 🎬 **Video Only**: Skips the audio synthesis step and builds B-Roll matching your existing output audio.
4. **Scrollable Output Console**: Restructured the layout to keep control panel triggers fixed on screen, hosting all segment results, playback controls, and rendering players in a space-maximized, scrollable history container.

---

## Features

- **Web Dashboard** — browser workspace with a custom line-numbered script editor, live progress streams, and embedded media players.
- **28 High-Fidelity Studio Voices** — US and UK accents, male and female voices, ranging from deep cinematic to warm conversational.
- **Dynamic Mode Switching** — toggle between Audio Only, Video Only, or Both.
- **Visual B-Roll Integration** — automatically parses your script keywords (offline or via free Gemini Flash) to pull, stitch, and pad orientation-aware footage.
- **Acoustic Engineering** — EBU R128 loudness normalization, custom silence gap padding, and automatic WAV/MP3 conversion.

---

## Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| macOS / Win / Linux | Any | Works on standard CPUs/GPUs via ONNX |
| Python | 3.10+ | |
| kokoro-onnx | 0.5.0+ | `pip install kokoro-onnx` |
| onnxruntime | 1.16+ | Runs the Kokoro model |
| soundfile | 0.12+ | Handles high-fidelity audio writing |
| FastAPI | 0.110+ | Web dashboard backend |
| ffmpeg | 7.0+ | Required for audio stitching and video merging |

---

## Setup

### 1. Clone the repo

```bash
git clone <your-repo-url> narrator
cd narrator
```

### 2. Set up Virtual Environment

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

*(Ensure `ffmpeg` is installed on your system. For macOS: `brew install ffmpeg`)*

### 3. Model Weights Auto-Download

You do not need to download the models manually! The application checks for weights on startup. The first time you generate audio, it will automatically pull the files from GitHub Releases and place them in the correct directories:
- `models/kokoro/kokoro-v1.0.onnx` (~300MB)
- `models/kokoro/voices-v1.0.bin` (~27MB)

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

You can format your script in the workspace to target specific voices per line. 

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
├── core/
│   ├── model.py           # Kokoro-ONNX loader & auto-downloader
│   ├── audio.py           # Synthesis, normalization, stitching, MP3
│   ├── script.py          # Script tag parsers
│   └── video.py           # B-Roll video extraction & stitching engine
├── server.py              # FastAPI server orchestrator
├── web/
│   ├── index.html         # Workspace dashboard interface
│   ├── style.css          # Glassmorphic dark styling
│   └── app.js             # SSE state manager & mode selector UI
├── voice_tests/           # Folder containing generated voice previews (gitignored)
└── requirements.txt       # Project python dependencies
```

---

## Troubleshooting

### Generation stalls on "Loading Kokoro ONNX Engine"
- The first generation downloads ~327MB of weights from GitHub releases. Ensure you have an active internet connection.
- Check the terminal logs to monitor the download percentages.

### "Audio overlaps or cuts off"
- Keep chunks bounded by scene breaks. Extremely long run-on lines can lead to pacing issues. Break your script into distinct lines in the editor.

### "Stitch failed"
- Ensure `ffmpeg` is in your system path: run `ffmpeg -version` in terminal.
