# ============================================================
# core/model.py — TTS model loading
# ============================================================

import os
import warnings

os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore")

from mlx_audio.tts.utils import load_model


def load_tts_model(model_path: str):
    """Load and return the Qwen3 TTS model.

    Handles environment setup, warning suppression, and status output.
    """
    print("Loading model...")
    model = load_model(model_path)
    print("Model loaded ✓")
    return model
