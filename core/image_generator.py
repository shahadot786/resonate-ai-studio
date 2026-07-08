# ============================================================
# core/image_generator.py — Image generation engine
# ============================================================

import os
import random
import urllib.parse
import requests

# Cache for local Stable Diffusion pipeline to avoid reloading
_local_pipeline = None

def generate_image_free_api(prompt: str, out_path: str, width: int = 1080, height: int = 1920, model: str = "flux") -> bool:
    """
    Generate an image using the free, keyless Pollinations.ai API with automatic model fallbacks on load/rate limit.
    Returns True on success.
    """
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        # Random seed to ensure varied images for same prompt if run multiple times
        seed = random.randint(1, 10000000)
        encoded_prompt = urllib.parse.quote(prompt)
        
        # Try the requested model first, then fall back to fast/highly available models on error
        fallback_models = [model]
        if model != "turbo":
            fallback_models.append("turbo")
        fallback_models.append(None)  # None maps to default pollinations generator
        
        for current_model in fallback_models:
            model_part = f"&model={current_model}" if current_model else ""
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&seed={seed}{model_part}"
            
            display_name = current_model if current_model else "default"
            print(f"  🖼 Requesting free API image ({display_name}): {url[:100]}...")
            
            try:
                response = requests.get(url, timeout=35)
                if response.status_code == 200:
                    # Validate content type is actually an image
                    content_type = response.headers.get("Content-Type", "")
                    if not content_type.startswith("image/"):
                        print(f"  ⚠ Pollinations API ({display_name}) returned non-image content ({content_type}). Trying fallback...")
                        continue
                    with open(out_path, "wb") as f:
                        f.write(response.content)
                    print(f"  ✓ Image generated successfully using ({display_name}): {out_path}")
                    return True
                else:
                    print(f"  ⚠ Pollinations API ({display_name}) returned error code: {response.status_code}. Trying fallback...")
            except Exception as e:
                print(f"  ⚠ Pollinations request failed for ({display_name}): {e}. Trying fallback...")
                
        return False
            
    except Exception as e:
        print(f"  ⚠ Free image generation exception: {e}")
        return False




def generate_image_local(prompt: str, out_path: str, width: int = 512, height: int = 768) -> bool:
    """
    Generate an image using Stable Diffusion locally on Mac M1 (MPS).
    Requires torch, diffusers, and transformers to be installed.
    Uses cached pipeline to avoid reloading weights.
    Returns True on success.
    """
    global _local_pipeline
    try:
        import torch
        from diffusers import StableDiffusionPipeline
        
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        
        # Load and cache pipeline if not already loaded
        if _local_pipeline is None:
            model_id = "Lykon/DreamShaper-v8"  # A fast, high-quality, lightweight model
            print(f"  🔌 Loading local Stable Diffusion model ({model_id}) onto Apple Silicon MPS...")
            
            # Select torch device: mps if Apple Silicon, otherwise cpu
            if torch.backends.mps.is_available():
                device = "mps"
                torch_dtype = torch.float16
            else:
                device = "cpu"
                torch_dtype = torch.float32
                
            print(f"  🖥 Device selected: {device}")
            
            _local_pipeline = StableDiffusionPipeline.from_pretrained(
                model_id, 
                torch_dtype=torch_dtype,
                safety_checker=None  # Disable to save RAM
            )
            _local_pipeline.to(device)
            # Enable attention slicing for low memory systems (like base M1 Mac)
            _local_pipeline.enable_attention_slicing()
            print("  ✓ Local SD pipeline initialized and cached.")
            
        # Run inference
        print(f"  🎨 Generating image locally via Stable Diffusion: «{prompt[:60]}...»")
        
        # Determine device
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        
        # DreamShaper does well with 20-30 steps
        with torch.autocast(device if device != "mps" else "cpu"):
            image = _local_pipeline(
                prompt,
                num_inference_steps=25,
                guidance_scale=7.5,
                width=width,
                height=height
            ).images[0]
            
        image.save(out_path)
        print(f"  ✓ Local Image saved: {out_path}")
        return True
        
    except ImportError:
        print("  ⚠ Local SD packages (torch, diffusers) not installed. Falling back to Free API...")
        return generate_image_free_api(prompt, out_path)
    except Exception as e:
        print(f"  ⚠ Local SD image generation failed: {e}. Falling back to Free API...")
        return generate_image_free_api(prompt, out_path)


def generate_image(prompt: str, out_path: str, provider: str = "free_api", style_preset: str = "cinematic") -> bool:
    """
    Master dispatcher for generating images. Appends dynamic style guardrails.
    """
    # Stylization presets to ensure beautiful aesthetic consistency
    style_suffixes = {
        "cinematic": ", rendered in a cinematic style with professional film lighting, atmospheric depth, and high production value",
        "fantasy": ", rendered in a beautiful digital fantasy art style with vibrant, mystical lighting and rich colors",
        "realistic": ", captured as a highly detailed realistic photograph with sharp focus, natural skin textures, and authentic lighting",
        "anime": ", rendered in a clean modern anime art style with vibrant colors and detailed character illustration",
        "cyberpunk": ", in a cyberpunk aesthetic featuring glowing neon lights, futuristic cityscape details, and a rich synthwave color palette",
        "sketch": ", drawn in a highly artistic hand-drawn charcoal sketch style with clean cross-hatching and shading textures"
    }
    
    style_suffix = style_suffixes.get(style_preset.lower(), style_suffixes["cinematic"])
    full_prompt = f"{prompt}{style_suffix}"
    
    if provider == "local":
        # Local Stable Diffusion is faster/easier at smaller sizes, we scale it later using FFmpeg
        # dreamshaper supports 512x768 portrait well
        return generate_image_local(full_prompt, out_path, width=512, height=768)
        
    # Map friendly provider name to Pollinations model ID
    model_mapping = {
        "flux": "flux",
        "ideogram": "ideogram-v4-quality",
        "grok": "grok-imagine-pro",
        "wan": "wan-image-pro",
        "gptimage": "gptimage-large",
        "turbo": "turbo"
    }
    target_model = model_mapping.get(provider.lower(), "flux")
    return generate_image_free_api(full_prompt, out_path, width=1080, height=1920, model=target_model)
