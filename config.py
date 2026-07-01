# ============================================================
# config.py — Shared configuration for the Narrator project
# ============================================================

# ── Model ─────────────────────────────────────────────────────
MODEL_PATH = "models/1.7B-CustomVoice"

# ── Voice ─────────────────────────────────────────────────────
VOICE = "aiden"

# ── Reference audio for voice cloning ─────────────────────────
REF_AUDIO = "ref/ref_voice_male.wav"
REF_TEXT = (
    "The day Paul Reston shook my hand and called me the most talented "
    "analyst he'd ever worked with, I believed him."
)

# ── Generation settings ──────────────────────────────────────
SPEED = 1.0
EMOTION = (
    "Deep, serious, and emotionally controlled. Speak slowly with gravitas "
    "and natural pauses. Begin calm and reflective, gradually build tension, "
    "express genuine hurt without melodrama, become intense during betrayal "
    "scenes, then finish with quiet confidence and emotional resolution."
)

# ── Audio pipeline ───────────────────────────────────────────
SILENCE_PADDING = 0.8       # seconds of silence between chunks
NORMALIZE_AUDIO = True      # EBU R128 loudness normalization
EXPORT_MP3 = True           # also export MP3 alongside WAV
SAMPLE_RATE = 24000         # sample rate for generated silence

# ── Paths ────────────────────────────────────────────────────
SCRIPT_FILE = "script.txt"
OUTPUT_FILE = "outputs/final_episode.wav"
CHUNKS_DIR = "outputs/chunks"
REF_DIR = "ref"

# ── Web server ───────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000

# ── All available voices ─────────────────────────────────────
VOICES = [
    "aiden",
    "ryan",
    "eric",
    "dylan",
    "serena",
    "vivian",
    "ono_anna",
    "sohee",
    "uncle_fu",
]
