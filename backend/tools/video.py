"""
Video tools using FFmpeg.
Requires ffmpeg to be installed and accessible on PATH (or configured via ffmpeg_path).
"""
from __future__ import annotations

import asyncio
import json
import shlex
import shutil
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.tools.base import BaseTool


def _ffmpeg() -> str:
    """Return the configured ffmpeg binary path."""
    return get_config().tools.video.ffmpeg_path


async def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run an ffmpeg command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", f"Timeout after {timeout}s"
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _check_ffmpeg() -> str | None:
    """Return an error string if ffmpeg is not available, else None."""
    path = _ffmpeg()
    if not shutil.which(path):
        return (
            f"ffmpeg not found at '{path}'. "
            "Install ffmpeg and make sure it's on PATH, or set ffmpeg_path in Settings → Video."
        )
    return None


# ── Tools ─────────────────────────────────────────────────────────────────────

class CreateVideoFromImagesTool(BaseTool):
    name = "create_video_from_images"
    description = (
        "Create a video from a list of image files using FFmpeg. "
        "Each image is shown for the specified duration. Optionally add an audio track."
    )
    parameters = {
        "type": "object",
        "properties": {
            "images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of image file paths (in order). Supports JPEG, PNG, WebP.",
            },
            "output": {
                "type": "string",
                "description": "Output video file path (e.g. /output/video.mp4).",
            },
            "duration_per_image": {
                "type": "number",
                "description": "Seconds each image is shown (default: 3).",
                "default": 3.0,
            },
            "fps": {
                "type": "number",
                "description": "Output frames per second (default: 25).",
                "default": 25.0,
            },
            "audio": {
                "type": "string",
                "description": "Optional audio file path to add as background music.",
            },
            "resolution": {
                "type": "string",
                "description": "Output resolution e.g. '1920x1080'. Default: matches first image.",
            },
        },
        "required": ["images", "output"],
    }

    async def run(
        self,
        images: list[str],
        output: str,
        duration_per_image: float = 3.0,
        fps: float = 25.0,
        audio: str | None = None,
        resolution: str | None = None,
        **_: Any,
    ) -> str:
        err = _check_ffmpeg()
        if err:
            return err
        if not images:
            return "Error: no images provided."

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Write a concat file listing each image with its duration
        concat_lines: list[str] = []
        for img in images:
            p = Path(img).expanduser()
            if not p.exists():
                return f"Error: image not found: {img}"
            concat_lines.append(f"file '{p.as_posix()}'")
            concat_lines.append(f"duration {duration_per_image}")
        # ffmpeg concat demuxer needs the last file repeated without duration
        last = Path(images[-1]).expanduser()
        concat_lines.append(f"file '{last.as_posix()}'")

        concat_file = out_path.parent / f"_concat_{out_path.stem}.txt"
        concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

        try:
            vf = f"fps={fps}"
            if resolution:
                w, h = resolution.split("x")
                vf += f",scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

            cmd = [
                _ffmpeg(), "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-vf", vf,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
            ]

            if audio:
                audio_path = Path(audio).expanduser()
                if not audio_path.exists():
                    return f"Error: audio file not found: {audio}"
                cmd += ["-i", str(audio_path), "-c:a", "aac", "-shortest"]

            cmd.append(str(out_path))

            rc, stdout, stderr = await _run(cmd, timeout=300)
            if rc != 0:
                return f"FFmpeg error (code {rc}):\n{stderr[-1000:]}"

            size_mb = out_path.stat().st_size / 1_048_576
            return (
                f"Video created: {out_path}\n"
                f"Images: {len(images)} | Duration per image: {duration_per_image}s | "
                f"FPS: {fps} | Size: {size_mb:.1f} MB"
            )
        finally:
            concat_file.unlink(missing_ok=True)


class ConvertVideoTool(BaseTool):
    name = "convert_video"
    description = (
        "Convert a video file to a different format or resolution using FFmpeg. "
        "Supports MP4, WebM, MKV, AVI, MOV and more."
    )
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Input video file path."},
            "output": {"type": "string", "description": "Output file path (extension determines format)."},
            "resolution": {
                "type": "string",
                "description": "Target resolution e.g. '1280x720'. Optional.",
            },
            "fps": {
                "type": "number",
                "description": "Target frames per second. Optional.",
            },
            "crf": {
                "type": "integer",
                "description": "Quality factor for H.264 (0–51, lower = better, default 23).",
                "default": 23,
            },
        },
        "required": ["input", "output"],
    }

    async def run(
        self,
        input: str,
        output: str,
        resolution: str | None = None,
        fps: float | None = None,
        crf: int = 23,
        **_: Any,
    ) -> str:
        err = _check_ffmpeg()
        if err:
            return err

        in_path = Path(input).expanduser()
        if not in_path.exists():
            return f"Error: input file not found: {input}"

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        vf_parts: list[str] = []
        if resolution:
            w, h = resolution.split("x")
            vf_parts.append(f"scale={w}:{h}")
        if fps:
            vf_parts.append(f"fps={fps}")

        cmd = [_ffmpeg(), "-y", "-i", str(in_path)]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        cmd += ["-c:v", "libx264", "-crf", str(crf), "-c:a", "aac", str(out_path)]

        rc, _, stderr = await _run(cmd, timeout=300)
        if rc != 0:
            return f"FFmpeg error (code {rc}):\n{stderr[-1000:]}"

        size_mb = out_path.stat().st_size / 1_048_576
        return f"Converted: {out_path} ({size_mb:.1f} MB)"


class TrimVideoTool(BaseTool):
    name = "trim_video"
    description = "Trim a video to a specific time range using FFmpeg."
    parameters = {
        "type": "object",
        "properties": {
            "input":  {"type": "string", "description": "Input video file path."},
            "output": {"type": "string", "description": "Output file path."},
            "start":  {"type": "string", "description": "Start time in HH:MM:SS or seconds (e.g. '00:00:10' or '10')."},
            "end":    {"type": "string", "description": "End time in HH:MM:SS or seconds. Optional (trims to end of file)."},
        },
        "required": ["input", "output", "start"],
    }

    async def run(
        self,
        input: str,
        output: str,
        start: str,
        end: str | None = None,
        **_: Any,
    ) -> str:
        err = _check_ffmpeg()
        if err:
            return err

        in_path = Path(input).expanduser()
        if not in_path.exists():
            return f"Error: input file not found: {input}"

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [_ffmpeg(), "-y", "-i", str(in_path), "-ss", start]
        if end:
            cmd += ["-to", end]
        cmd += ["-c", "copy", str(out_path)]

        rc, _, stderr = await _run(cmd, timeout=120)
        if rc != 0:
            return f"FFmpeg error (code {rc}):\n{stderr[-1000:]}"

        return f"Trimmed video saved: {out_path}"


class ExtractFramesTool(BaseTool):
    name = "extract_frames"
    description = "Extract frames from a video as image files using FFmpeg."
    parameters = {
        "type": "object",
        "properties": {
            "input":      {"type": "string", "description": "Input video file path."},
            "output_dir": {"type": "string", "description": "Directory to save extracted frames."},
            "fps": {
                "type": "number",
                "description": "Frames per second to extract (default: 1 = one frame per second).",
                "default": 1.0,
            },
            "format": {
                "type": "string",
                "description": "Image format: 'jpg' or 'png' (default: 'jpg').",
                "default": "jpg",
            },
        },
        "required": ["input", "output_dir"],
    }

    async def run(
        self,
        input: str,
        output_dir: str,
        fps: float = 1.0,
        format: str = "jpg",
        **_: Any,
    ) -> str:
        err = _check_ffmpeg()
        if err:
            return err

        in_path = Path(input).expanduser()
        if not in_path.exists():
            return f"Error: input file not found: {input}"

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        pattern = str(out_dir / f"frame_%04d.{format}")
        cmd = [_ffmpeg(), "-y", "-i", str(in_path), "-vf", f"fps={fps}", pattern]

        rc, _, stderr = await _run(cmd, timeout=300)
        if rc != 0:
            return f"FFmpeg error (code {rc}):\n{stderr[-1000:]}"

        count = len(list(out_dir.glob(f"frame_*.{format}")))
        return f"Extracted {count} frames to {out_dir}"


class AddAudioToVideoTool(BaseTool):
    name = "add_audio_to_video"
    description = "Add or replace the audio track of a video using FFmpeg."
    parameters = {
        "type": "object",
        "properties": {
            "video":  {"type": "string", "description": "Input video file path."},
            "audio":  {"type": "string", "description": "Audio file path (MP3, WAV, AAC, etc.)."},
            "output": {"type": "string", "description": "Output file path."},
            "loop_audio": {
                "type": "boolean",
                "description": "Loop the audio if it's shorter than the video (default: false).",
                "default": False,
            },
        },
        "required": ["video", "audio", "output"],
    }

    async def run(
        self,
        video: str,
        audio: str,
        output: str,
        loop_audio: bool = False,
        **_: Any,
    ) -> str:
        err = _check_ffmpeg()
        if err:
            return err

        v_path = Path(video).expanduser()
        a_path = Path(audio).expanduser()
        if not v_path.exists():
            return f"Error: video not found: {video}"
        if not a_path.exists():
            return f"Error: audio not found: {audio}"

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [_ffmpeg(), "-y", "-i", str(v_path)]
        if loop_audio:
            cmd += ["-stream_loop", "-1", "-i", str(a_path)]
        else:
            cmd += ["-i", str(a_path)]
        cmd += ["-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", "-shortest", str(out_path)]

        rc, _, stderr = await _run(cmd, timeout=300)
        if rc != 0:
            return f"FFmpeg error (code {rc}):\n{stderr[-1000:]}"

        return f"Video with audio saved: {out_path}"


VIDEO_TOOLS: list[BaseTool] = [
    CreateVideoFromImagesTool(),
    ConvertVideoTool(),
    TrimVideoTool(),
    ExtractFramesTool(),
    AddAudioToVideoTool(),
]
