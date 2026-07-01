# ============================================================
# core/model.py — TTS model loader (Kokoro-TTS via ONNX)
# ============================================================

import os
import urllib.request

MODEL_DIR = "models/kokoro"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

MODEL_PATH = os.path.join(MODEL_DIR, "kokoro-v1.0.onnx")
VOICES_PATH = os.path.join(MODEL_DIR, "voices-v1.0.bin")

def download_file(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"Downloading {url} to {dest}...")
    
    # Simple chunked download with progress reporting
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response, open(dest, "wb") as out_file:
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        block_size = 1024 * 1024 # 1MB
        
        while True:
            buffer = response.read(block_size)
            if not buffer:
                break
            downloaded += len(buffer)
            out_file.write(buffer)
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                print(f"  Downloaded: {percent:.1f}% ({downloaded / (1024*1024):.1f}MB / {total_size / (1024*1024):.1f}MB)", end="\r")
        print("\nDownload finished ✓")

def load_tts_model(model_path: str = ""):
    """
    Load and return a Kokoro instance.
    Downloads the model assets on the first run.
    """
    if not os.path.exists(MODEL_PATH):
        print("Kokoro model file not found. Fetching from release server...")
        download_file(MODEL_URL, MODEL_PATH)
        
    if not os.path.exists(VOICES_PATH):
        print("Kokoro voices database file not found. Fetching from release server...")
        download_file(VOICES_URL, VOICES_PATH)
        
    from kokoro_onnx import Kokoro
    print("Loading Kokoro ONNX engine...")
    # Initialize Kokoro
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    print("Kokoro ONNX engine loaded successfully ✓")
    return kokoro
