# ============================================================
# core/video.py — B-Roll video pipeline
#
# Pipeline per chunk:
#   1. Extract search keyword (RAKE offline or Gemini Flash)
#   2. Search video: Pexels → Pixabay → Coverr → Wikimedia
#   3. Fallback to image: Pexels → Pixabay → Wikimedia
#   4. Trim/loop video  OR  convert image → video (Ken Burns)
#   5. Merge all segments + mux with audio → final MP4
# ============================================================

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Optional

import requests

# ── Keyword extraction ────────────────────────────────────────


def _rake_keyword(text: str) -> str:
    """Extract best keyword phrase using RAKE (offline, no API)."""
    try:
        from rake_nltk import Rake
        r = Rake(max_length=3)
        r.extract_keywords_from_text(text)
        phrases = r.get_ranked_phrases()
        return phrases[0] if phrases else text[:40]
    except Exception:
        # Fallback: first 5 words
        words = text.split()
        return " ".join(words[:5])


def _gemini_keyword(text: str, api_key: str) -> str:
    """Extract best visual b-roll keyword using Gemini Flash (free tier)."""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            "You are a video editor choosing b-roll footage. "
            "Given this narration line, return ONLY a short 2-4 word search phrase "
            "that best describes what video footage should appear on screen. "
            "Be specific and visual. No explanation, just the phrase.\n\n"
            f"Narration: {text}"
        )
        # Try free-tier models in order (confirmed working first)
        models = [
            "gemini-2.5-flash",
            "gemini-2.0-flash-001",
            "gemini-2.0-flash-lite-001",
            "gemini-2.0-flash",
        ]
        last_err = None
        for model in models:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                keyword = response.text.strip().strip('"').strip("'").strip()
                keyword = re.sub(r"[.!?,;]+$", "", keyword).strip()
                return keyword if keyword else _rake_keyword(text)
            except Exception as e:
                last_err = e
                continue
        raise last_err
    except Exception as e:
        print(f"  ⚠ Gemini keyword failed ({e}), falling back to RAKE")
        return _rake_keyword(text)


def extract_keyword(text: str, mode: str = "rake", api_key: str = "") -> str:
    """Extract a visual search keyword from a narration chunk."""
    if mode == "gemini" and api_key:
        return _gemini_keyword(text, api_key)
    return _rake_keyword(text)


# ── Media search — Videos ────────────────────────────────────


def _orientation_from_resolution(resolution: str) -> str:
    """
    Derive Pexels/Pixabay orientation string from a WxH resolution string.
    Returns 'portrait', 'landscape', or 'square'.
    """
    try:
        w, h = resolution.split("x")
        w, h = int(w), int(h)
        if h > w:
            return "portrait"
        elif w > h:
            return "landscape"
        else:
            return "square"
    except Exception:
        return "landscape"


def _search_pexels_video(keyword: str, api_key: str, orientation: str = "landscape") -> Optional[str]:
    """Search Pexels for a video clip. Returns direct download URL or None."""
    try:
        # First try requested orientation, then fall back to any orientation
        for orient in ([orientation, None] if orientation != "landscape" else [orientation]):
            params = {"query": keyword, "per_page": 8}
            if orient:
                params["orientation"] = orient
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": api_key},
                params=params,
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            videos = resp.json().get("videos", [])
            for video in videos:
                files = video.get("video_files", [])
                # For portrait: prefer tall files (height > width)
                if orient == "portrait":
                    portrait_files = [f for f in files if f.get("height", 0) > f.get("width", 0)]
                    if portrait_files:
                        # Pick highest quality portrait file
                        portrait_files.sort(key=lambda f: f.get("height", 0), reverse=True)
                        return portrait_files[0]["link"]
                # Landscape: prefer wide HD files
                for quality in ["hd", "sd"]:
                    for vf in files:
                        if vf.get("quality") == quality and vf.get("width", 0) >= 1280:
                            return vf["link"]
                if files:
                    return files[0]["link"]
            if videos:  # found videos on first attempt, don't retry
                break
    except Exception as e:
        print(f"  ⚠ Pexels video search error: {e}")
    return None


def _search_pixabay_video(keyword: str, api_key: str, orientation: str = "horizontal") -> Optional[str]:
    """Search Pixabay for a video clip. Returns direct download URL or None."""
    # Pixabay uses 'horizontal' / 'vertical' / 'all'
    pixabay_orient = (
        "vertical"   if orientation == "portrait" else
        "horizontal" if orientation == "landscape" else
        "all"
    )
    try:
        for orient in ([pixabay_orient, "all"] if pixabay_orient != "all" else ["all"]):
            resp = requests.get(
                "https://pixabay.com/api/videos/",
                params={
                    "key": api_key,
                    "q": keyword,
                    "per_page": 8,
                    "video_type": "film",
                    "orientation": orient,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            hits = resp.json().get("hits", [])
            for hit in hits:
                videos = hit.get("videos", {})
                for quality in ["large", "medium", "small"]:
                    v = videos.get(quality, {})
                    url = v.get("url")
                    if url:
                        return url
            if hits:
                break
    except Exception as e:
        print(f"  ⚠ Pixabay video search error: {e}")
    return None


def _search_coverr_video(keyword: str, api_key: str = "") -> Optional[str]:
    """Search Coverr for a video clip. Returns download URL or None."""
    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.get(
            "https://api.coverr.co/videos",
            headers=headers,
            params={"keywords": keyword, "per_page": 3},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        hits = data.get("hits", [])
        for hit in hits:
            url = hit.get("urls", {}).get("mp4_download") or hit.get("mp4")
            if url:
                return url
    except Exception as e:
        print(f"  ⚠ Coverr video search error: {e}")
    return None


def _search_wikimedia_video(keyword: str) -> Optional[str]:
    """Search Wikimedia Commons for a video (webm/ogv). No API key needed."""
    try:
        resp = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": f"{keyword} filetype:video",
                "gsrnamespace": 6,
                "gsrlimit": 5,
                "prop": "imageinfo",
                "iiprop": "url|mime|mediatype",
                "format": "json",
            },
            headers={"User-Agent": "NarratorBRoll/1.0 (narrator-tool)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            info = page.get("imageinfo", [{}])[0]
            mime = info.get("mime", "")
            if info.get("mediatype") == "VIDEO" or "video" in mime:
                return info.get("url")
    except Exception as e:
        print(f"  ⚠ Wikimedia video search error: {e}")
    return None


# ── Media search — Images (fallback) ────────────────────────


def _search_pexels_image(keyword: str, api_key: str, orientation: str = "landscape") -> Optional[str]:
    """Search Pexels for a photo. Returns original image URL or None."""
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": api_key},
            params={"query": keyword, "per_page": 5, "orientation": orientation},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        photos = resp.json().get("photos", [])
        if photos:
            src = photos[0].get("src", {})
            return src.get("original") or src.get("large2x") or src.get("large")
    except Exception as e:
        print(f"  ⚠ Pexels image search error: {e}")
    return None


def _search_pixabay_image(keyword: str, api_key: str, orientation: str = "horizontal") -> Optional[str]:
    """Search Pixabay for a photo. Returns full-size image URL or None."""
    pixabay_orient = "vertical" if orientation == "portrait" else "horizontal"
    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": keyword,
                "per_page": 5,
                "orientation": pixabay_orient,
                "image_type": "photo",
                "min_width": 720,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        hits = resp.json().get("hits", [])
        if hits:
            return hits[0].get("largeImageURL") or hits[0].get("webformatURL")
    except Exception as e:
        print(f"  ⚠ Pixabay image search error: {e}")
    return None


def _search_wikimedia_image(keyword: str) -> Optional[str]:
    """Search Wikimedia Commons for an image. No API key needed."""
    try:
        resp = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": keyword,
                "gsrnamespace": 6,
                "gsrlimit": 5,
                "prop": "imageinfo",
                "iiprop": "url|mime|mediatype",
                "format": "json",
            },
            headers={"User-Agent": "NarratorBRoll/1.0 (narrator-tool)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            info = page.get("imageinfo", [{}])[0]
            mime = info.get("mime", "")
            if "image" in mime and info.get("mediatype") != "VIDEO":
                return info.get("url")
    except Exception as e:
        print(f"  ⚠ Wikimedia image search error: {e}")
    return None


# ── Media download ───────────────────────────────────────────


def download_media(url: str, dest_path: str) -> bool:
    """Download a file from URL to dest_path. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "NarratorBRoll/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as response, \
                open(dest_path, "wb") as out_file:
            shutil.copyfileobj(response, out_file)
        # Sanity check: file must be > 1KB
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024
    except Exception as e:
        print(f"  ✗ Download failed ({url[:60]}…): {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False


# ── ffmpeg helpers ───────────────────────────────────────────


def _get_duration_secs(path: str) -> float:
    """Get media duration via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def image_to_video(
    img_path: str,
    out_path: str,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 30,
) -> bool:
    """Convert a static image to a video with Ken Burns zoom effect via ffmpeg."""
    w, h = resolution.split("x")
    # zoompan: slow zoom from 1.0 to 1.1 over the duration
    total_frames = int(duration * fps)
    zoom_expr = f"'min(1.1, zoom+0.0003)'"
    vf = (
        f"zoompan=z={zoom_expr}:d={total_frames}:x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", img_path,
            "-vf", vf,
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            out_path,
        ],
        capture_output=True,
    )
    return result.returncode == 0


def _scale_clip(src: str, dst: str, resolution: str, fps: int) -> bool:
    """Scale + pad a raw clip to target resolution. Returns True on success."""
    w, h = resolution.split("x")
    scale_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={fps}"
    )
    r = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-vf", scale_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-an", dst,
        ],
        capture_output=True,
    )
    return r.returncode == 0


def fill_video_segment(
    clip_paths: list,
    out_path: str,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 30,
) -> bool:
    """
    Fill exactly `duration` seconds using one or more raw clips.

    Strategy:
      - Scale each clip to the target resolution.
      - Walk through clips in order, taking as much as needed from each.
      - If we still need more time after all clips are used, loop the
        last clip (avoiding repetition of earlier clips).
      - Concat everything into a single properly-timed segment.
    """
    if not clip_paths:
        return False

    tmp_dir = out_path + "_parts"
    os.makedirs(tmp_dir, exist_ok=True)
    parts = []         # scaled part files
    filled = 0.0       # seconds covered so far

    try:
        for ci, raw in enumerate(clip_paths):
            if filled >= duration:
                break
            need = duration - filled
            clip_dur = _get_duration_secs(raw)
            if clip_dur <= 0:
                continue

            take = min(clip_dur, need)   # seconds to take from this clip
            part_raw = os.path.join(tmp_dir, f"p{ci}_raw.mp4")
            part_scaled = os.path.join(tmp_dir, f"p{ci}.mp4")

            # Trim the raw clip to `take` seconds
            subprocess.run(
                ["ffmpeg", "-y", "-i", raw, "-t", str(take),
                 "-c", "copy", part_raw],
                capture_output=True,
            )
            if not os.path.exists(part_raw):
                continue

            # Scale to target resolution
            if _scale_clip(part_raw, part_scaled, resolution, fps):
                parts.append(part_scaled)
                filled += take

        # If we still need more time, loop the last used clip
        if filled < duration - 0.1 and parts:
            last_raw = clip_paths[-1]
            last_dur = _get_duration_secs(last_raw)
            if last_dur > 0:
                remaining = duration - filled
                loops_needed = int(remaining / last_dur) + 2
                loop_raw = os.path.join(tmp_dir, "loop_raw.mp4")
                loop_scaled = os.path.join(tmp_dir, "loop.mp4")
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-stream_loop", str(loops_needed),
                        "-i", last_raw,
                        "-t", str(remaining),
                        "-c", "copy", loop_raw,
                    ],
                    capture_output=True,
                )
                if os.path.exists(loop_raw) and _scale_clip(loop_raw, loop_scaled, resolution, fps):
                    parts.append(loop_scaled)

        if not parts:
            return False

        # Single clip — just move it
        if len(parts) == 1:
            import shutil as _sh
            _sh.copy2(parts[0], out_path)
            return True

        # Concat all parts
        concat_txt = os.path.join(tmp_dir, "concat.txt")
        with open(concat_txt, "w") as f:
            for p in parts:
                f.write(f"file '{os.path.abspath(p)}'\n")

        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_txt,
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an", out_path,
            ],
            capture_output=True,
        )
        return r.returncode == 0

    finally:
        import shutil as _sh
        if os.path.isdir(tmp_dir):
            _sh.rmtree(tmp_dir, ignore_errors=True)


def trim_video(
    clip_path: str,
    out_path: str,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 30,
) -> bool:
    """Backward-compat wrapper — single clip, fills via fill_video_segment."""
    return fill_video_segment([clip_path], out_path, duration, resolution, fps)


def create_color_segment(
    out_path: str,
    duration: float,
    resolution: str = "1920x1080",
    fps: int = 30,
    color: str = "black",
) -> bool:
    """Generate a solid-color video segment as a last-resort fallback."""
    w, h = resolution.split("x")
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:size={w}x{h}:rate={fps}",
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            out_path,
        ],
        capture_output=True,
    )
    return result.returncode == 0


# ── Segment builder (one chunk → one .mp4 segment) ──────────


def build_segment(
    index: int,
    text: str,
    audio_path: str,
    out_path: str,
    *,
    pexels_key: str = "",
    pixabay_key: str = "",
    coverr_key: str = "",
    gemini_key: str = "",
    keyword_mode: str = "rake",
    resolution: str = "1920x1080",
    fps: int = 30,
    segments_dir: str = "outputs/video/segments",
    progress_cb=None,
) -> dict:
    """
    Build one video segment for a script chunk.
    Returns a result dict with keys: index, keyword, source, type, path, ok.
    """

    def _emit(msg: str):
        if progress_cb:
            progress_cb(index, msg)

    os.makedirs(segments_dir, exist_ok=True)

    # ── 1. Get audio duration ────────────────────────────────
    duration = _get_duration_secs(audio_path)
    if duration <= 0:
        _emit("⚠ Cannot read audio duration")
        duration = 5.0  # safe default

    # ── 2. Extract keyword ────────────────────────────────────
    _emit("🔍 Extracting keyword…")
    keyword = extract_keyword(text, mode=keyword_mode, api_key=gemini_key)
    _emit(f"🔑 Keyword: «{keyword}»")

    result = {"index": index, "keyword": keyword, "source": None, "type": None,
              "path": out_path, "ok": False}

    raw_dir = os.path.join(segments_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_video = os.path.join(raw_dir, f"raw_{index:04d}_video")
    raw_image = os.path.join(raw_dir, f"raw_{index:04d}_image")

    # ── 3. Search for video clips (multi-clip fill for long chunks) ───────
    MAX_CLIPS = 5          # max different clips to fetch per chunk
    CLIP_TARGET = 15.0     # try to get clips of ~15 s each

    # Derive orientation from resolution for search APIs
    _orient = _orientation_from_resolution(resolution)   # 'portrait' / 'landscape' / 'square'

    providers_video = []
    if pexels_key:
        providers_video.append(("Pexels",   lambda k, _o=_orient: _search_pexels_video(k, pexels_key, _o)))
    if pixabay_key:
        providers_video.append(("Pixabay",  lambda k, _o=_orient: _search_pixabay_video(k, pixabay_key, _o)))
    if coverr_key:
        providers_video.append(("Coverr",   lambda k: _search_coverr_video(k, coverr_key)))
    providers_video.append(("Wikimedia", _search_wikimedia_video))

    # Build a set of search terms: primary keyword + word-level fallbacks
    kw_words = keyword.split()
    search_terms = [keyword]
    if len(kw_words) >= 2:
        search_terms.append(" ".join(kw_words[:2]))
    search_terms.append(kw_words[0])
    # De-duplicate while preserving order
    seen = set()
    search_terms = [t for t in search_terms if not (t in seen or seen.add(t))]

    raw_clips = []         # list of downloaded raw file paths
    covered  = 0.0         # seconds covered by downloaded clips
    source_names = []

    for term in search_terms:
        if covered >= duration or len(raw_clips) >= MAX_CLIPS:
            break
        for name, searcher in providers_video:
            if covered >= duration or len(raw_clips) >= MAX_CLIPS:
                break
            _emit(f"🎬 Searching {name} — '{term}'…")
            url = searcher(term)
            if not url:
                continue
            clip_idx = len(raw_clips)
            raw_path = os.path.join(raw_dir, f"raw_{index:04d}_v{clip_idx}.mp4")
            _emit(f"⬇ Downloading clip {clip_idx+1} from {name}…")
            if download_media(url, raw_path):
                clip_dur = _get_duration_secs(raw_path)
                if clip_dur > 0:
                    raw_clips.append(raw_path)
                    covered += clip_dur
                    source_names.append(name)
                    _emit(f"✓ Clip {clip_idx+1}: {clip_dur:.1f}s from {name} (total {covered:.1f}s / need {duration:.1f}s)")

    # ── 4. Stitch clips → exact-duration segment ──────────────
    if raw_clips:
        clips_label = "+".join(dict.fromkeys(source_names))  # e.g. "Pexels+Pixabay"
        n = len(raw_clips)
        _emit(f"✂ Filling {duration:.1f}s from {n} clip{'s' if n>1 else ''} ({clips_label})…")
        ok = fill_video_segment(raw_clips, out_path, duration, resolution, fps)
        if ok:
            result.update(source=clips_label, type="video", ok=True)
            return result
        _emit("⚠ Video fill failed, trying image fallback…")

    # ── 5. Fallback: search for image ─────────────────────────
    image_url = None
    providers_image = []
    if pexels_key:
        providers_image.append(("Pexels",  lambda k, _o=_orient: _search_pexels_image(k, pexels_key, _o)))
    if pixabay_key:
        providers_image.append(("Pixabay", lambda k, _o=_orient: _search_pixabay_image(k, pixabay_key, _o)))
    providers_image.append(("Wikimedia", _search_wikimedia_image))

    for name, searcher in providers_image:
        _emit(f"🖼 Searching {name} image…")
        url = searcher(keyword)
        if url:
            _emit(f"⬇ Downloading image from {name}…")
            ext = ".jpg"
            if url.lower().endswith(".png"):
                ext = ".png"
            raw_path = raw_image + ext
            if download_media(url, raw_path):
                image_url = raw_path
                source_name = f"{name} (image)"
                break

    # ── 6. Process image → video ──────────────────────────────
    if image_url:
        _emit(f"🎞 Converting image to video ({duration:.1f}s, Ken Burns)…")
        ok = image_to_video(image_url, out_path, duration, resolution, fps)
        if ok:
            result.update(source=source_name, type="image", ok=True)
            return result
        _emit("⚠ Image conversion failed, using color fallback…")

    # ── 7. Last resort: solid color ───────────────────────────
    _emit("⬛ Generating solid-color fallback…")
    ok = create_color_segment(out_path, duration, resolution, fps)
    result.update(source="fallback", type="color", ok=ok)
    return result


# ── Final merge: segments + audio → MP4 ─────────────────────


def merge_segments_with_audio(
    segment_paths: list[str],
    audio_path: str,
    output_path: str,
    fps: int = 30,
) -> bool:
    """
    Concatenate all video segments and mux with the full audio track.
    The video is extended (freeze-frame) if shorter than the audio so the
    FULL audio always plays — never cut short by -shortest.
    Returns True on success.
    """
    if not segment_paths:
        return False

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    concat_file = output_path + ".concat.txt"
    raw_concat  = output_path + ".concat.mp4"
    padded_vid  = output_path + ".padded.mp4"

    try:
        # ── Step 1: Concat all video segments ────────────────
        with open(concat_file, "w") as f:
            for p in segment_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")

        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                raw_concat,
            ],
            capture_output=True,
        )
        if r.returncode != 0:
            print("  ✗ Concat failed:", r.stderr.decode()[-400:])
            return False

        # ── Step 2: Ensure video >= audio duration ────────────
        audio_dur = _get_duration_secs(audio_path)
        video_dur = _get_duration_secs(raw_concat)

        mux_src = raw_concat   # will be replaced if padding needed

        if audio_dur > 0 and video_dur > 0 and video_dur < audio_dur - 0.5:
            # Pad with a freeze of the last frame to match audio length
            extra = audio_dur - video_dur + 0.5   # small buffer
            r2 = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", raw_concat,
                    "-vf", f"tpad=stop_mode=clone:stop_duration={extra:.3f}",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-an", padded_vid,
                ],
                capture_output=True,
            )
            if r2.returncode == 0:
                mux_src = padded_vid
            else:
                print("  ⚠ Freeze-pad failed, using unpadded video:",
                      r2.stderr.decode()[-200:])

        # ── Step 3: Mux audio — full audio duration guaranteed ─
        r3 = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", mux_src,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                # No -shortest: audio is the master track
                # Use -t to cap at audio duration (avoids freeze tail overflow)
                "-t", str(audio_dur) if audio_dur > 0 else "99999",
                output_path,
            ],
            capture_output=True,
        )
        if r3.returncode != 0:
            print("  ✗ Audio mux failed:", r3.stderr.decode()[-400:])
            return False

        return True

    finally:
        for tmp in [concat_file, raw_concat, padded_vid]:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

