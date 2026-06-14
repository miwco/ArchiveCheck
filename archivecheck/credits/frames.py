"""Extract frames from the end-credits window with ffmpeg."""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import List, Tuple

from ..config import CONFIG
import subprocess


def credits_window(duration: float, window_sec: float | None = None) -> Tuple[float, float]:
    """Return (start, end) of the assumed credits window (default: last N sec)."""
    win = window_sec if window_sec is not None else CONFIG.credits_window_sec
    start = max(0.0, duration - win)
    return start, duration


def extract_credit_frames(
    video_path: str,
    out_dir: str,
    start: float,
    end: float,
    fps: float | None = None,
) -> List[Tuple[float, str]]:
    """Sample frames across [start, end]. Returns (timestamp_sec, path) pairs."""
    CONFIG.require("ffmpeg")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rate = fps if fps is not None else CONFIG.credits_fps
    pattern = os.path.join(out_dir, "frame_%05d.jpg")
    cmd = [
        CONFIG.ffmpeg, "-y",
        "-ss", f"{start:.3f}",
        "-t", f"{max(0.0, end - start):.3f}",
        "-i", video_path,
        "-vf", f"fps={rate}",
        "-q:v", "2",
        pattern,
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)

    frames = sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))
    out: List[Tuple[float, str]] = []
    for i, fpath in enumerate(frames):
        ts = start + (i / rate)
        out.append((ts, fpath))
    return out
