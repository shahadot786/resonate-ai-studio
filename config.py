# ============================================================
# config.py — Shared configuration for the Narrator project
# ============================================================

# ── Model ─────────────────────────────────────────────────────
MODEL_PATH = "models/kokoro/kokoro-v1.0.onnx"

# ── Voice ─────────────────────────────────────────────────────
VOICE = "af_sarah"

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
NORMALIZE_AUDIO = False     # EBU R128 loudness normalization
EXPORT_MP3 = False          # also export MP3 alongside WAV
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
    # American Female
    "af_sarah",
    "af_bella",
    "af_heart",
    "af_nicole",
    "af_sky",
    "af_alloy",
    "af_aoede",
    "af_jessica",
    "af_kore",
    "af_nova",
    "af_river",

    # American Male
    "am_adam",
    "am_michael",
    "am_fenrir",
    "am_puck",
    "am_echo",
    "am_eric",
    "am_liam",
    "am_onyx",
    "am_santa",

    # British Female
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",

    # British Male
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
]

# ── B-Roll Video Pipeline ────────────────────────────────────
import os as _os

# Load .env file if present (requires python-dotenv, falls back silently)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_os.path.join(_os.path.dirname(__file__), ".env"))
except ImportError:
    pass  # python-dotenv not installed — keys must be set as real env vars

PEXELS_API_KEY   = _os.getenv("PEXELS_API_KEY",  "")
PIXABAY_API_KEY  = _os.getenv("PIXABAY_API_KEY", "")
COVERR_API_KEY   = _os.getenv("COVERR_API_KEY",  "")
GROQ_API_KEYS    = [k.strip() for k in _os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]



# Video output settings
VIDEO_RESOLUTION    = "1920x1080"
VIDEO_FPS           = 30
VIDEO_DIR           = "outputs/video"
VIDEO_SEGMENTS_DIR  = "outputs/video/segments"
VIDEO_OUTPUT_FILE   = "outputs/video/final_video.mp4"

# Keyword extraction mode: forced to "groq" using rotating keys
KEYWORD_MODE        = "groq"


# Clip interval: force a new clip search every N seconds within a long segment.
# Set to 0 to disable (one clip per chunk, looped if needed).
VIDEO_CLIP_INTERVAL = 10

# Review before merge: pause pipeline after all clips are found so you can
# preview and replace clips before the final video is assembled.
VIDEO_REVIEW_BEFORE_MERGE = True
