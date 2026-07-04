# ============================================================
# core/video.py — B-Roll video pipeline
#
# Pipeline per chunk:
#   1. Extract search keyword (Groq Llama-3.3 with rotating keys)
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

def _simple_visual_fallback(text: str) -> list[str]:
    """A clean, minimal fallback that filters out stop words if the Groq API fails."""
    clean = re.sub(r'[."\'`!?,;:]', "", text).strip().lower()
    stop_words = {
        "i", "me", "my", "we", "our", "you", "your", "he", "him", "his", "she", "her",
        "they", "them", "their", "it", "its", "the", "a", "an", "and", "or", "but",
        "in", "on", "at", "to", "for", "with", "by", "from", "of", "about", "was", "were",
        "is", "am", "are", "had", "have", "has", "do", "does", "did", "been", "would", "should", "could",
        "four", "days", "later", "suddenly", "then", "after", "before", "once", "again"
    }
    words = [w for w in clean.split() if w not in stop_words]
    if not words:
        return ["office workspace"]

    res = []
    if len(words) >= 3:
        res.append(" ".join(words[:3]))
    if len(words) >= 2:
        res.append(" ".join(words[:2]))
    res.append(words[0])
    res.append("office setting")
    res.append("corporate worker")
    return list(dict.fromkeys(res))[:5]


def _groq_keyword_alternatives(text: str, groq_keys: list[str]) -> list[str]:
    """
    Generate 5 semantically diverse stock-search queries for a script line using Groq.
    Rotates through the list of keys if rate limited (429).
    """
    if not groq_keys:
        return []

def _update_groq_stats(key: str, success: bool, rate_limited: bool):
    import json
    import os
    from datetime import datetime

    stats_file = "outputs/.groq_stats.json"
    os.makedirs("outputs", exist_ok=True)

    stats = {"total_requests": 0, "successful_requests": 0, "rate_limits_hit": 0, "keys": {}}
    if os.path.exists(stats_file):
        try:
            with open(stats_file) as f:
                stats = json.load(f)
        except Exception:
            pass

    if "keys" not in stats or not isinstance(stats["keys"], dict):
        stats["keys"] = {}

    stats["total_requests"] += 1
    if success:
        stats["successful_requests"] += 1
    if rate_limited:
        stats["rate_limits_hit"] += 1

    key_id = key[:16] + "..."
    key_stats = stats["keys"].get(key_id, {
        "prefix": key[:12] + "...",
        "status": "active",
        "requests": 0,
        "rate_limits": 0,
        "last_used": ""
    })

    key_stats["requests"] += 1
    key_stats["last_used"] = datetime.now().isoformat()
    if rate_limited:
        key_stats["status"] = "rate_limited (429)"
        key_stats["rate_limits"] += 1
    elif success:
        key_stats["status"] = "active"

    stats["keys"][key_id] = key_stats

    try:
        with open(stats_file, "w") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass


def _groq_keyword_alternatives(text: str, groq_keys: list[str]) -> list[str]:
    """
    Generate 5 semantically diverse stock-search queries for a script line using Groq.
    Rotates through the list of keys if rate limited (429).
    """
    if not groq_keys:
        return []

    prompt = (
        "You are an expert B-roll director for YouTube narration videos. Your job is to pick VISUAL stock footage search keywords.\n\n"
        f"NARRATION LINE: \"{text}\"\n\n"
        "STRICT RULES:\n"
        "- Think about what a CAMERA would show on screen, not what the words literally say\n"
        "- Convert abstract phrases to concrete visuals: 'bank account ripped open' = 'empty wallet stress'\n"
        "- Convert time phrases like 'four days later' to mood/scene visuals: 'dim office morning'\n"
        "- NEVER include names (Derek, Sandra etc) — replace with visual: 'empty desk'\n"
        "- NEVER include transition words (later, suddenly, then) — show the SCENE instead\n"
        "- Each keyword must be 2-3 words, searchable on stock sites like Pexels\n\n"
        "Return exactly 5 different visual search keywords, one per line, NO numbering, NO punctuation, NO explanation. Just the 5 keywords."
    )

    for key in groq_keys:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 100,
                },
                timeout=10
            )
            if resp.status_code == 200:
                _update_groq_stats(key, success=True, rate_limited=False)
                body = resp.json()
                content = body["choices"][0]["message"]["content"].strip()
                lines = [line.strip().lower() for line in content.splitlines() if line.strip()]
                cleaned = []
                for line in lines:
                    line = re.sub(r"^\d+\.\s*", "", line)
                    line = re.sub(r"^[-*+]\s*", "", line)
                    line = re.sub(r'[."\'`!?,;:]', "", line).strip()
                    if line:
                        cleaned.append(line)
                if len(cleaned) >= 2:
                    return cleaned[:5]
            elif resp.status_code == 429:
                _update_groq_stats(key, success=False, rate_limited=True)
                print(f"  ⚠ Groq Key {key[:12]}... hit rate limit (429), rotating to next key...")
                continue
            else:
                _update_groq_stats(key, success=False, rate_limited=False)
                print(f"  ⚠ Groq Key {key[:12]}... error {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            _update_groq_stats(key, success=False, rate_limited=False)
            print(f"  ⚠ Groq key extraction error: {e}")
            continue
    return []


def _groq_subclip_keyword_alternatives(text: str, n_subs: int, groq_keys: list[str]) -> list[list[str]]:
    """
    For each of n_subs sub-clips, return a list of 5 diverse search query alternatives using Groq.
    Returns a list[list[str]] of shape [n_subs][n_alternatives].
    """
    if not groq_keys:
        return []

    prompt = (
        "You are an expert YouTube video editor and B-roll director.\n"
        "Script segment:\n"
        f"\"{text}\"\n\n"
        f"This segment will be split into exactly {n_subs} sequential video clips.\n"
        f"For EACH clip, provide exactly 5 different stock video search queries, "
        "ordered from MOST to LEAST relevant for that clip's moment in the script.\n\n"
        "STRICT RULES:\n"
        "- Think about what a CAMERA would show on screen, not what the words literally say\n"
        "- Convert metaphors to concrete visuals: 'bank account ripped open' = 'empty wallet'\n"
        "- Convert time phrases like 'four days later' to mood/scene visuals: 'dim office morning'\n"
        "- NEVER include names (Derek, Sandra etc) — replace with visual: 'empty desk'\n"
        "- NEVER include transition words (later, suddenly, then) — show the SCENE instead\n"
        "- Each keyword must be 2-3 words, searchable on stock sites like Pexels\n\n"
        f"Return ONLY a valid JSON array of exactly {n_subs} arrays, each containing exactly 5 strings.\n"
        f"Example for n=2: [[\"phone call office\", \"man on phone\", \"business call\", \"smartphone desk\", \"office worker calling\"], "
        "[\"empty wallet\", \"low bank balance\", \"stressed businessman\", \"financial crisis\", \"broke person\"]]"
    )

    for key in groq_keys:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that always outputs JSON. The root JSON object must contain a key 'data' which is the array of arrays."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
                timeout=15
            )
            if resp.status_code == 200:
                _update_groq_stats(key, success=True, rate_limited=False)
                body = resp.json()
                content = body["choices"][0]["message"]["content"].strip()
                data = json.loads(content)
                if isinstance(data, dict) and "data" in data:
                    grid = data["data"]
                else:
                    grid = data

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
            elif resp.status_code == 429:
                _update_groq_stats(key, success=False, rate_limited=True)
                print(f"  ⚠ Groq Key {key[:12]}... hit rate limit (429), rotating...")
                continue
            else:
                _update_groq_stats(key, success=False, rate_limited=False)
                print(f"  ⚠ Groq Key {key[:12]}... error {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            _update_groq_stats(key, success=False, rate_limited=False)
            print(f"  ⚠ Groq subclip extraction error: {e}")
            continue
    return []


def extract_keyword(text: str, mode: str = "rake", api_key: str = "", groq_keys: list[str] = None) -> str:
    """Extract a visual search keyword from a narration chunk."""
    alts = extract_keyword_alternatives(text, mode, api_key, groq_keys)
    return alts[0] if alts else "office"


def extract_keyword_alternatives(text: str, mode: str = "rake", api_key: str = "", groq_keys: list[str] = None) -> list[str]:
    """
    Return a list of diverse search query alternatives for a script line.
    Uses Groq API; falls back to a clean manual stop-word filtering if keys fail.
    """
    if groq_keys:
        res = _groq_keyword_alternatives(text, groq_keys)
        if res:
            return res

    # Emergency fallback (non-API stop-word filtering)
    return _simple_visual_fallback(text)


def extract_subclip_keywords(text: str, n_subs: int, mode: str = "rake", api_key: str = "", groq_keys: list[str] = None) -> list[str]:
    """
    Extract exactly n_subs primary keywords sequentially representing the timeline of the text.
    """
    alts_grid = extract_subclip_keyword_alternatives(text, n_subs, mode, api_key, groq_keys)
    return [alts[0] for alts in alts_grid]


def extract_subclip_keyword_alternatives(
    text: str, n_subs: int, mode: str = "rake", api_key: str = "", groq_keys: list[str] = None
) -> list[list[str]]:
    """
    For each of n_subs sub-clips, return a list of 5 diverse search query alternatives using Groq.
    """
    if n_subs <= 1:
        return [extract_keyword_alternatives(text, mode, api_key, groq_keys)]

    if groq_keys:
        res = _groq_subclip_keyword_alternatives(text, n_subs, groq_keys)
        if res:
            return res

    # Minimal fallback split by clauses
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
            result.append(extract_keyword_alternatives(sub_text, mode, api_key, groq_keys))
    else:
        words = text.split()
        if words:
            word_chunk = len(words) / n_subs
            for i in range(n_subs):
                start = int(i * word_chunk)
                end = int((i + 1) * word_chunk) if i < n_subs - 1 else len(words)
                sub_text = " ".join(words[start:end])
                result.append(extract_keyword_alternatives(sub_text, mode, api_key, groq_keys))
        else:
            result.append(["office"])

    while len(result) < n_subs:
        result.append(result[-1] if result else ["office"])
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


def get_retry_session(retries=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504)):
    from requests.adapters import HTTPAdapter
    from urllib3.util import Retry
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def download_media(url: str, dest_path: str) -> bool:
    """Download a file from URL to dest_path. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        session = get_retry_session()
        headers = {"User-Agent": "NarratorBRoll/1.0"}
        
        with session.get(url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as out_file:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        out_file.write(chunk)
                        
        # Sanity check: file must be > 1KB
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024
    except Exception as e:
        print(f"  ✗ Download failed ({url[:60]}…): {e}")
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except Exception:
                pass
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
    groq_keys: list[str] = None,
    keyword_mode: str = "groq",
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
    keyword = extract_keyword(text, mode=keyword_mode, api_key="", groq_keys=groq_keys)


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
        Try all alternative keywords across all stock video providers (Pexels → Pixabay → Coverr → Wikimedia).
        kw_alternatives is a list ordered from best to least relevant.
        Returns (path, source_name, matched_keyword) or (None, None, None).
        """
        # Try stock API providers (Pexels / Pixabay / Wikimedia)
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

        # Extract N×5 alternatives grid from Groq
        sub_alts_grid = extract_subclip_keyword_alternatives(
            text, n_subs, mode=keyword_mode, api_key="", groq_keys=groq_keys
        )
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
    kw_alternatives = extract_keyword_alternatives(
        text, mode=keyword_mode, api_key="", groq_keys=groq_keys
    )
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
            print("  ⚠ Concat demuxer failed. Attempting robust transcoding filter complex fallback...")
            inputs = []
            filter_str = ""
            for idx, p in enumerate(segment_paths):
                inputs.extend(["-i", p])
                filter_str += f"[{idx}:v]"
            filter_str += f"concat=n={len(segment_paths)}:v=1:a=0[outv]"
            
            try:
                r_fallback = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        *inputs,
                        "-filter_complex", filter_str,
                        "-map", "[outv]",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        raw_concat,
                    ],
                    capture_output=True,
                    timeout=600,
                )
                if r_fallback.returncode != 0:
                    print("  ✗ Fallback transcode concat failed:", r_fallback.stderr.decode()[-400:])
                    return False
            except Exception as fe:
                print("  ✗ Fallback transcode concat error:", fe)
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

