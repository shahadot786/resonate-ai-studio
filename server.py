# ============================================================
# server.py — FastAPI web dashboard for Narrator
#
# Generation runs in a subprocess (core/worker.py) because MLX
# requires GPU operations on the main thread of a process.
# ============================================================

import asyncio
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

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
from core.audio import get_duration, get_duration_secs

# ── App setup ────────────────────────────────────────────────

app = FastAPI(title="Narrator", docs_url=None, redoc_url=None)

# Serve static files from web/
app.mount("/static", StaticFiles(directory="web"), name="static")

# ── State ────────────────────────────────────────────────────

_worker_process = None  # asyncio.subprocess.Process

# Generation state
_gen_state = {
    "running": False,
    "status": "idle",      # idle | loading | generating | stitching | done | error | cancelled
    "message": "",
    "current_chunk": 0,
    "total_chunks": 0,
    "chunks_done": [],
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
        if q in _sse_subscribers:
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


# ── Routes: Dashboard ────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard():
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
            setattr(config, key.upper(), data[key])
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


# ── Routes: Reference voice ─────────────────────────────────


@app.get("/api/refs")
async def list_refs():
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
    os.makedirs(config.REF_DIR, exist_ok=True)
    dest = os.path.join(config.REF_DIR, file.filename)
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

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


# ── Routes: Generation (subprocess-based) ────────────────────


async def _run_worker(mode: str, text: str = ""):
    """Spawn core/worker.py as a subprocess and stream progress."""
    global _worker_process

    # Write config to temp file for the worker
    config_path = os.path.join("outputs", ".worker_config.json")
    os.makedirs("outputs", exist_ok=True)

    worker_cfg = {
        "mode": mode,
        "text": text,
        "voice": config.VOICE,
        "speed": config.SPEED,
        "emotion": config.EMOTION,
        "ref_audio": config.REF_AUDIO,
        "ref_text": config.REF_TEXT,
        "script_file": config.SCRIPT_FILE,
        "output_file": config.OUTPUT_FILE,
        "chunks_dir": config.CHUNKS_DIR,
        "silence_padding": config.SILENCE_PADDING,
        "sample_rate": config.SAMPLE_RATE,
        "normalize_audio": config.NORMALIZE_AUDIO,
        "export_mp3": config.EXPORT_MP3,
        "model_path": config.MODEL_PATH,
    }

    with open(config_path, "w") as f:
        json.dump(worker_cfg, f)

    try:
        # Find the Python from the current venv
        python = sys.executable

        _worker_process = await asyncio.create_subprocess_exec(
            python, "core/worker.py", config_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )

        # Read stdout line by line for JSON progress
        while True:
            line = await _worker_process.stdout.readline()
            if not line:
                break

            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            # Try to parse as JSON progress
            try:
                data = json.loads(line)
                event = data.get("event", "")

                if event in ("status", "chunk_done", "chunk_error"):
                    _update_state(
                        status=data.get("status", _gen_state["status"]),
                        message=data.get("message", _gen_state["message"]),
                        current_chunk=data.get("current_chunk", _gen_state["current_chunk"]),
                        total_chunks=data.get("total_chunks", _gen_state["total_chunks"]),
                        chunks_done=data.get("chunks_done", _gen_state["chunks_done"]),
                    )

                elif event == "done":
                    _update_state(
                        running=False,
                        status="done",
                        message=data.get("message", "Complete!"),
                        output_file=data.get("output_file"),
                        chunks_done=data.get("chunks_done", _gen_state["chunks_done"]),
                    )

                elif event == "error":
                    _update_state(
                        running=False,
                        status="error",
                        message=data.get("message", "Generation failed"),
                        chunks_done=data.get("chunks_done", _gen_state["chunks_done"]),
                    )

            except json.JSONDecodeError:
                # Not JSON — probably model loading output, ignore
                pass

        # Wait for process to finish
        await _worker_process.wait()

        # If process exited with error and we haven't already set error state
        if _worker_process.returncode != 0 and _gen_state["status"] not in ("done", "error", "cancelled"):
            stderr = await _worker_process.stderr.read()
            err_msg = stderr.decode("utf-8", errors="replace").strip()[-200:]
            _update_state(
                running=False,
                status="error",
                message=f"Worker crashed: {err_msg}" if err_msg else "Worker process failed",
            )

    except asyncio.CancelledError:
        # Stop was requested
        if _worker_process and _worker_process.returncode is None:
            _worker_process.terminate()
            await _worker_process.wait()
        _update_state(running=False, status="cancelled", message="Generation cancelled")

    except Exception as e:
        _update_state(running=False, status="error", message=str(e))

    finally:
        _worker_process = None
        # Clean up config file
        if os.path.exists(config_path):
            os.remove(config_path)


_worker_task = None  # asyncio.Task


@app.post("/api/generate")
async def start_generation(request: Request):
    global _worker_task

    if _gen_state["running"]:
        return JSONResponse({"ok": False, "error": "Generation already in progress"}, 409)

    data = await request.json() if request.headers.get("content-type") == "application/json" else {}
    mode = data.get("mode", "batch")
    text = data.get("text", "")

    _gen_state["running"] = True
    _gen_state["output_file"] = None
    _gen_state["chunks_done"] = []
    _gen_state["current_chunk"] = 0
    _gen_state["total_chunks"] = 0

    _update_state(status="loading", message="Starting worker...")

    # Launch worker as async task
    _worker_task = asyncio.create_task(_run_worker(mode, text))

    return {"ok": True, "mode": mode}


@app.post("/api/generate/stop")
async def stop_generation():
    global _worker_task, _worker_process

    if not _gen_state["running"]:
        return {"ok": False, "message": "Nothing running"}

    # Cancel the async task (which will terminate the subprocess)
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()

    # Also send SIGTERM directly to the worker process
    if _worker_process and _worker_process.returncode is None:
        try:
            _worker_process.terminate()
        except ProcessLookupError:
            pass

    _update_state(running=False, status="cancelled", message="Generation cancelled")
    return {"ok": True, "message": "Cancel requested"}


@app.get("/api/generate/progress")
async def progress_sse(request: Request):
    """Server-Sent Events stream for real-time progress."""
    queue = asyncio.Queue()
    _sse_subscribers.append(queue)

    async def event_stream():
        # Send current state immediately
        state_snapshot = {k: _gen_state[k] for k in
                          ["running", "status", "message", "current_chunk", "total_chunks", "chunks_done"]}
        yield f"event: progress\ndata: {json.dumps(state_snapshot)}\n\n"

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
    for ext in [".wav", ".mp3"]:
        path = config.OUTPUT_FILE.replace(".wav", ext) if ext == ".mp3" else config.OUTPUT_FILE
        if os.path.exists(path):
            return FileResponse(path, media_type="audio/wav" if ext == ".wav" else "audio/mpeg")
    return JSONResponse({"error": "No output file"}, 404)


@app.get("/api/audio/chunk/{filename}")
async def serve_chunk(filename: str):
    path = os.path.join(config.CHUNKS_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="audio/wav")
    return JSONResponse({"error": "Not found"}, 404)


@app.get("/api/audio/ref/{filename}")
async def serve_ref(filename: str):
    path = os.path.join(config.REF_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "Not found"}, 404)


@app.get("/api/chunks")
async def list_chunks():
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

    return {
        "chunks": chunks,
        "final": {
            "exists": final_exists,
            "duration": get_duration(config.OUTPUT_FILE) if final_exists else None,
            "mp3_exists": os.path.exists(mp3_path),
        },
    }


@app.get("/api/download/{format}")
async def download_output(format: str):
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
