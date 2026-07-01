# Narrator

Local AI voice generator for long-form narration and audiobook-style content. Runs entirely on-device using Apple Silicon (MLX) with the Qwen3-TTS model — no cloud APIs, no subscriptions.

---

## Features

- **Batch generation** — turn a full script into a single stitched audio file
- **Single clip mode** — quickly test a piece of text
- **Voice comparison** — generate the same text with all 9 available voices
- **Voice cloning** — use a reference WAV to clone a custom voice
- **Auto-resume** — interrupted batch runs pick up where they left off
- **Emotion control** — instruct the model with tone, pacing, and emotional arc

---

## Requirements

| Dependency | Version | Notes |
|------------|---------|-------|
| macOS | Apple Silicon (M1/M2/M3/M4) | Required for MLX |
| Python | 3.11+ | |
| mlx-audio | 0.4.4+ | `pip install mlx-audio` |
| ffmpeg | 7.0+ | `brew install ffmpeg` |

> **Memory:** The 1.7B model uses ~11 GB peak RAM during generation. 16 GB Macs will work but may swap. 24+ GB recommended for comfortable batch runs.

---

## Project Structure

```
narrator/
├── config.py              # All settings (voice, speed, paths, emotion)
├── core/
│   ├── __init__.py
│   ├── model.py           # TTS model loading
│   ├── audio.py           # Chunk generation + WAV stitching
│   └── script.py          # Script file parsing
├── generate_batch.py      # CLI: script.txt → full episode audio
├── generate_single.py     # CLI: inline text → single clip
├── test_voices.py         # CLI: compare all voices side by side
├── script.txt             # Your narration script
├── ref/
│   ├── ref_voice_male.wav
│   └── ref_voice_female.wav
├── models/
│   └── 1.7B-CustomVoice/  # Qwen3-TTS model weights
└── outputs/               # Generated audio files
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
pip install mlx-audio
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

---

## Usage

### Generate a full episode (batch mode)

This is the main workflow. Write your script, run the generator, get a single stitched audio file.

**Step 1 — Write your script in `script.txt`:**

```
The day Paul Reston shook my hand, I believed him. That was my first mistake.

I came to Hargrove & Associates three years out of Northwestern with a finance degree.

Paul hired me out of a pool of forty-seven candidates.
```

> **Format:** Each non-empty line = one chunk. Blank lines are separators (ignored). Keep each line under ~200 words for best quality.

**Step 2 — Run:**

```bash
python3 generate_batch.py
```

**Step 3 — Output:**

```
outputs/
├── final_episode.wav      # Stitched full audio
└── chunks/
    ├── chunk_0000.wav     # Individual chunks (for debugging)
    ├── chunk_0001.wav
    └── chunk_0002.wav
```

**Step 4 — Play:**

```bash
afplay outputs/final_episode.wav
```

#### Auto-resume

If the process is interrupted (crash, Ctrl+C, etc.), just run the same command again. Already-generated chunks in `outputs/chunks/` are detected and skipped automatically. Only remaining chunks are generated, then everything is stitched.

#### Re-generating from scratch

To start fresh, delete the chunks directory first:

```bash
rm -rf outputs/chunks/
python3 generate_batch.py
```

---

### Generate a single clip

For quick testing or one-off generation. Edit the text directly inside `generate_single.py`:

```python
TEXT = """\
She had been my best friend for twelve years.
I trusted her with everything — my secrets, my dreams, my darkest fears.\
"""

OUTPUT = "outputs/test_output.wav"
```

Then run:

```bash
python3 generate_single.py
```

Output: `outputs/test_output.wav`

---

### Compare all voices

Generate the same sample text with every available voice to find the best one for your project:

```bash
python3 test_voices.py
```

Output:

```
voice_tests/
├── serena.wav
├── vivian.wav
├── uncle_fu.wav
├── ryan.wav
├── aiden.wav
├── ono_anna.wav
├── sohee.wav
├── eric.wav
└── dylan.wav
```

Listen to each and update `VOICE` in `config.py` with your choice.

---

## Configuration

All settings live in a single file: **`config.py`**

| Setting | Default | Description |
|---------|---------|-------------|
| `MODEL_PATH` | `models/1.7B-CustomVoice` | Path to the Qwen3-TTS model |
| `VOICE` | `aiden` | Voice preset to use |
| `REF_AUDIO` | `ref/ref_voice_male.wav` | Reference audio for voice cloning |
| `REF_TEXT` | *(transcript)* | Exact transcript of the reference audio |
| `SPEED` | `1.0` | Playback speed multiplier |
| `EMOTION` | *(see below)* | Emotional/style instruction for the model |
| `SCRIPT_FILE` | `script.txt` | Input script file for batch mode |
| `OUTPUT_FILE` | `outputs/final_episode.wav` | Final stitched output path |
| `CHUNKS_DIR` | `outputs/chunks` | Directory for individual chunks |

### Emotion / Instruct

The `EMOTION` string controls the model's tone, pacing, and emotional delivery. Examples:

```python
# Cinematic narration
EMOTION = (
    "Deep, serious, and emotionally controlled. Speak slowly with gravitas "
    "and natural pauses. Begin calm and reflective, gradually build tension."
)

# Warm and conversational
EMOTION = (
    "Warm, friendly, and approachable. Speak at a natural pace with "
    "gentle emphasis. Sound like you're telling a story to a close friend."
)

# News anchor
EMOTION = (
    "Professional and authoritative. Clear enunciation, steady pacing, "
    "neutral tone. Emphasize key facts without emotional coloring."
)

# Thriller / suspense
EMOTION = (
    "Tense and urgent. Start with a whisper, build intensity. "
    "Short pauses for suspense. Controlled fear in the voice."
)
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

> Tip: Run `python3 test_voices.py` to hear them all and pick the best fit.

---

## Script Writing Tips

### Formatting

- **One line = one chunk.** The model generates each line independently.
- **Blank lines** between chunks are ignored (use them for readability).
- Keep each chunk under **~200 words** for consistent quality.
- Longer lines are fine but may have slight pacing drift.

### For best results

- Write in full sentences with natural punctuation.
- Use em dashes (—) for dramatic pauses.
- Use ellipsis (...) for trailing off.
- Avoid abbreviations — write "Mister" not "Mr."
- Spell out numbers in narration — "forty-seven" not "47".
- Start a new line at natural scene or paragraph breaks.

### Example `script.txt`

```
The day Paul Reston shook my hand and called me the most talented analyst he'd ever worked with, I believed him. That was my first mistake.

I came to Hargrove & Associates three years out of Northwestern with a finance degree, a minor in statistics, and the kind of focus that made my college roommates call me "the monk."

Paul hired me out of a pool of forty-seven candidates. I know because he told me, more than once, usually when he wanted me to feel grateful.
```

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
