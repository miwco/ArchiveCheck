"""Probe media and extract an analysis-friendly audio track with ffmpeg."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import CONFIG


@dataclass
class MediaInfo:
    duration_sec: float
    width: Optional[int]
    height: Optional[int]
    has_audio: bool
    video_codec: Optional[str]
    audio_codec: Optional[str]
    fps: Optional[float] = None
    audio_channels: Optional[int] = None
    audio_sample_rate: Optional[int] = None
    container: Optional[str] = None


def _parse_fps(rate: Optional[str]) -> Optional[float]:
    """Parse an ffprobe r_frame_rate like '25/1' into a float."""
    if not rate or rate == "0/0":
        return None
    try:
        num, _, den = rate.partition("/")
        return round(float(num) / float(den), 3) if den else float(num)
    except (ValueError, ZeroDivisionError):
        return None


def probe(video_path: str) -> MediaInfo:
    """Return basic stream info via ffprobe."""
    CONFIG.require("ffprobe")
    cmd = [
        CONFIG.ffprobe, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)

    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0.0) or 0.0)
    container = fmt.get("format_name")
    width = height = None
    vcodec = acodec = None
    fps = channels = sample_rate = None
    has_audio = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and width is None:
            width = stream.get("width")
            height = stream.get("height")
            vcodec = stream.get("codec_name")
            fps = _parse_fps(stream.get("r_frame_rate"))
        elif stream.get("codec_type") == "audio":
            has_audio = True
            if acodec is None:
                acodec = stream.get("codec_name")
                channels = stream.get("channels")
                sr = stream.get("sample_rate")
                sample_rate = int(sr) if sr else None

    return MediaInfo(
        duration_sec=duration,
        width=width,
        height=height,
        has_audio=has_audio,
        video_codec=vcodec,
        audio_codec=acodec,
        fps=fps,
        audio_channels=channels,
        audio_sample_rate=sample_rate,
        container=container,
    )


def extract_audio(video_path: str, out_wav: str) -> str:
    """Extract a mono, downsampled PCM wav suitable for segmentation/fingerprints.

    Returns the output path. Codec of the source is irrelevant; ffmpeg decodes
    it and we re-encode to plain PCM.
    """
    CONFIG.require("ffmpeg")
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        CONFIG.ffmpeg, "-y",
        "-i", video_path,
        "-vn",
        "-ac", str(CONFIG.audio_channels),
        "-ar", str(CONFIG.audio_sample_rate),
        "-acodec", "pcm_s16le",
        out_wav,
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_wav


def extract_audio_segment(video_path: str, start: float, duration: float, out_wav: str) -> str:
    """Extract a single time-bounded mono wav snippet (used for fingerprinting)."""
    CONFIG.require("ffmpeg")
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        CONFIG.ffmpeg, "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", video_path,
        "-vn",
        "-ac", str(CONFIG.audio_channels),
        "-ar", str(CONFIG.audio_sample_rate),
        "-acodec", "pcm_s16le",
        out_wav,
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_wav
