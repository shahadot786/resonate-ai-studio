# ============================================================
# server.py — FastAPI web dashboard for Narrator
# ============================================================

import asyncio
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

import config
from core.audio import (
    generate_chunk,
    get_duration,
    get_duration_secs,
    stitch_wavs,
)
from core.model import load_tts_model
from core.script import parse_script

# ── App setup ────────────────────────────────────────────────

app = FastAPI(title="Narrator", docs_url=None, redoc_url=None)

# Serve static files from web/
app.mount("/static", StaticFiles(directory="web"), name="static")

# ── State ────────────────────────────────────────────────────

_model = None
_model_lock = threading.Lock()

# Generation state
_gen_state = {
    "running": False,
    "cancel_requested": False,
    "current_chunk": 0,
    "total_chunks": 0,
    "chunks_done": [],
    "status": "idle",      # idle | loading | generating | stitching | done | error | cancelled
    "message": "",
    "started_at": None,
    "output_file": None,
}

# SSE subscribers (asyncio queues)
_sse_subscribers: list[asyncio.Queue] = []


def _broadcast(event: str, data: dict):
    """Push an event to all SSE subscribers."""
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        _sse_subscribers.remove(q)


def _update_state(**kwargs):
    """Update generation state and broadcast to SSE."""
    _gen_state.update(kwargs)
    _broadcast("progress", {
        "running": _gen_state["running"],
        "status": _gen_state["status"],
        "message": _gen_state["message"],
        "current_chunk": _gen_state["current_chunk"],
        "total_chunks": _gen_state["total_chunks"],
        "chunks_done": _gen_state["chunks_done"],
    })


def _get_model():
    """Load model once (thread-safe)."""
    global _model
    with _model_lock:
        if _model is None:
            _update_state(status="loading", message="Loading TTS model...")
            _model = load_tts_model(config.MODEL_PATH)
            _update_state(status="idle", message="Model ready")
        return _model


# ── Routes: Dashboard ────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard page."""
    return FileResponse("web/index.html")


# ── Routes: Config ───────────────────────────────────────────


@app.get("/api/config")
async def get_config():
    return {
        "voice": config.VOICE,
        "speed": config.SPEED,
        "emotion": config.EMOTION,
        "ref_audio": config.REF_AUDIO,
        "ref_text": config.REF_TEXT,
        "silence_padding": config.SILENCE_PADDING,
        "normalize_audio": config.NORMALIZE_AUDIO,
        "export_mp3": config.EXPORT_MP3,
    }


@app.post("/api/config")
async def update_config(request: Request):
    data = await request.json()
    for key in ["voice", "speed", "emotion", "ref_audio", "ref_text",
                 "silence_padding", "normalize_audio", "export_mp3"]:
        if key in data:
            val = data[key]
            attr = key.upper()
            if hasattr(config, attr):
                setattr(config, attr, val)
    return {"ok": True}


@app.get("/api/voices")
async def list_voices():
    return {"voices": config.VOICES}


# ── Routes: Script ───────────────────────────────────────────


@app.get("/api/script")
async def get_script():
    if os.path.exists(config.SCRIPT_FILE):
        text = Path(config.SCRIPT_FILE).read_text(encoding="utf-8")
    else:
        text = ""
    return {"text": text, "path": config.SCRIPT_FILE}


@app.post("/api/script")
async def save_script(request: Request):
    data = await request.json()
    text = data.get("text", "")
    Path(config.SCRIPT_FILE).write_text(text, encoding="utf-8")
    return {"ok": True, "lines": len([l for l in text.splitlines() if l.strip()])}


# ── Routes: Reference voice upload ───────────────────────────


@app.get("/api/refs")
async def list_refs():
    """List available reference audio files."""
    refs = []
    if os.path.exists(config.REF_DIR):
        for f in sorted(os.listdir(config.REF_DIR)):
            if f.endswith((".wav", ".mp3", ".m4a", ".flac")):
                path = os.path.join(config.REF_DIR, f)
                refs.append({
                    "name": f,
                    "path": path,
                    "duration": get_duration(path),
                    "active": path == config.REF_AUDIO,
                })
    return {"refs": refs, "current": config.REF_AUDIO}


@app.post("/api/refs/upload")
async def upload_ref(
    file: UploadFile = File(...),
    ref_text: str = Form(""),
):
    """Upload a new reference voice WAV."""
    os.makedirs(config.REF_DIR, exist_ok=True)
    dest = os.path.join(config.REF_DIR, file.filename)
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    # Auto-activate the uploaded ref
    config.REF_AUDIO = dest
    if ref_text:
        config.REF_TEXT = ref_text

    return {
        "ok": True,
        "path": dest,
        "name": file.filename,
        "duration": get_duration(dest),
    }


@app.post("/api/refs/activate")
async def activate_ref(request: Request):
    data = await request.json()
    path = data.get("path", "")
    if os.path.exists(path):
        config.REF_AUDIO = path
        if "ref_text" in data:
            config.REF_TEXT = data["ref_text"]
        return {"ok": True, "active": path}
    return JSONResponse({"ok": False, "error": "File not found"}, 400)


# ── Routes: Generation ───────────────────────────────────────


def _run_generation(mode: str, text: str | None = None):
    """Background thread: generate audio chunks and stitch."""
    try:
        model = _get_model()

        if mode == "batch":
            if not os.path.exists(config.SCRIPT_FILE):
                _update_state(running=False, status="error", message="script.txt not found")
                return
            chunks = parse_script(config.SCRIPT_FILE)
        else:
            # Single mode
            chunks = [{"text": text or "", "voice": None, "emotion": None}]

        total = len(chunks)
        if total == 0:
            _update_state(running=False, status="error", message="No text to generate")
            return

        os.makedirs(config.CHUNKS_DIR, exist_ok=True)
        os.makedirs("outputs", exist_ok=True)

        _update_state(
            total_chunks=total,
            current_chunk=0,
            chunks_done=[],
            status="generating",
        )

        made = []

        for i, chunk in enumerate(chunks):
            if _gen_state["cancel_requested"]:
                _update_state(running=False, status="cancelled", message="Generation cancelled")
                return

            chunk_path = os.path.join(config.CHUNKS_DIR, f"chunk_{i:04d}.wav")
            voice = chunk["voice"] or config.VOICE
            emotion = chunk["emotion"] or config.EMOTION
            preview = chunk["text"][:80]

            _update_state(
                current_chunk=i + 1,
                message=f"Generating chunk {i + 1}/{total}: \"{preview}...\"",
            )

            # Skip existing chunks
            if os.path.exists(chunk_path):
                made.append(chunk_path)
                done = list(_gen_state["chunks_done"])
                done.append({
                    "index": i,
                    "file": f"chunk_{i:04d}.wav",
                    "duration": get_duration(chunk_path),
                    "skipped": True,
                })
                _update_state(chunks_done=done)
                continue

            t0 = time.time()
            ok = generate_chunk(
                model,
                chunk["text"],
                chunk_path,
                voice=voice,
                ref_audio=config.REF_AUDIO,
                ref_text=config.REF_TEXT,
                instruct=emotion,
                speed=config.SPEED,
                verbose=True,
            )

            if ok:
                made.append(chunk_path)
                elapsed = time.time() - t0
                done = list(_gen_state["chunks_done"])
                done.append({
                    "index": i,
                    "file": f"chunk_{i:04d}.wav",
                    "duration": get_duration(chunk_path),
                    "time": f"{elapsed:.1f}s",
                    "skipped": False,
                })
                _update_state(chunks_done=done)
            else:
                done = list(_gen_state["chunks_done"])
                done.append({
                    "index": i,
                    "file": f"chunk_{i:04d}.wav",
                    "error": True,
                })
                _update_state(chunks_done=done)

        # Stitch
        _update_state(status="stitching", message="Stitching chunks...")

        output = config.OUTPUT_FILE if mode == "batch" else "outputs/single_output.wav"

        if made and stitch_wavs(
            made,
            output,
            silence_padding=config.SILENCE_PADDING,
            sample_rate=config.SAMPLE_RATE,
            normalize=config.NORMALIZE_AUDIO,
            export_mp3=config.EXPORT_MP3,
        ):
            duration = get_duration(output)
            _update_state(
                running=False,
                status="done",
                message=f"Complete! Duration: {duration}",
                output_file=output,
            )
        else:
            _update_state(
                running=False,
                status="error",
                message="Stitching failed",
            )

    except Exception as e:
        _update_state(running=False, status="error", message=str(e))


@app.post("/api/generate")
async def start_generation(request: Request):
    """Start batch generation in a background thread."""
    if _gen_state["running"]:
        return JSONResponse({"ok": False, "error": "Generation already in progress"}, 409)

    data = await request.json() if request.headers.get("content-type") == "application/json" else {}
    mode = data.get("mode", "batch")
    text = data.get("text", "")

    _gen_state["running"] = True
    _gen_state["cancel_requested"] = False
    _gen_state["output_file"] = None

    thread = threading.Thread(target=_run_generation, args=(mode, text), daemon=True)
    thread.start()

    return {"ok": True, "mode": mode}


@app.post("/api/generate/stop")
async def stop_generation():
    if _gen_state["running"]:
        _gen_state["cancel_requested"] = True
        return {"ok": True, "message": "Cancel requested"}
    return {"ok": False, "message": "Nothing running"}


@app.get("/api/generate/progress")
async def progress_sse(request: Request):
    """Server-Sent Events stream for real-time progress."""
    queue = asyncio.Queue()
    _sse_subscribers.append(queue)

    async def event_stream():
        # Send current state immediately
        yield f"event: progress\ndata: {json.dumps({k: _gen_state[k] for k in ['running', 'status', 'message', 'current_chunk', 'total_chunks', 'chunks_done']})}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in _sse_subscribers:
                _sse_subscribers.remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/generate/status")
async def generation_status():
    return {
        "running": _gen_state["running"],
        "status": _gen_state["status"],
        "message": _gen_state["message"],
        "current_chunk": _gen_state["current_chunk"],
        "total_chunks": _gen_state["total_chunks"],
        "output_file": _gen_state["output_file"],
    }


# ── Routes: Audio serving ────────────────────────────────────


@app.get("/api/audio/final")
async def serve_final():
    """Serve the final stitched audio."""
    for ext in [".wav", ".mp3"]:
        path = config.OUTPUT_FILE.replace(".wav", ext) if ext == ".mp3" else config.OUTPUT_FILE
        if os.path.exists(path):
            return FileResponse(path, media_type="audio/wav" if ext == ".wav" else "audio/mpeg")
    return JSONResponse({"error": "No output file"}, 404)


@app.get("/api/audio/chunk/{filename}")
async def serve_chunk(filename: str):
    """Serve an individual chunk WAV."""
    path = os.path.join(config.CHUNKS_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="audio/wav")
    return JSONResponse({"error": "Not found"}, 404)


@app.get("/api/audio/ref/{filename}")
async def serve_ref(filename: str):
    """Serve a reference audio file."""
    path = os.path.join(config.REF_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "Not found"}, 404)


@app.get("/api/chunks")
async def list_chunks():
    """List all generated chunks with metadata."""
    chunks = []
    if os.path.exists(config.CHUNKS_DIR):
        for f in sorted(os.listdir(config.CHUNKS_DIR)):
            if f.endswith(".wav"):
                path = os.path.join(config.CHUNKS_DIR, f)
                chunks.append({
                    "name": f,
                    "duration": get_duration(path),
                    "duration_secs": get_duration_secs(path),
                    "size": os.path.getsize(path),
                })

    final_exists = os.path.exists(config.OUTPUT_FILE)
    mp3_path = config.OUTPUT_FILE.replace(".wav", ".mp3")
    mp3_exists = os.path.exists(mp3_path)

    return {
        "chunks": chunks,
        "final": {
            "exists": final_exists,
            "duration": get_duration(config.OUTPUT_FILE) if final_exists else None,
            "mp3_exists": mp3_exists,
        },
    }


@app.get("/api/download/{format}")
async def download_output(format: str):
    """Download final output in WAV or MP3."""
    if format == "mp3":
        path = config.OUTPUT_FILE.replace(".wav", ".mp3")
        media = "audio/mpeg"
        fname = "narrator_output.mp3"
    else:
        path = config.OUTPUT_FILE
        media = "audio/wav"
        fname = "narrator_output.wav"

    if os.path.exists(path):
        return FileResponse(path, media_type=media, filename=fname)
    return JSONResponse({"error": "File not found"}, 404)


# ── Routes: Clear / Reset ───────────────────────────────────


@app.post("/api/clear")
async def clear_outputs():
    """Delete all generated chunks and outputs."""
    if _gen_state["running"]:
        return JSONResponse({"ok": False, "error": "Generation in progress"}, 409)

    if os.path.exists(config.CHUNKS_DIR):
        shutil.rmtree(config.CHUNKS_DIR)
    for ext in [".wav", ".mp3"]:
        path = config.OUTPUT_FILE.replace(".wav", ext) if ext == ".mp3" else config.OUTPUT_FILE
        if os.path.exists(path):
            os.remove(path)

    _gen_state.update(
        current_chunk=0, total_chunks=0, chunks_done=[],
        status="idle", message="Outputs cleared", output_file=None,
    )

    return {"ok": True}


# ── Startup ──────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    """Pre-load model on server start."""
    threading.Thread(target=_get_model, daemon=True).start()


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n  🎙️  Narrator Dashboard → http://{config.SERVER_HOST}:{config.SERVER_PORT}\n")
    uvicorn.run(
        "server:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=False,
        log_level="warning",
    )
