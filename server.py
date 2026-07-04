# ============================================================
# server.py — FastAPI web dashboard for Narrator
#
# Generation runs in a subprocess (core/worker.py) because MLX
# requires GPU operations on the main thread of a process.
# ============================================================

import asyncio
import datetime
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

app = FastAPI(title="Resonate", docs_url=None, redoc_url=None)

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

# Generation history archive directory
ARCHIVE_DIR = Path("outputs/archive")


def _get_title_from_script(script_path: str) -> str:
    """Extract a clean short title from the first non-empty line of the script."""
    if not os.path.exists(script_path):
        return ""
    try:
        content = Path(script_path).read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            # Remove any overrides like [voice:...] or [emotion:...]
            import re
            clean = re.sub(r"\[[^\]]*\]", "", line).strip()
            if clean:
                # Limit length to first 7 words
                words = clean.split()
                if len(words) > 7:
                    return " ".join(words[:7]) + "..."
                return clean
    except Exception:
        pass
    return ""


def _archive_generation(audio_path: str, video_path: str | None, title: str = "") -> dict | None:
    """Copy finished audio (and optional video) into a timestamped archive folder."""
    if not audio_path or not os.path.exists(audio_path):
        return None
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = ARCHIVE_DIR / ts
    dest.mkdir(parents=True, exist_ok=True)

    # Copy audio
    audio_dest = dest / "audio.wav"
    shutil.copy2(audio_path, audio_dest)

    # Copy MP3 if exists
    mp3_src = Path(audio_path).with_suffix(".mp3")
    if mp3_src.exists():
        shutil.copy2(mp3_src, dest / "audio.mp3")

    # Copy video if provided
    has_video = False
    if video_path and os.path.exists(video_path):
        shutil.copy2(video_path, dest / "video.mp4")
        has_video = True

    # Copy current script snapshot
    if os.path.exists(config.SCRIPT_FILE):
        shutil.copy2(config.SCRIPT_FILE, dest / "script.txt")

    # Resolve a clean descriptive title from script content
    resolved_title = title.strip() if title else ""
    if not resolved_title:
        resolved_title = _get_title_from_script(config.SCRIPT_FILE)
    if not resolved_title:
        resolved_title = f"Generation {ts}"

    # Save metadata JSON
    meta = {
        "id":        ts,
        "title":     resolved_title,
        "created":   datetime.datetime.now().isoformat(),
        "voice":     config.VOICE,
        "speed":     config.SPEED,
        "emotion":   config.EMOTION,
        "has_video": has_video,
        "duration":  get_duration(str(audio_dest)),
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta

# SSE subscribers (asyncio queues)
_sse_subscribers: list[asyncio.Queue] = []

# Video generation state
_video_state = {
    "running": False,
    "status": "idle",      # idle | searching | merging | done | error | cancelled
    "message": "",
    "current_chunk": 0,
    "total_chunks": 0,
    "segments_done": [],
    "output_file": None,
}

# SSE subscribers for video progress
_video_sse_subscribers: list[asyncio.Queue] = []


def _broadcast(event: str, data: dict):
    """Push an event to all audio SSE subscribers."""
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


def _broadcast_video(event: str, data: dict):
    """Push an event to all video SSE subscribers."""
    msg = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = []
    for q in _video_sse_subscribers:
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in _video_sse_subscribers:
            _video_sse_subscribers.remove(q)


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


@app.get("/api/voices/preview/{voice_name}")
async def get_voice_preview(voice_name: str):
    path = Path("voice_tests") / f"{voice_name}_sample.wav"
    if path.exists():
        return FileResponse(path, media_type="audio/wav")
    return JSONResponse({"error": "Preview not found"}, status_code=404)


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


@app.post("/api/script/polish")
async def polish_script(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if not text:
        return {"ok": True, "text": ""}
        
    use_gemini = False
    gemini_key = getattr(config, "GEMINI_API_KEY", "")
    if gemini_key and gemini_key.strip():
        use_gemini = True

    if use_gemini:
        import requests
        prompt = (
            "You are a text processing expert. Your task is to clean up the provided script so it can be read smoothly by a TTS engine.\n\n"
            "Rules:\n"
            "1. Rewrite all numbers and numerical values into their fully spelled-out word equivalents. E.g., '1995' to 'nineteen ninety-five', '4.5' to 'four point five', '100' to 'one hundred', '$20' to 'twenty dollars'.\n"
            "2. Convert all abbreviations to their full spoken equivalents. E.g., 'Mr.' to 'Mister', 'Dr.' to 'Doctor', 'Mrs.' to 'Missus', 'St.' to 'Street', 'vs.' to 'versus', 'etc.' to 'et cetera'.\n"
            "3. Keep all voice and emotion override tags (like [voice:...] and [emotion:...]) exactly intact at the start or inline.\n"
            "4. Do not output any notes, introductory phrases, or markdown wrapper blocks. Return ONLY the polished script text exactly.\n\n"
            f"Script:\n{text}"
        )
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1}
            }
            res = requests.post(url, json=payload, timeout=15)
            res_data = res.json()
            ai_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if ai_text.startswith("```"):
                ai_text = "\n".join([line for line in ai_text.splitlines() if not line.startswith("```")])
            return {"ok": True, "text": ai_text, "mode": "ai"}
        except Exception as e:
            print(f"Gemini script polish error: {e}")

    # Fallback to local rule-based regex replacement (Offline)
    import re
    abbrev_map = {
        r"\bMr\b\.?": "Mister",
        r"\bMrs\b\.?": "Missus",
        r"\bMs\b\.?": "Miss",
        r"\bDr\b\.?": "Doctor",
        r"\bSt\b\.?": "Street",
        r"\bRd\b\.?": "Road",
        r"\bvs\b\.?": "versus",
        r"\bapprox\b\.?": "approximately",
        r"\bdept\b\.?": "department",
        r"\bmin\b\.?": "minutes",
        r"\bsec\b\.?": "seconds",
        r"\betc\b\.?": "et cetera",
    }
    
    polished = text
    for pattern, repl in abbrev_map.items():
        polished = re.sub(pattern, repl, polished, flags=re.IGNORECASE)
        
    num_map = {
        r"\b0\b": "zero",
        r"\b1\b": "one",
        r"\b2\b": "two",
        r"\b3\b": "three",
        r"\b4\b": "four",
        r"\b5\b": "five",
        r"\b6\b": "six",
        r"\b7\b": "seven",
        r"\b8\b": "eight",
        r"\b9\b": "nine",
    }
    for pattern, repl in num_map.items():
        polished = re.sub(pattern, repl, polished)

    return {"ok": True, "text": polished, "mode": "rules"}


# ── Routes: Reference voice ─────────────────────────────────


@app.post("/api/script/analyze")
async def analyze_script(request: Request):
    data = await request.json()
    text = data.get("text", "")
    if not text:
        return {"ok": True, "text": ""}
        
    lines = text.splitlines()
    analyzed_lines = []
    
    use_gemini = False
    gemini_key = getattr(config, "GEMINI_API_KEY", "")
    if gemini_key and gemini_key.strip():
        use_gemini = True

    if use_gemini:
        import requests
        prompt = (
            "You are a professional audio drama and audiobook script director. "
            "Your task is to take this script and enhance it by injecting appropriate tags "
            "for Kokoro TTS at the start of each line where a mood changes or a voice switches.\n\n"
            "Rules:\n"
            "- Available voice overrides: [voice:af_sarah], [voice:af_bella], [voice:af_heart], "
            "[voice:am_adam], [voice:am_michael], [voice:bf_emma], [voice:bm_george]\n"
            "- Available emotion overrides: [emotion:Simmering Anger] (for rage/heat), "
            "[emotion:Cinematic Narrative] (standard narration), [emotion:Whispered Suspense] (fear/secrecy/night), "
            "[emotion:Cold Precision] (flatness/precision), [emotion:Raw Vulnerability] (sorrow/pain), "
            "[emotion:Urgent Excitement] (energy), [emotion:Empowered Resolution] (confidence), "
            "[emotion:Bitter Sarcasm] (irony)\n"
            "- Keep spacing clean. Inject tags at the very start of lines where appropriate.\n"
            "- Do not add metadata, titles, or formatting wrapper text. Output ONLY the updated script text exactly.\n\n"
            f"Script:\n{text}"
        )
        
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2}
            }
            res = requests.post(url, json=payload, timeout=15)
            res_data = res.json()
            ai_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if ai_text.startswith("```"):
                ai_text = "\n".join([line for line in ai_text.splitlines() if not line.startswith("```")])
            return {"ok": True, "text": ai_text, "mode": "ai"}
        except Exception as e:
            print(f"Gemini script analysis error: {e}")

    # Fallback to pure offline rule-based heuristics
    import re
    default_voices = ["af_sarah", "am_adam", "af_bella", "bm_george"]
    voice_idx = 0
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            analyzed_lines.append("")
            continue
            
        if stripped.startswith("[voice:") or stripped.startswith("[emotion:"):
            analyzed_lines.append(line)
            continue
            
        injected_tags = []
        
        # Heuristics
        if re.search(r"\b(rage|hate|angry|betray|lie|lied|fake|enemy|scoundrel)\b", stripped, re.IGNORECASE):
            injected_tags.append("[emotion:Simmering Anger]")
        elif re.search(r"\b(quiet|silent|whisper|shadow|dark|night|breath|creepy|haunt|scared)\b", stripped, re.IGNORECASE):
            injected_tags.append("[emotion:Whispered Suspense]")
        elif re.search(r"\b(cry|weep|hurt|pain|sad|lost|tears|broken|alone|grief|sorrow)\b", stripped, re.IGNORECASE):
            injected_tags.append("[emotion:Raw Vulnerability]")
        elif re.search(r"\b(run|fast|excited|hurry|victory|win|shout|yes|great|awesome)\b", stripped, re.IGNORECASE):
            injected_tags.append("[emotion:Urgent Excitement]")
        elif re.search(r"\b(clinical|flat|dead|cold|calculation|math|science|fact)\b", stripped, re.IGNORECASE):
            injected_tags.append("[emotion:Cold Precision]")
        else:
            if len(stripped.split()) > 10:
                injected_tags.append("[emotion:Cinematic Narrative]")
                
        if "[voice:" not in line:
            current_voice = default_voices[voice_idx % len(default_voices)]
            injected_tags.insert(0, f"[voice:{current_voice}]")
            voice_idx += 1
            
        joined_tags = " ".join(injected_tags)
        analyzed_lines.append(f"{joined_tags} {stripped}")
        
    return {"ok": True, "text": "\n".join(analyzed_lines), "mode": "rules"}


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
                    # Archive this generation
                    try:
                        _archive_generation(
                            audio_path=config.OUTPUT_FILE,
                            video_path=None,  # video archives separately when video is done
                        )
                    except Exception as _ae:
                        print(f"Archive warning (audio): {_ae}")

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
        _update_state(running=False)


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


@app.delete("/api/chunks/{filename}")
async def delete_chunk(filename: str):
    """Delete a single chunk WAV file."""
    if _gen_state["running"]:
        return JSONResponse({"ok": False, "error": "Generation in progress"}, 409)
    path = os.path.join(config.CHUNKS_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
        # Also remove final output since it's now stale
        for ext in [".wav", ".mp3"]:
            p = config.OUTPUT_FILE.replace(".wav", ext) if ext == ".mp3" else config.OUTPUT_FILE
            if os.path.exists(p):
                os.remove(p)
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "Not found"}, 404)


@app.post("/api/clear")
async def clear_outputs():
    if _gen_state["running"]:
        return JSONResponse({"ok": False, "error": "Generation in progress"}, 409)
    if _video_state["running"]:
        return JSONResponse({"ok": False, "error": "Video generation in progress"}, 409)

    # ── Clear audio outputs ───────────────────────────────────
    if os.path.exists(config.CHUNKS_DIR):
        shutil.rmtree(config.CHUNKS_DIR)
    for ext in [".wav", ".mp3"]:
        path = config.OUTPUT_FILE.replace(".wav", ext) if ext == ".mp3" else config.OUTPUT_FILE
        if os.path.exists(path):
            os.remove(path)

    _gen_state.update(
        current_chunk=0, total_chunks=0, chunks_done=[],
        status="idle", message="", output_file=None,
    )
    _broadcast("progress", {
        "running": False, "status": "idle", "message": "",
        "current_chunk": 0, "total_chunks": 0, "chunks_done": [],
    })

    # ── Clear video outputs ───────────────────────────────────
    if os.path.exists(config.VIDEO_SEGMENTS_DIR):
        shutil.rmtree(config.VIDEO_SEGMENTS_DIR)
    if os.path.exists(config.VIDEO_OUTPUT_FILE):
        os.remove(config.VIDEO_OUTPUT_FILE)

    _video_state.update(
        current_chunk=0, total_chunks=0, segments_done=[],
        status="idle", message="", output_file=None,
    )
    _broadcast_video("progress", {
        "running": False, "status": "idle", "message": "",
        "current_chunk": 0, "total_chunks": 0, "segments_done": [],
    })

    return {"ok": True}


# ── Routes: Generation History ───────────────────────────────


@app.get("/api/history")
async def list_history():
    """Return all archived generation entries, newest first."""
    entries = []
    if ARCHIVE_DIR.exists():
        for folder in sorted(ARCHIVE_DIR.iterdir(), reverse=True):
            meta_path = folder / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    # Compute sizes
                    audio_p = folder / "audio.wav"
                    video_p = folder / "video.mp4"
                    meta["audio_exists"] = audio_p.exists()
                    meta["video_exists"] = video_p.exists()
                    meta["audio_size"]   = audio_p.stat().st_size if audio_p.exists() else 0
                    meta["video_size"]   = video_p.stat().st_size if video_p.exists() else 0
                    entries.append(meta)
                except Exception:
                    pass
    return {"entries": entries}


@app.patch("/api/history/{entry_id}")
async def rename_history_entry(entry_id: str, request: Request):
    """Rename a history entry."""
    data = await request.json()
    new_title = data.get("title", "").strip()
    if not new_title:
        return JSONResponse({"ok": False, "error": "Title required"}, 400)
    folder = ARCHIVE_DIR / entry_id
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        return JSONResponse({"ok": False, "error": "Not found"}, 404)
    meta = json.loads(meta_path.read_text())
    meta["title"] = new_title
    meta_path.write_text(json.dumps(meta, indent=2))
    return {"ok": True}


@app.get("/api/history/{entry_id}/audio")
async def serve_history_audio(entry_id: str, fmt: str = "wav"):
    """Stream the archived audio for a specific entry."""
    folder = ARCHIVE_DIR / entry_id
    if fmt == "mp3":
        path = folder / "audio.mp3"
        if path.exists():
            return FileResponse(path, media_type="audio/mpeg", filename=f"{entry_id}.mp3")
    path = folder / "audio.wav"
    if path.exists():
        return FileResponse(path, media_type="audio/wav", filename=f"{entry_id}.wav")
    return JSONResponse({"error": "Not found"}, 404)


@app.get("/api/history/{entry_id}/video")
async def serve_history_video(entry_id: str):
    """Stream the archived video for a specific entry."""
    path = ARCHIVE_DIR / entry_id / "video.mp4"
    if path.exists():
        return FileResponse(path, media_type="video/mp4", filename=f"{entry_id}.mp4")
    return JSONResponse({"error": "Not found"}, 404)


@app.get("/api/history/{entry_id}/script")
async def serve_history_script(entry_id: str):
    """Return the script snapshot for a specific entry."""
    path = ARCHIVE_DIR / entry_id / "script.txt"
    if path.exists():
        return {"text": path.read_text(encoding="utf-8")}
    return JSONResponse({"error": "Not found"}, 404)


@app.delete("/api/history/{entry_id}")
async def delete_history_entry(entry_id: str):
    """Permanently delete a history entry."""
    folder = ARCHIVE_DIR / entry_id
    if folder.exists() and folder.parent == ARCHIVE_DIR:
        shutil.rmtree(folder)
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "Not found"}, 404)


# ── Routes: Video (B-Roll) ──────────────────────────────

_video_worker_process = None
_video_worker_task    = None


def _update_video_state(**kwargs):
    """Update video generation state and broadcast to SSE."""
    _video_state.update(kwargs)
    _broadcast_video("progress", {
        "running":       _video_state["running"],
        "status":        _video_state["status"],
        "message":       _video_state["message"],
        "current_chunk": _video_state["current_chunk"],
        "total_chunks":  _video_state["total_chunks"],
        "segments_done": _video_state["segments_done"],
    })


async def _run_video_worker():
    """Spawn core/video_worker.py as a subprocess and stream progress."""
    global _video_worker_process

    config_path = os.path.join("outputs", ".video_worker_config.json")
    os.makedirs("outputs", exist_ok=True)

    merge_trigger_file = os.path.join("outputs", ".merge_trigger")
    worker_cfg = {
        "pexels_api_key":      config.PEXELS_API_KEY,
        "pixabay_api_key":     config.PIXABAY_API_KEY,
        "coverr_api_key":      config.COVERR_API_KEY,
        "gemini_api_key":      config.GEMINI_API_KEY,
        "youtube_api_key":     getattr(config, "YOUTUBE_API_KEY", ""),
        "groq_api_keys":       getattr(config, "GROQ_API_KEYS", []),
        "keyword_mode":        config.KEYWORD_MODE,
        "resolution":          config.VIDEO_RESOLUTION,
        "fps":                 config.VIDEO_FPS,
        "script_file":         config.SCRIPT_FILE,
        "chunks_dir":          config.CHUNKS_DIR,
        "segments_dir":        config.VIDEO_SEGMENTS_DIR,
        "output_file":         config.VIDEO_OUTPUT_FILE,
        "audio_file":          config.OUTPUT_FILE,
        "clip_interval":       getattr(config, "VIDEO_CLIP_INTERVAL", 0),
        "review_before_merge": getattr(config, "VIDEO_REVIEW_BEFORE_MERGE", True),
        "merge_trigger_file":  merge_trigger_file,
    }

    with open(config_path, "w") as f:
        json.dump(worker_cfg, f)

    try:
        python = sys.executable
        _video_worker_process = await asyncio.create_subprocess_exec(
            python, "core/video_worker.py", config_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )

        while True:
            line = await _video_worker_process.stdout.readline()
            if not line:
                break

            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                event = data.get("event", "")

                if event in ("status", "segment_progress"):
                    _update_video_state(
                        status=data.get("status", _video_state["status"]),
                        message=data.get("message", _video_state["message"]),
                        current_chunk=data.get("current_chunk", _video_state["current_chunk"]),
                        total_chunks=data.get("total_chunks", _video_state["total_chunks"]),
                    )

                elif event == "segment_done":
                    _update_video_state(
                        status=data.get("status", _video_state["status"]),
                        message=data.get("message", _video_state["message"]),
                        current_chunk=data.get("current_chunk", _video_state["current_chunk"]),
                        total_chunks=data.get("total_chunks", _video_state["total_chunks"]),
                        segments_done=data.get("segments_done", _video_state["segments_done"]),
                    )

                elif event == "review_ready":
                    # Pipeline is paused waiting for user to click Merge
                    _update_video_state(
                        running=True,
                        status="review_ready",
                        message=data.get("message", "Review clips before merging"),
                        current_chunk=data.get("current_chunk", _video_state["current_chunk"]),
                        total_chunks=data.get("total_chunks", _video_state["total_chunks"]),
                        segments_done=data.get("segments_done", _video_state["segments_done"]),
                    )

                elif event == "done":
                    _update_video_state(
                        running=False,
                        status="done",
                        message=data.get("message", "Video ready!"),
                        output_file=data.get("output_file"),
                        segments_done=data.get("segments_done", _video_state["segments_done"]),
                        current_chunk=data.get("current_chunk", _video_state["current_chunk"]),
                        total_chunks=data.get("total_chunks", _video_state["total_chunks"]),
                    )
                    # Archive with video included (update most recent audio-only archive)
                    try:
                        video_out = data.get("output_file") or config.VIDEO_OUTPUT_FILE
                        # Find most recent archive and patch video into it
                        if ARCHIVE_DIR.exists():
                            folders = sorted(ARCHIVE_DIR.iterdir(), reverse=True)
                            if folders:
                                latest = folders[0]
                                meta_path = latest / "meta.json"
                                if meta_path.exists() and video_out and os.path.exists(video_out):
                                    shutil.copy2(video_out, latest / "video.mp4")
                                    meta = json.loads(meta_path.read_text())
                                    meta["has_video"] = True
                                    meta_path.write_text(json.dumps(meta, indent=2))
                    except Exception as _ve:
                        print(f"Archive warning (video): {_ve}")

                elif event == "error":
                    _update_video_state(
                        running=False,
                        status="error",
                        message=data.get("message", "Video generation failed"),
                        segments_done=data.get("segments_done", _video_state["segments_done"]),
                    )

            except json.JSONDecodeError:
                pass

        await _video_worker_process.wait()

        if _video_worker_process.returncode != 0 and _video_state["status"] not in ("done", "error", "cancelled"):
            stderr = await _video_worker_process.stderr.read()
            err_msg = stderr.decode("utf-8", errors="replace").strip()[-300:]
            _update_video_state(
                running=False,
                status="error",
                message=f"Worker crashed: {err_msg}" if err_msg else "Video worker failed",
            )

    except asyncio.CancelledError:
        if _video_worker_process and _video_worker_process.returncode is None:
            _video_worker_process.terminate()
            await _video_worker_process.wait()
        _update_video_state(running=False, status="cancelled", message="Video generation cancelled")

    except Exception as e:
        _update_video_state(running=False, status="error", message=str(e))

    finally:
        _video_worker_process = None
        if os.path.exists(config_path):
            os.remove(config_path)
        _update_video_state(running=False)


@app.get("/api/video/status")
async def video_status():
    return {
        "running":       _video_state["running"],
        "status":        _video_state["status"],
        "message":       _video_state["message"],
        "current_chunk": _video_state["current_chunk"],
        "total_chunks":  _video_state["total_chunks"],
        "output_file":   _video_state["output_file"],
        "segments_done": _video_state["segments_done"],
    }


@app.post("/api/video/create")
async def start_video_generation(request: Request):
    global _video_worker_task

    if _video_state["running"]:
        return JSONResponse({"ok": False, "error": "Video generation already in progress"}, 409)

    # Check that audio exists
    if not os.path.exists(config.OUTPUT_FILE):
        return JSONResponse({"ok": False, "error": "No audio file found. Generate audio first."}, 400)

    _video_state["running"] = True
    _video_state["output_file"] = None
    _video_state["segments_done"] = []
    _video_state["current_chunk"] = 0
    _video_state["total_chunks"] = 0

    _update_video_state(status="searching", message="Starting video worker…")

    _video_worker_task = asyncio.create_task(_run_video_worker())
    return {"ok": True}


@app.post("/api/video/cancel")
async def cancel_video_generation():
    global _video_worker_task, _video_worker_process

    if not _video_state["running"]:
        return {"ok": False, "message": "Nothing running"}

    if _video_worker_task and not _video_worker_task.done():
        _video_worker_task.cancel()

    if _video_worker_process and _video_worker_process.returncode is None:
        try:
            _video_worker_process.terminate()
        except ProcessLookupError:
            pass

    _update_video_state(running=False, status="cancelled", message="Video generation cancelled")
    return {"ok": True}


@app.get("/api/video/events")
async def video_events_sse(request: Request):
    """SSE stream for real-time video generation progress."""
    queue = asyncio.Queue()
    _video_sse_subscribers.append(queue)

    async def event_stream():
        snapshot = {k: _video_state[k] for k in
                    ["running", "status", "message", "current_chunk",
                     "total_chunks", "segments_done"]}
        yield f"event: progress\ndata: {json.dumps(snapshot)}\n\n"

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
            if queue in _video_sse_subscribers:
                _video_sse_subscribers.remove(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/video/download")
async def download_video():
    path = config.VIDEO_OUTPUT_FILE
    if os.path.exists(path):
        return FileResponse(
            path, media_type="video/mp4",
            filename="narrator_video.mp4",
        )
    return JSONResponse({"error": "No video file found"}, 404)


@app.get("/api/video/config")
async def get_video_config():
    return {
        "pexels_api_key":      config.PEXELS_API_KEY,
        "pixabay_api_key":     config.PIXABAY_API_KEY,
        "coverr_api_key":      config.COVERR_API_KEY,
        "gemini_api_key":      config.GEMINI_API_KEY,
        "youtube_api_key":     getattr(config, "YOUTUBE_API_KEY", ""),
        "groq_api_keys":       ",".join(getattr(config, "GROQ_API_KEYS", [])),
        "keyword_mode":        config.KEYWORD_MODE,
        "resolution":          config.VIDEO_RESOLUTION,
        "fps":                 config.VIDEO_FPS,
        "clip_interval":       getattr(config, "VIDEO_CLIP_INTERVAL", 10),
        "review_before_merge": getattr(config, "VIDEO_REVIEW_BEFORE_MERGE", True),
    }


@app.post("/api/video/config")
async def update_video_config(request: Request):
    data = await request.json()
    mapping = {
        "pexels_api_key":      "PEXELS_API_KEY",
        "pixabay_api_key":     "PIXABAY_API_KEY",
        "coverr_api_key":      "COVERR_API_KEY",
        "gemini_api_key":      "GEMINI_API_KEY",
        "youtube_api_key":     "YOUTUBE_API_KEY",
        "keyword_mode":        "KEYWORD_MODE",
        "resolution":          "VIDEO_RESOLUTION",
        "fps":                 "VIDEO_FPS",
        "clip_interval":       "VIDEO_CLIP_INTERVAL",
        "review_before_merge": "VIDEO_REVIEW_BEFORE_MERGE",
    }
    for key, attr in mapping.items():
        if key in data:
            setattr(config, attr, data[key])
    if "groq_api_keys" in data:
        raw_val = data["groq_api_keys"]
        if isinstance(raw_val, list):
            config.GROQ_API_KEYS = [k.strip() for k in raw_val if k.strip()]
        else:
            config.GROQ_API_KEYS = [k.strip() for k in str(raw_val).split(",") if k.strip()]
    return {"ok": True}


# ── Routes: Video Segment Preview & Replace ──────────────────


@app.get("/api/video/segments")
async def list_video_segments():
    """Return metadata for all built video segments."""
    segs_dir = Path(config.VIDEO_SEGMENTS_DIR)
    segments = []
    if segs_dir.exists():
        for f in sorted(segs_dir.glob("segment_*.mp4")):
            # Parse index from filename
            try:
                idx = int(f.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            size = f.stat().st_size
            # Find matching segment_done entry from current state
            meta = {"index": idx, "file": f.name, "size": size, "ok": True}
            for seg in _video_state.get("segments_done", []):
                if seg.get("index") == idx:
                    meta["keyword"]  = seg.get("keyword", "")
                    meta["source"]   = seg.get("source", "")
                    meta["type"]     = seg.get("type", "")
                    meta["time"]     = seg.get("time", "")
                    break
            segments.append(meta)
    return {"segments": segments}


@app.get("/api/video/segments/{index}")
async def serve_video_segment(index: int):
    """Stream a single video segment file for preview."""
    path = Path(config.VIDEO_SEGMENTS_DIR) / f"segment_{index:04d}.mp4"
    if path.exists():
        return FileResponse(str(path), media_type="video/mp4")
    return JSONResponse({"error": "Segment not found"}, status_code=404)


@app.post("/api/video/segments/{index}/replace")
async def replace_video_segment(index: int, request: Request):
    """
    Re-search and rebuild a single video segment with a new keyword.
    Runs synchronously in a thread pool to avoid blocking the event loop.
    """
    if _video_state.get("status") not in ("review_ready",):
        return JSONResponse(
            {"ok": False, "error": "Replace is only available during the review stage"},
            status_code=409,
        )

    data     = await request.json()
    keyword  = data.get("keyword", "").strip()
    if not keyword:
        return JSONResponse({"ok": False, "error": "keyword is required"}, status_code=400)

    seg_path = str(Path(config.VIDEO_SEGMENTS_DIR) / f"segment_{index:04d}.mp4")

    # Find matching audio chunk
    audio_chunk = str(Path(config.CHUNKS_DIR) / f"chunk_{index:04d}.wav")
    if not os.path.exists(audio_chunk):
        return JSONResponse({"ok": False, "error": "Audio chunk not found for this segment"}, status_code=404)

    from core.video import build_segment
    import asyncio

    def _rebuild():
        # Remove existing segment so build_segment overwrites it
        if os.path.exists(seg_path):
            os.remove(seg_path)
        # Override text with the provided keyword directly
        result = build_segment(
            index=index,
            text=keyword,   # use keyword directly as the text (skips NLP extraction)
            audio_path=audio_chunk,
            out_path=seg_path,
            pexels_key=config.PEXELS_API_KEY,
            pixabay_key=config.PIXABAY_API_KEY,
            coverr_key=config.COVERR_API_KEY,
            gemini_key=config.GEMINI_API_KEY,
            youtube_key=getattr(config, "YOUTUBE_API_KEY", ""),
            groq_keys=getattr(config, "GROQ_API_KEYS", []),
            keyword_mode="rake",   # use RAKE so it returns the keyword as-is
            resolution=config.VIDEO_RESOLUTION,
            fps=config.VIDEO_FPS,
            segments_dir=config.VIDEO_SEGMENTS_DIR,
            clip_interval=0,       # no sub-splitting for manual replacement
        )
        return result

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _rebuild)

    if result.get("ok"):
        # Patch segments_done in state
        for seg in _video_state["segments_done"]:
            if seg.get("index") == index:
                seg.update(keyword=keyword, source=result.get("source"), type=result.get("type"))
                break
        _broadcast_video("progress", {
            "running":       _video_state["running"],
            "status":        _video_state["status"],
            "message":       f"Segment {index+1} replaced with '{keyword}'",
            "current_chunk": _video_state["current_chunk"],
            "total_chunks":  _video_state["total_chunks"],
            "segments_done": _video_state["segments_done"],
        })
        return {"ok": True, "source": result.get("source"), "type": result.get("type")}
    else:
        return JSONResponse({"ok": False, "error": "Rebuild failed — no clip found"}, status_code=500)


@app.post("/api/video/segments/{index}/upload")
async def upload_video_segment(index: int, file: UploadFile = File(...)):
    """
    Replace a video segment by uploading a custom video file.
    Accepts any video format; converts to the project resolution via ffmpeg.
    """
    if _video_state.get("status") not in ("review_ready",):
        return JSONResponse(
            {"ok": False, "error": "Upload is only available during the review stage"},
            status_code=409,
        )

    seg_path  = str(Path(config.VIDEO_SEGMENTS_DIR) / f"segment_{index:04d}.mp4")
    audio_chunk = str(Path(config.CHUNKS_DIR) / f"chunk_{index:04d}.wav")

    import tempfile
    suffix = Path(file.filename).suffix if file.filename else ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from core.video import fill_video_segment, _get_duration_secs
        import asyncio

        def _convert():
            # Get target duration from audio chunk
            if os.path.exists(audio_chunk):
                from core.audio import get_duration_secs
                duration = get_duration_secs(audio_chunk)
            else:
                duration = _get_duration_secs(tmp_path)
            if duration <= 0:
                duration = _get_duration_secs(tmp_path)
            if os.path.exists(seg_path):
                os.remove(seg_path)
            return fill_video_segment(
                [tmp_path], seg_path, duration,
                config.VIDEO_RESOLUTION, config.VIDEO_FPS,
            )

        loop = asyncio.get_event_loop()
        ok   = await loop.run_in_executor(None, _convert)

        if ok:
            for seg in _video_state["segments_done"]:
                if seg.get("index") == index:
                    seg.update(keyword="custom upload", source="upload", type="video")
                    break
            _broadcast_video("progress", {
                "running":       _video_state["running"],
                "status":        _video_state["status"],
                "message":       f"Segment {index+1} replaced with uploaded file",
                "current_chunk": _video_state["current_chunk"],
                "total_chunks":  _video_state["total_chunks"],
                "segments_done": _video_state["segments_done"],
            })
            return {"ok": True}
        else:
            return JSONResponse({"ok": False, "error": "Conversion failed"}, status_code=500)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/api/video/merge")
async def trigger_video_merge():
    """Signal the video worker to proceed with final merge after review."""
    if _video_state.get("status") != "review_ready":
        return JSONResponse(
            {"ok": False, "error": "Not in review state"},
            status_code=409,
        )
    # Write trigger file — worker polls for this
    trigger = os.path.join("outputs", ".merge_trigger")
    os.makedirs("outputs", exist_ok=True)
    Path(trigger).touch()
    _update_video_state(status="merging", message="Merging all segments…")
    return {"ok": True}


@app.post("/api/video/clear")
async def clear_video_outputs():
    if _video_state["running"]:
        return JSONResponse({"ok": False, "error": "Video generation in progress"}, 409)

    if os.path.exists(config.VIDEO_SEGMENTS_DIR):
        shutil.rmtree(config.VIDEO_SEGMENTS_DIR)
    if os.path.exists(config.VIDEO_OUTPUT_FILE):
        os.remove(config.VIDEO_OUTPUT_FILE)

    _video_state.update(
        current_chunk=0, total_chunks=0, segments_done=[],
        status="idle", message="", output_file=None,
    )
    _broadcast_video("progress", {
        "running": False, "status": "idle", "message": "",
        "current_chunk": 0, "total_chunks": 0, "segments_done": [],
    })
    return {"ok": True}


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n  🎙️  Resonate Dashboard → http://{config.SERVER_HOST}:{config.SERVER_PORT}\n")
    uvicorn.run(
        "server:app",
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        reload=False,
        log_level="warning",
    )
