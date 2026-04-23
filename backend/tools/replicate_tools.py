"""
Replicate API tools — AI image and video generation.
Requires a Replicate API key (set in Settings → Replicate).
Install: pip install replicate
"""
from __future__ import annotations

import mimetypes
import os
import urllib.request
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool


def _api_key() -> str:
    return get_config().tools.replicate.api_key or os.environ.get("REPLICATE_API_TOKEN", "")


def _check() -> str | None:
    if not _api_key():
        return (
            "Replicate API key not configured. "
            "Add it in Settings → Replicate, or set REPLICATE_API_TOKEN env var."
        )
    return None


async def _run_replicate(model: str, input_data: dict) -> Any:
    """Run a Replicate model and return its output (blocking in thread pool)."""
    import asyncio
    import functools

    key = _api_key()

    def _sync():
        try:
            import replicate
        except ImportError:
            raise RuntimeError(
                "replicate package not installed. Run: pip install replicate"
            )
        client = replicate.Client(api_token=key)
        return client.run(model, input=input_data)

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(_sync))


def _download(url: str, dest: Path) -> Path:
    """Download a URL to dest. Returns the path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # If dest has no extension, guess from Content-Type
    if not dest.suffix:
        with urllib.request.urlopen(url) as r:
            ctype = r.headers.get_content_type()
            ext = mimetypes.guess_extension(ctype) or ".bin"
            dest = dest.with_suffix(ext)
    urllib.request.urlretrieve(url, dest)
    return dest


def _resolve_output(output_path: str | None, default_name: str) -> Path:
    if output_path:
        p = Path(output_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    # Default: save to ~/LocalForge_outputs/
    out_dir = Path.home() / "LocalForge_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / default_name


# ── Image generation ──────────────────────────────────────────────────────────

class GenerateImageTool(BaseTool):
    name = "generate_image"
    description = (
        "Generate an image using AI via Replicate. "
        "Default model: Flux Schnell (fast, free-tier friendly). "
        "The result is downloaded and saved locally."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text description of the image to generate.",
            },
            "output_path": {
                "type": "string",
                "description": "Where to save the image (e.g. /output/image.png). "
                               "If omitted, saves to ~/LocalForge_outputs/.",
            },
            "model": {
                "type": "string",
                "description": (
                    "Replicate model identifier. Examples:\n"
                    "- 'black-forest-labs/flux-schnell' (fast, default)\n"
                    "- 'black-forest-labs/flux-dev' (higher quality)\n"
                    "- 'stability-ai/sdxl'\n"
                    "- 'recraft-ai/recraft-v3'"
                ),
            },
            "width":  {"type": "integer", "description": "Image width in pixels (default: 1024).", "default": 1024},
            "height": {"type": "integer", "description": "Image height in pixels (default: 1024).", "default": 1024},
            "num_outputs": {
                "type": "integer",
                "description": "Number of images to generate (default: 1).",
                "default": 1,
            },
            "negative_prompt": {
                "type": "string",
                "description": "Things to avoid in the image (not all models support this).",
            },
        },
        "required": ["prompt"],
    }

    async def run(
        self,
        prompt: str,
        output_path: str | None = None,
        model: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_outputs: int = 1,
        negative_prompt: str | None = None,
        **_: Any,
    ) -> str:
        err = _check()
        if err:
            return err

        cfg = get_config().tools.replicate
        model = model or cfg.default_image_model

        input_data: dict = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_outputs": num_outputs,
        }
        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt

        try:
            output = await _run_replicate(model, input_data)
        except Exception as e:
            return f"Replicate error: {e}"

        # Output is typically a list of URLs or FileOutput objects
        urls: list[str] = []
        if isinstance(output, list):
            for item in output:
                urls.append(str(item))
        else:
            urls.append(str(output))

        saved: list[str] = []
        for i, url in enumerate(urls):
            suffix = f"_{i+1}" if len(urls) > 1 else ""
            dest = _resolve_output(
                f"{output_path}{suffix}" if output_path and len(urls) > 1 else output_path,
                f"image{suffix}.png",
            )
            try:
                dest = _download(url, dest)
                saved.append(str(dest))
            except Exception as e:
                saved.append(f"(download failed: {e} — URL: {url})")

        return (
            f"Generated {len(saved)} image(s) with {model}:\n"
            + "\n".join(f"  • {p}" for p in saved)
        )


# ── Video generation ──────────────────────────────────────────────────────────

class GenerateVideoTool(BaseTool):
    name = "generate_video"
    description = (
        "Generate a video using AI via Replicate. "
        "Supports text-to-video and image-to-video models. "
        "The result is downloaded and saved locally."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text description of the video to generate.",
            },
            "output_path": {
                "type": "string",
                "description": "Where to save the video (e.g. /output/video.mp4). "
                               "If omitted, saves to ~/LocalForge_outputs/.",
            },
            "model": {
                "type": "string",
                "description": (
                    "Replicate model identifier. Examples:\n"
                    "- 'wan-ai/wan2.1-t2v-480p' (text-to-video, default)\n"
                    "- 'wan-ai/wan2.1-i2v-480p' (image-to-video)\n"
                    "- 'minimax/video-01' (high quality)\n"
                    "- 'lightricks/ltx-video'"
                ),
            },
            "image": {
                "type": "string",
                "description": "Path to a local image for image-to-video models.",
            },
            "duration": {
                "type": "integer",
                "description": "Video duration in seconds (model-dependent, default: 5).",
                "default": 5,
            },
            "negative_prompt": {
                "type": "string",
                "description": "Things to avoid in the video.",
            },
        },
        "required": ["prompt"],
    }

    async def run(
        self,
        prompt: str,
        output_path: str | None = None,
        model: str | None = None,
        image: str | None = None,
        duration: int = 5,
        negative_prompt: str | None = None,
        **_: Any,
    ) -> str:
        err = _check()
        if err:
            return err

        cfg = get_config().tools.replicate
        model = model or cfg.default_video_model

        input_data: dict = {"prompt": prompt, "duration": duration}
        if negative_prompt:
            input_data["negative_prompt"] = negative_prompt

        # Attach image for i2v models (upload as data URI or file object)
        if image:
            img_path = Path(image).expanduser()
            if not img_path.exists():
                return f"Error: image not found: {image}"
            mime = mimetypes.guess_type(str(img_path))[0] or "image/jpeg"
            import base64
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            input_data["image"] = f"data:{mime};base64,{b64}"

        try:
            output = await _run_replicate(model, input_data)
        except Exception as e:
            return f"Replicate error: {e}"

        url = str(output[0]) if isinstance(output, list) else str(output)

        dest = _resolve_output(output_path, "video.mp4")
        try:
            dest = _download(url, dest)
        except Exception as e:
            return f"Video generated but download failed: {e}\nURL: {url}"

        size_mb = dest.stat().st_size / 1_048_576
        return (
            f"Video generated with {model}:\n"
            f"  • Saved to: {dest}\n"
            f"  • Size: {size_mb:.1f} MB"
        )


REPLICATE_TOOLS: list[BaseTool] = [
    GenerateImageTool(),
    GenerateVideoTool(),
]
