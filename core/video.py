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

import json
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
            "You are an expert YouTube B-roll director choosing stock footage for a narration script line.\n"
            f"Narration line: \"{text}\"\n\n"
            "CRITICAL INSTRUCTIONS FOR STOCK SEARCH CONVERSION:\n"
            "1. DO NOT be literal with metaphors. If the script says 'bank account ripped open with a shovel' or 'cash vanished', "
            "search for the underlying visual meaning: 'empty wallet', 'stressed businessman laptop', 'low bank balance'.\n"
            "2. DO NOT search for abstract time/transition phrases (e.g. 'four days later', 'suddenly'). "
            "Instead, search for concrete visuals: 'phone call office', 'clocks ticking', 'empty desk'.\n"
            "3. DO NOT search for character names or dialogue tags. Search for visual equivalents: 'man talking phone', 'stressed face'.\n"
            "4. Keep the search query simple and highly searchable (2-3 words, lowercase, no punctuation).\n\n"
            "Return ONLY a short 2-3 word search query phrase, with no explanation, markdown formatting, or punctuation."
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


def _gemini_keyword_alternatives(text: str, api_key: str) -> list[str]:
    """
    Generate 4-5 semantically diverse stock-search queries for a script line.
    The first is the best match; the rest are fallbacks with different visual angles.
    Returns a list of 2-3 word lowercase search queries.
    Falls back to [_rake_keyword(text)] on error.
    """
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            "You are an expert YouTube B-roll director choosing stock video footage.\n"
            f"Script line: \"{text}\"\n\n"
            "Generate exactly 5 different stock video search queries for this line, ordered from MOST to LEAST relevant.\n"
            "Each query should represent a DIFFERENT visual angle of the same scene/emotion.\n\n"
            "CRITICAL RULES:\n"
            "1. Convert metaphors to concrete visuals: 'bank account ripped open with a shovel' → 'empty wallet', 'low bank balance screen'\n"
            "2. Convert time/transition phrases: 'four days later' → 'calendar flipping', 'office morning'\n"
            "3. Convert character names to visual actions: 'Derek wasn't there' → 'empty office chair', 'abandoned desk'\n"
            "4. Each query must be DIFFERENT — explore different visual angles: mood, setting, object, action\n"
            "5. Keep each query 2-3 words, lowercase, no punctuation\n\n"
            "Example for 'my bank account looked like someone ripped it open with a shovel':\n"
            "[\"empty wallet\", \"low bank balance\", \"stressed man laptop\", \"financial crisis\", \"broke person coins\"]\n\n"
            "Return ONLY a valid JSON array of exactly 5 strings. No explanation or markdown."
        )
        models = ["gemini-2.5-flash", "gemini-2.0-flash-001", "gemini-2.0-flash"]
        for model in models:
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                content = response.text.strip()
                if content.startswith("```"):
                    lines = content.splitlines()
                    content = "\n".join(lines[1:-1]).strip()
                alternatives = json.loads(content)
                if isinstance(alternatives, list) and len(alternatives) >= 2:
                    cleaned = [re.sub(r"[.!?,;]+$", "", str(k).strip().lower()).strip() for k in alternatives]
                    return [k for k in cleaned if k][:5]
            except Exception:
                continue
    except Exception as e:
        print(f"  ⚠ Gemini alternatives failed ({e}), using RAKE")
    # Fallback: single keyword from RAKE
    return [_rake_keyword(text)]


def extract_keyword(text: str, mode: str = "rake", api_key: str = "") -> str:
    """Extract a visual search keyword from a narration chunk."""
    if mode == "gemini" and api_key:
        return _gemini_keyword(text, api_key)
    return _rake_keyword(text)


def extract_keyword_alternatives(text: str, mode: str = "rake", api_key: str = "") -> list[str]:
    """
    Return a list of diverse search query alternatives for a script line.
    Gemini mode returns 5 semantically different queries; RAKE returns 1.
    """
    if mode == "gemini" and api_key:
        return _gemini_keyword_alternatives(text, api_key)
    kw = _rake_keyword(text)
    # Generate simple word-subset fallbacks for RAKE mode
    words = kw.split()
    alts = [kw]
    if len(words) >= 2:
        alts.append(" ".join(words[:2]))
    alts.append(words[0])
    return list(dict.fromkeys(alts))  # deduplicated


def extract_subclip_keywords(text: str, n_subs: int, mode: str = "rake", api_key: str = "") -> list[str]:
    """
    Extract exactly n_subs primary keywords sequentially representing the timeline of the text.
    Returns a flat list of n_subs primary keyword strings (for display/logging).
    Use extract_subclip_keyword_alternatives for the full alternatives-per-subclip grid.
    """
    alts_grid = extract_subclip_keyword_alternatives(text, n_subs, mode, api_key)
    return [alts[0] for alts in alts_grid]


def extract_subclip_keyword_alternatives(
    text: str, n_subs: int, mode: str = "rake", api_key: str = ""
) -> list[list[str]]:
    """
    For each of n_subs sub-clips, return a list of 3-5 diverse stock-search alternatives.
    Returns a list[list[str]] of shape [n_subs][n_alternatives].
    The first entry in each inner list is the best/primary match.
    """
    if n_subs <= 1:
        return [extract_keyword_alternatives(text, mode, api_key)]

    # 1. Try Gemini if enabled — ask for a 2D grid: n_subs rows × 5 alternatives each
    if mode == "gemini" and api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            prompt = (
                "You are an expert YouTube video editor and B-roll director.\n"
                "Script segment:\n"
                f"\"{text}\"\n\n"
                f"This segment will be split into exactly {n_subs} sequential video clips.\n"
                f"For EACH clip, provide exactly 5 different stock video search queries, "
                "ordered from MOST to LEAST relevant for that clip's moment in the script.\n\n"
                "CRITICAL RULES:\n"
                "1. Convert metaphors to concrete visuals: 'bank account ripped open' → 'empty wallet'\n"
                "2. Convert time phrases: 'four days later' → 'calendar flipping', 'office morning'\n"
                "3. Convert character names to visual actions: 'Derek wasn't there' → 'empty office desk'\n"
                "4. Each of the 5 alternatives must be a DIFFERENT visual angle (mood/setting/object/action)\n"
                "5. Keep each query 2-3 words, lowercase, no punctuation\n\n"
                f"Return ONLY a valid JSON array of exactly {n_subs} arrays, each containing exactly 5 strings.\n"
                f"Example for n=2: [[\"phone call office\", \"man on phone\", \"business call\", \"smartphone desk\", \"office worker calling\"], "
                "[\"empty wallet\", \"low bank balance\", \"stressed businessman\", \"financial crisis\", \"broke person\"]]"
            )
            models = ["gemini-2.5-flash", "gemini-2.0-flash-001", "gemini-2.0-flash"]
            for model in models:
                try:
                    response = client.models.generate_content(model=model, contents=prompt)
                    content = response.text.strip()
                    if content.startswith("```"):
                        lines = content.splitlines()
                        content = "\n".join(lines[1:-1]).strip()
                    grid = json.loads(content)
                    if isinstance(grid, list) and len(grid) == n_subs:
                        result = []
                        valid = True
                        for row in grid:
                            if not isinstance(row, list) or len(row) < 2:
                                valid = False
                                break
                            cleaned = [re.sub(r"[.!?,;]+$", "", str(k).strip().lower()).strip() for k in row]
                            cleaned = [k for k in cleaned if k][:5]
                            result.append(cleaned)
                        if valid:
                            return result
                except Exception:
                    continue
        except Exception as e:
            print(f"  ⚠ Gemini subclip alternatives failed: {e}")

    # 2. Offline fallback — split text into clauses, run RAKE on each
    clauses = [c.strip() for c in re.split(r'[.,;!?]', text) if c.strip()]
    if not clauses:
        clauses = [text]

    result = []
    if len(clauses) >= n_subs:
        chunk_size = len(clauses) / n_subs
        for i in range(n_subs):
            start = int(i * chunk_size)
            end = int((i + 1) * chunk_size) if i < n_subs - 1 else len(clauses)
            sub_text = " ".join(clauses[start:end])
            result.append(extract_keyword_alternatives(sub_text, mode="rake"))
    else:
        words = text.split()
        if words:
            word_chunk = len(words) / n_subs
            for i in range(n_subs):
                start = int(i * word_chunk)
                end = int((i + 1) * word_chunk) if i < n_subs - 1 else len(words)
                sub_text = " ".join(words[start:end])
                result.append(extract_keyword_alternatives(sub_text, mode="rake"))
        else:
            result.append(["broll video"])

    # Pad to exactly n_subs rows
    while len(result) < n_subs:
        result.append(result[-1] if result else ["broll video"])
    return result[:n_subs]


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
    # Determine the dimension predicate for the desired orientation.
    # This is applied both when the API filter is active and when we fall
    # back to an unfiltered search so a mislabelled clip never slips through.
    if orientation == "portrait":
        def _correct_dims(f: dict) -> bool:
            return f.get("height", 0) > f.get("width", 0)
    elif orientation == "landscape":
        def _correct_dims(f: dict) -> bool:
            return f.get("width", 0) >= f.get("height", 0)
    else:  # square or unknown — accept anything
        def _correct_dims(f: dict) -> bool:
            return True

    try:
        # Always try with the orientation filter first, then without as a
        # fallback (symmetric for both portrait and landscape).  In the
        # fallback pass we still validate actual dimensions so a wrongly-
        # labelled clip cannot sneak through.
        passes = [orientation, None]
        for orient in passes:
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
                # Filter to files whose actual pixel dimensions match
                matching = [f for f in files if _correct_dims(f)]
                if not matching:
                    continue
                if orientation == "portrait":
                    # Highest resolution portrait file wins
                    matching.sort(key=lambda f: f.get("height", 0), reverse=True)
                    return matching[0]["link"]
                else:
                    # Landscape / square: prefer HD width >= 1280
                    for quality in ["hd", "sd"]:
                        for vf in matching:
                            if vf.get("quality") == quality and vf.get("width", 0) >= 1280:
                                return vf["link"]
                    # Any correctly-oriented file is better than nothing
                    return matching[0]["link"]
            if videos:  # found results but none matched dims — try unfiltered pass
                continue
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
    # Dimension predicate applied to every candidate file so mislabelled
    # clips returned by the API are rejected before we ever use them.
    if orientation == "portrait":
        def _correct_dims(w: int, h: int) -> bool:
            return h > w
    elif orientation == "landscape":
        def _correct_dims(w: int, h: int) -> bool:
            return w >= h
    else:
        def _correct_dims(w: int, h: int) -> bool:
            return True

    try:
        # Try with the orientation filter first, then fall back to "all".
        # In both passes we validate actual pixel dimensions.
        passes = ([pixabay_orient, "all"] if pixabay_orient != "all" else ["all"])
        for orient in passes:
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
                    if not url:
                        continue
                    # Validate actual dimensions — Pixabay's orientation tag
                    # is occasionally wrong so we never rely on it alone.
                    w = v.get("width", 0)
                    h = v.get("height", 0)
                    if _correct_dims(w, h):
                        return url
            if hits:  # results exist but none passed dim check — try fallback pass
                continue
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
            timeout=10,
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
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img_path,
                "-vf", vf,
                "-t", str(duration),
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                out_path,
            ],
            capture_output=True,
            timeout=120,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _scale_clip(src: str, dst: str, resolution: str, fps: int) -> bool:
    """Scale + pad a raw clip to target resolution. Returns True on success."""
    w, h = resolution.split("x")
    scale_filter = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"fps={fps}"
    )
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", src,
                "-vf", scale_filter,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-an", dst,
            ],
            capture_output=True,
            timeout=120,
        )
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


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
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", raw, "-t", str(take),
                     "-c", "copy", part_raw],
                    capture_output=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                continue
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
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-y",
                            "-stream_loop", str(loops_needed),
                            "-i", last_raw,
                            "-t", str(remaining),
                            "-c", "copy", loop_raw,
                        ],
                        capture_output=True,
                        timeout=60,
                    )
                except subprocess.TimeoutExpired:
                    pass
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

        try:
            r = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_txt,
                    "-t", str(duration),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-an", out_path,
                ],
                capture_output=True,
                timeout=180,
            )
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            return False

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
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c={color}:size={w}x{h}:rate={fps}",
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                out_path,
            ],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


# ── Segment builder (one chunk → one .mp4 segment) ──────────


def _vary_keyword(keyword: str, sub_index: int) -> str:
    """
    Return a slightly varied keyword for a sub-clip to encourage different
    footage being returned. Uses the original keyword but shuffles word order
    or adds common visual adjectives on alternating passes.
    """
    words = keyword.split()
    if sub_index == 0 or len(words) <= 1:
        return keyword
    # Rotate words so "office worker typing" becomes "typing office worker" etc.
    rotated = words[sub_index % len(words):] + words[:sub_index % len(words)]
    return " ".join(rotated)


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
    youtube_key: str = "",
    keyword_mode: str = "rake",
    resolution: str = "1920x1080",
    fps: int = 30,
    segments_dir: str = "outputs/video/segments",
    clip_interval: float = 0.0,
    progress_cb=None,
) -> dict:
    """
    Build one video segment for a script chunk.

    If clip_interval > 0 and duration > clip_interval, the segment is split
    into sub-clips of up to clip_interval seconds each. Each sub-clip searches
    for a DIFFERENT video clip, giving visual variety for long narration chunks.

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
    raw_image = os.path.join(raw_dir, f"raw_{index:04d}_image")

    # Derive orientation from resolution for search APIs
    _orient = _orientation_from_resolution(resolution)

    # ── Helper: build provider lists ─────────────────────────
    def _make_video_providers():
        """Stock API video providers (Pexels/Pixabay/Wikimedia). YouTube CC is handled separately."""
        providers = []
        if pexels_key:
            providers.append(("Pexels",   lambda k, _o=_orient: _search_pexels_video(k, pexels_key, _o)))
        if pixabay_key:
            providers.append(("Pixabay",  lambda k, _o=_orient: _search_pixabay_video(k, pixabay_key, _o)))
        if coverr_key:
            providers.append(("Coverr",   lambda k: _search_coverr_video(k, coverr_key)))
        providers.append(("Wikimedia", _search_wikimedia_video))
        return providers


    def _make_image_providers():
        providers = []
        if pexels_key:
            providers.append(("Pexels",  lambda k, _o=_orient: _search_pexels_image(k, pexels_key, _o)))
        if pixabay_key:
            providers.append(("Pixabay", lambda k, _o=_orient: _search_pixabay_image(k, pixabay_key, _o)))
        providers.append(("Wikimedia", _search_wikimedia_image))
        return providers

    # ── Helper: search + download one clip given a list of keyword alternatives ──
    def _fetch_one_clip(kw_alternatives: list[str], raw_path: str) -> tuple[str | None, str | None, str | None]:
        """
        Try all alternative keywords across all video providers.
        Priority order: YouTube CC → Pexels → Pixabay → Coverr → Wikimedia.
        kw_alternatives is a list ordered from best to least relevant.
        Returns (path, source_name, matched_keyword) or (None, None, None).
        """
        # 1. Try YouTube CC first (best semantic matching, completely free)
        if youtube_key:
            from core.youtube_cc import search_and_download_youtube_cc
            for kw in kw_alternatives:
                _emit(f"  🎬 YouTubeCC — searching «{kw}»…")
                result_path = search_and_download_youtube_cc(kw, raw_path, youtube_key, _orient)
                if result_path and os.path.exists(result_path) and _get_duration_secs(result_path) > 0:
                    _emit(f"  ✓ YouTubeCC found clip for «{kw}»")
                    return result_path, "YouTubeCC", kw

        # 2. Fall back to stock API providers (Pexels / Pixabay / Wikimedia)
        for kw in kw_alternatives:
            for name, searcher in _make_video_providers():
                url = searcher(kw)
                if not url:
                    continue
                if download_media(url, raw_path):
                    if _get_duration_secs(raw_path) > 0:
                        return raw_path, name, kw
        return None, None, None


    # ── 3. Decide strategy: sub-clip splitting vs. single fill ──

    use_subclips = clip_interval > 0 and duration > clip_interval

    if use_subclips:
        # Split duration into N sub-clips of up to clip_interval seconds each
        n_subs = max(1, int(duration / clip_interval) + (1 if duration % clip_interval > 0.5 else 0))
        sub_dur = duration / n_subs   # distribute evenly to avoid tiny last clip
        _emit(f"⏱ Clip interval {clip_interval:.0f}s → {n_subs} sub-clips of {sub_dur:.1f}s each")

        # Extract N×5 alternatives grid from Gemini
        sub_alts_grid = extract_subclip_keyword_alternatives(text, n_subs, mode=keyword_mode, api_key=gemini_key)
        primary_kws = [alts[0] for alts in sub_alts_grid]
        _emit(f"🔑 Sub-clip primary keywords: {', '.join([f'«{k}»' for k in primary_kws])}")

        sub_parts = []     # paths of finished sub-clip segment files
        all_sources: list[str] = []
        matched_kws: list[str] = []
        tmp_sub_dir = out_path + "_subs"
        os.makedirs(tmp_sub_dir, exist_ok=True)

        try:
            for si in range(n_subs):
                alts = sub_alts_grid[si]
                raw_path = os.path.join(raw_dir, f"raw_{index:04d}_sub{si}.mp4")
                sub_out  = os.path.join(tmp_sub_dir, f"sub_{si:04d}.mp4")

                _emit(f"🎬 Sub-clip {si+1}/{n_subs} — trying {len(alts)} alternatives: {alts[:3]}…")
                clip_path, src_name, matched_kw = _fetch_one_clip(alts, raw_path)

                if clip_path:
                    _emit(f"⬇ Filling sub-clip {si+1} ({sub_dur:.1f}s) from {src_name} via «{matched_kw}»…")
                    ok_sub = fill_video_segment([clip_path], sub_out, sub_dur, resolution, fps)
                    if ok_sub:
                        sub_parts.append(sub_out)
                        all_sources.append(src_name)
                        matched_kws.append(matched_kw)
                        _emit(f"✓ Sub-clip {si+1} done ({src_name})")
                        continue

                # Fallback: try image for this sub-clip using all alternatives
                _emit(f"🖼 Sub-clip {si+1}: trying image fallback with {len(alts)} alternatives…")
                img_raw = os.path.join(raw_dir, f"raw_{index:04d}_sub{si}_img.jpg")
                image_found = False
                for alt_kw in alts:
                    for name, searcher in _make_image_providers():
                        url = searcher(alt_kw)
                        if url and download_media(url, img_raw):
                            ok_img = image_to_video(img_raw, sub_out, sub_dur, resolution, fps)
                            if ok_img:
                                sub_parts.append(sub_out)
                                all_sources.append(f"{name}(img)")
                                matched_kws.append(alt_kw)
                                image_found = True
                                break
                    if image_found:
                        break

                if not image_found:
                    # Last resort: solid color for this sub-clip
                    create_color_segment(sub_out, sub_dur, resolution, fps)
                    sub_parts.append(sub_out)
                    all_sources.append("fallback")
                    matched_kws.append(alts[0])

            if sub_parts:
                _emit(f"✂ Concatenating {len(sub_parts)} sub-clips…")
                concat_txt = os.path.join(tmp_sub_dir, "concat.txt")
                with open(concat_txt, "w") as f:
                    for p in sub_parts:
                        f.write(f"file '{os.path.abspath(p)}'\n")
                try:
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                         "-i", concat_txt,
                         "-t", str(duration),
                         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                         "-an", out_path],
                        capture_output=True,
                        timeout=180,
                    )
                except subprocess.TimeoutExpired:
                    r = None
                if r and r.returncode == 0:
                    sources_label = "+".join(dict.fromkeys(all_sources))
                    result.update(source=sources_label, type="video", ok=True, keyword=", ".join(matched_kws))
                    return result

        finally:
            import shutil as _sh
            if os.path.isdir(tmp_sub_dir):
                _sh.rmtree(tmp_sub_dir, ignore_errors=True)

        _emit("⚠ Sub-clip strategy failed, falling back to single-clip fill…")

    # ── 4. Single-clip fill strategy — uses full alternatives list ──
    MAX_CLIPS = 5

    # Get diverse alternatives for the main keyword instead of word-chopped variants
    kw_alternatives = extract_keyword_alternatives(text, mode=keyword_mode, api_key=gemini_key)
    _emit(f"🔑 Keyword alternatives: {kw_alternatives}")

    raw_clips: list[str] = []
    covered   = 0.0
    source_names: list[str] = []
    matched_kw_list: list[str] = []

    for alt_kw in kw_alternatives:
        if covered >= duration or len(raw_clips) >= MAX_CLIPS:
            break
        raw_path = os.path.join(raw_dir, f"raw_{index:04d}_v{len(raw_clips)}.mp4")
        clip_path, src_name, matched_kw = _fetch_one_clip([alt_kw], raw_path)
        if clip_path:
            clip_dur = _get_duration_secs(clip_path)
            if clip_dur > 0:
                raw_clips.append(clip_path)
                covered += clip_dur
                source_names.append(src_name)
                matched_kw_list.append(matched_kw)
                _emit(f"✓ Clip {len(raw_clips)}: {clip_dur:.1f}s from {src_name} via «{matched_kw}» (total {covered:.1f}s / need {duration:.1f}s)")

    # ── 5. Stitch clips → exact-duration segment ──────────────
    if raw_clips:
        clips_label = "+".join(dict.fromkeys(source_names))
        n = len(raw_clips)
        _emit(f"✂ Filling {duration:.1f}s from {n} clip{'s' if n>1 else ''} ({clips_label})…")
        ok = fill_video_segment(raw_clips, out_path, duration, resolution, fps)
        if ok:
            best_kw = matched_kw_list[0] if matched_kw_list else keyword
            result.update(source=clips_label, type="video", ok=True, keyword=best_kw)
            return result
        _emit("⚠ Video fill failed, trying image fallback…")

    # ── 6. Fallback: search for image using all alternatives ──
    image_url = None
    source_name = "fallback"
    for alt_kw in kw_alternatives:
        for name, searcher in _make_image_providers():
            _emit(f"🖼 Searching {name} image — «{alt_kw}»…")
            url = searcher(alt_kw)
            if url:
                _emit(f"⬇ Downloading image from {name}…")
                ext = ".jpg"
                if url.lower().endswith(".png"):
                    ext = ".png"
                raw_path = raw_image + ext
                if download_media(url, raw_path):
                    image_url = raw_path
                    source_name = f"{name} (image)"
                    keyword = alt_kw  # update keyword to what actually matched
                    break
        if image_url:
            break

    # ── 7. Process image → video ──────────────────────────────
    if image_url:
        _emit(f"🎞 Converting image to video ({duration:.1f}s, Ken Burns)…")
        ok = image_to_video(image_url, out_path, duration, resolution, fps)
        if ok:
            result.update(source=source_name, type="image", ok=True)
            return result
        _emit("⚠ Image conversion failed, using color fallback…")

    # ── 8. Last resort: solid color ───────────────────────────
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

        try:
            r = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    raw_concat,
                ],
                capture_output=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            print("  ✗ Concat timed out")
            return False
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
            try:
                r2 = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", raw_concat,
                        "-vf", f"tpad=stop_mode=clone:stop_duration={extra:.3f}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        "-an", padded_vid,
                    ],
                    capture_output=True,
                    timeout=120,
                )
            except subprocess.TimeoutExpired:
                r2 = None
            if r2 and r2.returncode == 0:
                mux_src = padded_vid
            else:
                print("  ⚠ Freeze-pad failed/timed-out, using unpadded video")

        # ── Step 3: Mux audio — full audio duration guaranteed ─
        try:
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
                    "-t", str(audio_dur) if audio_dur > 0 else "99999",
                    output_path,
                ],
                capture_output=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            print("  ✗ Audio mux timed out")
            return False
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

