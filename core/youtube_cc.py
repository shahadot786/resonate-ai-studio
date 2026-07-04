# ============================================================
# core/youtube_cc.py — YouTube Creative Commons B-Roll search
#
# Strategy:
#   1. Search YouTube Data API v3 for Creative Commons videos
#      matching the keyword (videoLicense=creativeCommon)
#   2. Pick the best result (shortest duration >= 5s, most views)
#   3. Download with yt-dlp at the desired resolution
#   4. Return the local file path for ffmpeg processing
#
# Why YouTube CC beats Pexels/Pixabay:
#   - Millions of CC-licensed clips vs ~20K on Pexels free tier
#   - Semantically tagged by creators, not keyword-matched titles
#   - Covers abstract/metaphorical concepts that stock sites miss
#   - Completely free (YouTube Data API: 10,000 units/day free)
# ============================================================

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Optional


# ── YouTube Data API v3 search ────────────────────────────────

_YT_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _iso8601_to_seconds(duration: str) -> int:
    """Convert ISO 8601 duration (PT1M30S) to total seconds."""
    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    m = re.match(pattern, duration)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + minutes * 60 + s


def search_youtube_cc(
    keyword: str,
    api_key: str,
    max_results: int = 10,
    min_duration_s: int = 5,
    max_duration_s: int = 120,
) -> Optional[str]:
    """
    Search YouTube for a Creative Commons licensed video matching keyword.
    Returns a YouTube video URL (https://www.youtube.com/watch?v=...) or None.

    Uses YouTube Data API v3 — free tier gives 10,000 units/day.
    Each search costs 100 units; each videos.list costs 1 unit.
    So you get ~100 searches/day on the free tier.
    """
    try:
        import requests

        # Step 1: Search for CC-licensed videos
        search_resp = requests.get(
            _YT_SEARCH_URL,
            params={
                "key": api_key,
                "q": keyword,
                "part": "id",
                "type": "video",
                "videoLicense": "creativeCommon",
                "videoDuration": "short",   # < 4 minutes — avoids full documentaries
                "maxResults": max_results,
                "order": "relevance",
                "safeSearch": "moderate",
            },
            timeout=10,
        )
        if search_resp.status_code != 200:
            print(f"  ⚠ YouTube search error {search_resp.status_code}: {search_resp.text[:200]}")
            return None

        items = search_resp.json().get("items", [])
        if not items:
            return None

        video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
        if not video_ids:
            return None

        # Step 2: Get video details (duration, view count) to pick best match
        detail_resp = requests.get(
            _YT_VIDEOS_URL,
            params={
                "key": api_key,
                "id": ",".join(video_ids),
                "part": "contentDetails,statistics",
            },
            timeout=10,
        )
        if detail_resp.status_code != 200:
            # Fallback: just use the first result without filtering
            vid_id = video_ids[0]
            return f"https://www.youtube.com/watch?v={vid_id}"

        video_details = detail_resp.json().get("items", [])

        # Step 3: Score and pick best video
        candidates = []
        for detail in video_details:
            vid_id = detail["id"]
            duration_iso = detail.get("contentDetails", {}).get("duration", "PT0S")
            duration_s = _iso8601_to_seconds(duration_iso)
            view_count = int(detail.get("statistics", {}).get("viewCount", 0))

            # Filter by duration
            if duration_s < min_duration_s or duration_s > max_duration_s:
                continue

            candidates.append({
                "id": vid_id,
                "duration_s": duration_s,
                "view_count": view_count,
            })

        if not candidates:
            # No candidates passed filters — use first result anyway
            return f"https://www.youtube.com/watch?v={video_ids[0]}"

        # Sort by view count descending (most popular = most likely high quality)
        candidates.sort(key=lambda x: x["view_count"], reverse=True)
        best = candidates[0]
        return f"https://www.youtube.com/watch?v={best['id']}"

    except Exception as e:
        print(f"  ⚠ YouTube CC search error: {e}")
        return None


# ── yt-dlp download ───────────────────────────────────────────

def _ytdlp_available() -> bool:
    """Check if yt-dlp is available as a Python module or CLI."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def download_youtube_clip(
    video_url: str,
    dest_path: str,
    max_filesize_mb: int = 100,
) -> bool:
    """
    Download a YouTube video using yt-dlp.
    Saves to dest_path (should end in .mp4).
    Returns True on success.

    Tries yt-dlp Python module first, falls back to CLI subprocess.
    """
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    # Prefer mp4, max 720p to keep file sizes manageable
    format_spec = (
        "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]"
        "/bestvideo[height<=720]+bestaudio"
        "/best[height<=720]"
        "/best"
    )

    # Try yt-dlp Python module (preferred)
    try:
        import yt_dlp

        ydl_opts = {
            "format": format_spec,
            "outtmpl": dest_path,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
            "max_filesize": max_filesize_mb * 1024 * 1024,
            "socket_timeout": 30,
            "retries": 2,
            # Avoid age-gating / login prompts
            "age_limit": 17,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024

    except ImportError:
        pass
    except Exception as e:
        print(f"  ⚠ yt-dlp module download failed: {e}")

    # Fallback: CLI subprocess
    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "-f", format_spec,
                "--merge-output-format", "mp4",
                "--max-filesize", f"{max_filesize_mb}M",
                "-o", dest_path,
                "--quiet",
                "--no-warnings",
                video_url,
            ],
            capture_output=True,
            timeout=120,
        )
        return result.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1024

    except Exception as e:
        print(f"  ⚠ yt-dlp CLI download failed: {e}")
        return False


# ── High-level helper used by video.py ───────────────────────

def search_and_download_youtube_cc(
    keyword: str,
    dest_path: str,
    youtube_api_key: str,
    orientation: str = "landscape",
) -> Optional[str]:
    """
    Search YouTube CC for keyword and download the best clip to dest_path.
    Returns dest_path on success, None on failure.

    orientation is ignored for now (YouTube search doesn't filter by it)
    but kept for API compatibility with other provider functions.
    """
    if not youtube_api_key:
        return None

    if not _ytdlp_available():
        print("  ⚠ yt-dlp not available — skipping YouTube CC source")
        return None

    video_url = search_youtube_cc(keyword, youtube_api_key)
    if not video_url:
        return None

    print(f"  🎬 YouTube CC match: {video_url}")
    success = download_youtube_clip(video_url, dest_path)
    if success:
        return dest_path
    return None
