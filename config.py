# ============================================================
# config.py — Shared configuration for the Narrator project
# ============================================================

# Model
MODEL_PATH = "models/1.7B-CustomVoice"

# Voice
VOICE = "aiden"

# Reference audio for voice cloning
REF_AUDIO = "ref/ref_voice_male.wav"
REF_TEXT = (
    "The day Paul Reston shook my hand and called me the most talented "
    "analyst he'd ever worked with, I believed him."
)

# Generation settings
SPEED = 1.0
EMOTION = (
    "Deep, serious, and emotionally controlled. Speak slowly with gravitas "
    "and natural pauses. Begin calm and reflective, gradually build tension, "
    "express genuine hurt without melodrama, become intense during betrayal "
    "scenes, then finish with quiet confidence and emotional resolution."
)

# Paths
SCRIPT_FILE = "script.txt"
OUTPUT_FILE = "outputs/final_episode.wav"
CHUNKS_DIR = "outputs/chunks"

# All available voices for testing
VOICES = [
    "serena",
    "vivian",
    "uncle_fu",
    "ryan",
    "aiden",
    "ono_anna",
    "sohee",
    "eric",
    "dylan",
]
