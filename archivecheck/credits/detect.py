"""Auto-detect where the end credits start.

Brightness and edge density don't separate credits from dark/textured footage,
but *readable text* does: a cheap native-resolution OCR scan returns lines on
credit frames and nothing on footage. We coarsely scan the trailing part of the
film, then return the start of the final run of text frames so the dense OCR pass
only covers the actual credits (faster, and no pre-credit footage to filter).
"""

from __future__ import annotations

import glob
import os
import subprocess
import tempfile
from typing import List, Optional, Tuple

from ..config import CONFIG
from .ocr import OcrEngine


def _credits_start_from_flags(
    samples: List[Tuple[float, bool]],
    duration: float,
    gap: float,
    margin: float,
    min_text_frames: int,
    tail_tol: float,
) -> Optional[float]:
    """Pure core: from (time, has_text) samples, find the credits start time.

    Returns the start of the final run of text frames (bridging gaps <= ``gap``),
    minus a small ``margin``. Returns None when there isn't a credible credits
    block near the end (so the caller falls back to a fixed window).
    """
    text_times = [t for t, has in samples if has]
    if len(text_times) < min_text_frames:
        return None
    if duration - text_times[-1] > tail_tol:
        return None  # text isn't near the end -> probably not the credits

    start: Optional[float] = None
    for t, has in reversed(samples):
        if has:
            start = t
        elif start is not None and (start - t) > gap:
            break
    if start is None:
        return None
    return max(0.0, start - margin)


def detect_credits_window(
    video_path: str, duration: float, engine: OcrEngine
) -> Optional[Tuple[float, float]]:
    """Return (start, end) of the detected credits, or None to fall back."""
    if not engine.available() or duration <= 0:
        return None
    search_sec = min(CONFIG.credits_search_sec, duration)
    step = max(1.0, CONFIG.credits_detect_step)
    start0 = max(0.0, duration - search_sec)

    work = tempfile.mkdtemp(prefix="vc_detect_")
    try:
        pattern = os.path.join(work, "d_%05d.png")
        # One decode pass, native resolution (fast OCR), one frame every `step` sec.
        cmd = [
            CONFIG.ffmpeg, "-y", "-ss", f"{start0:.3f}",
            "-t", f"{duration - start0:.3f}", "-i", video_path,
            "-vf", f"fps={1.0 / step:.6f}", "-q:v", "2", pattern,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        frames = sorted(glob.glob(os.path.join(work, "d_*.png")))
        if not frames:
            return None
        samples: List[Tuple[float, bool]] = []
        for i, fp in enumerate(frames):
            t = start0 + i * step
            samples.append((t, len(engine.image_to_lines(fp)) >= 1))
    except Exception:
        return None
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    start = _credits_start_from_flags(
        samples, duration,
        gap=CONFIG.credits_detect_gap,
        margin=CONFIG.credits_detect_margin,
        min_text_frames=CONFIG.credits_min_text_frames,
        tail_tol=CONFIG.credits_detect_tail_tol,
    )
    if start is None:
        return None
    return (start, duration)
