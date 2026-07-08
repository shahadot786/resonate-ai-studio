# ============================================================
# core/script.py — Script file parsing with per-chunk overrides
# ============================================================

import re
import json
import requests
import random
from pathlib import Path

# Regex for inline override tags: [voice:xyz] [emotion:some text here]
_TAG_RE = re.compile(r"\[(voice|emotion):([^\]]+)\]", re.IGNORECASE)


def parse_chunk_overrides(line: str) -> dict:
    """Extract [voice:X], [emotion:X], or shorthand [X] tags from a line.

    Returns a dict with keys:
        text     — the cleaned text with tags removed
        voice    — override voice or None
        emotion  — override emotion or None
    """
    overrides = {"voice": None, "emotion": None}
    emotions = []

    def _extract(match):
        content = match.group(1).strip()
        if ":" in content:
            parts = content.split(":", 1)
            key = parts[0].strip().lower()
            val = parts[1].strip()
            if key == "voice":
                overrides["voice"] = val
            elif key == "emotion":
                emotions.append(val)
        else:
            # Shorthand emotion direction, e.g. [Bitter laugh]
            emotions.append(content)
        return ""

    # Replace all [...] blocks
    clean = re.sub(r"\[([^\]]+)\]", _extract, line).strip()
    
    # Collapse multiple spaces left by removed tags
    clean = re.sub(r"\s{2,}", " ", clean)

    if emotions:
        overrides["emotion"] = ", ".join(emotions)

    return {"text": clean, **overrides}


def parse_script(filepath: str) -> list[dict]:
    """Read a script file and return chunks with optional overrides.

    Each non-empty line is one chunk. Blank lines are ignored.
    Lines can contain optional override tags:
        [voice:serena] [emotion:Whispered, fearful] I heard footsteps.

    Returns a list of dicts:
        [{"text": "...", "voice": None, "emotion": None}, ...]
    """
    text = Path(filepath).read_text(encoding="utf-8")
    chunks = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        chunk = parse_chunk_overrides(stripped)
        if chunk["text"]:  # skip lines that were only tags
            chunks.append(chunk)
    return chunks


# ── Title-to-Shorts LLM Script & Prompt Generator ─────────────────

def generate_shorts_script_from_title(
    title: str,
    target_duration: int = 60,
    style_preset: str = "cinematic",
    groq_keys: list[str] = None,
    available_voices: list[str] = None,
) -> dict:
    """
    Generate an engaging video script and matching visual prompts from a title.
    Determines appropriate segment count dynamically based on the target duration.
    Selects a voice from available_voices matching the sentiment/genre of the script.
    
    Returns a dictionary structured as:
    {
      "recommended_voice": "am_adam",
      "tone_analysis": "Motivational, intense",
      "segments": [
         {"text": "...", "image_prompt": "...", "transition": "..."},
         ...
      ]
    }
    """
    if not groq_keys:
        raise ValueError("No Groq API keys provided for script generation")
        
    if not available_voices:
        available_voices = ["af_sarah", "am_adam", "am_fenrir", "am_onyx", "bf_emma", "bm_daniel"]
        
    # Dynamic visual pacing recommendation: let the LLM suggest between 2.0s and 4.0s visual changes.
    # We pass the target duration and let the LLM output the optimal segment count.
    min_seg = max(3, int(target_duration / 4))
    max_seg = min(22, int(target_duration / 2))
    
    prompt = f"""You are an expert viral YouTube Shorts and TikTok content creator and creative director.
Your task is to design a high-retention, highly engaging short-form video concept and script based on the title: "{title}".
To prevent the video from feeling like generic "reused content", you must custom-tailor the visual style, pacing, voiceover, and transitions to perfectly match the story.

USA TARGET AUDIENCE HOOK STRATEGY:
- The target audience is the USA. Use highly engaging, colloquial, fast-paced American English, utilizing powerful active verbs, intriguing questions, or scroll-stopping facts.
- The script MUST open with a powerful, high-energy hook in the first 1-2 seconds (the very first scene) that immediately triggers curiosity or surprise (e.g., "This space secret will keep you up tonight..." or "Most Americans have no idea that...").
- The first scene's visual prompt must feature a dramatic, detailed, focal point visual that pairs perfectly with a sudden zoom in or zoom out effect (e.g., a massive planetary collision or a close-up of a glowing mysterious object) to grab attention instantly.

The target duration is {target_duration} seconds.
Based on the target duration and topic pacing, determine the optimal number of scenes/visual changes (images).
- For high retention, visuals should change every 2 to 4 seconds.
- Suggest between {min_seg} and {max_seg} scenes/segments.
- Each scene must feature a punchy narration line (approx. 6 to 10 spoken words per scene) and a highly descriptive image generation prompt (no text overlay).

Select from the following options:
1. Valid Voice Models (select the single best match for the tone of the script):
{json.dumps(available_voices)}
2. Valid Visual Style Presets (select the one that best matches the mood):
["cinematic", "fantasy", "realistic", "anime", "cyberpunk", "sketch"]
3. Valid Transition Styles (select the one that matches the pace. NOTE: The transition for the very first segment should recommend 'zoomin' to trigger the attention hook):
["crossfade", "slideup", "circlecrop", "zoomin", "random"]

Your output must be a raw JSON object containing these concepts and the script segments. Do not include markdown codeblocks, preambles, or explanations.

JSON Schema:
{{
  "recommended_voice": "string (MUST be one from the list of valid voices above)",
  "recommended_style": "string (MUST be one from the visual style list above)",
  "recommended_transition": "string (MUST be one from the transition list above)",
  "suggested_image_count": "number (the number of scenes/images you decided to output)",
  "tone_analysis": "string (description of the theme, tone, and genre)",
  "creation_tip": "string (pacing advice or styling guide to make it feel premium, high-retention, and avoid reused content warnings)",
  "segments": [
    {{
      "text": "string (6-10 spoken words, spelling out numbers like 'three' instead of '3' for TTS compatibility)",
      "image_prompt": "string (A descriptive visual prompt in natural language. Prioritize the main subject at the beginning, followed by details of the action, composition, lighting, and camera style. Avoid tag-soup keywords like 'photorealistic' or '8k'. DO NOT include text in the prompt)",
      "transition": "string (one from the transition list above)"
    }}
  ]
}}

Write the JSON output now:"""


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
                    "temperature": 0.6, # slightly higher for creativity
                    "max_tokens": 2000,
                },
                timeout=30
            )
            # Log key success stats
            try:
                from core.video import _update_groq_stats
                if resp.status_code == 200:
                    _update_groq_stats(key, success=True, rate_limited=False)
                elif resp.status_code == 429:
                    _update_groq_stats(key, success=False, rate_limited=True)
            except Exception:
                pass

            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                
                # Strip markdown code blocks if Llama formats it with ```json
                if content.startswith("```"):
                    lines = content.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                    
                data = json.loads(content)
                # Validation
                if "segments" in data and len(data["segments"]) > 0:
                    # Enforce voice recommendation validity
                    if data.get("recommended_voice") not in available_voices:
                        data["recommended_voice"] = available_voices[0]
                    return data
            elif resp.status_code == 429:
                print(f"  ⚠ Groq key {key[:12]}... rate limited (429) during script gen, rotating...")
                continue
        except Exception as e:
            print(f"  ⚠ Failed Groq script generation call: {e}")
            continue
            
    raise RuntimeError("All Groq keys failed or rate-limited during script generation")

