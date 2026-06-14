"""Find where music plays, with a pluggable backend.

Preferred backend: ``inaSpeechSegmenter`` (labels music/speech/noise) when it is
installed. It lets us report *total music time* and fingerprint only music.

Fallback backend: ffmpeg ``silencedetect`` finds non-silent regions which we
label ``unknown`` (could be music or speech). Fingerprinting then sorts them
out — speech simply returns no match — at the cost of the total-music metric.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import List, Literal

from ..config import CONFIG

Label = Literal["music", "speech", "noise", "unknown"]


@dataclass
class Segment:
    start: float
    end: float
    label: Label

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _have_ina() -> bool:
    try:
        import inaSpeechSegmenter  # noqa: F401
        return True
    except Exception:
        return False


def _segment_ina(wav_path: str) -> List[Segment]:
    from inaSpeechSegmenter import Segmenter  # type: ignore

    seg = Segmenter()
    raw = seg(wav_path)  # list of (label, start, end)
    out: List[Segment] = []
    for label, start, end in raw:
        norm: Label
        if label == "music":
            norm = "music"
        elif label in ("male", "female", "speech"):
            norm = "speech"
        else:
            norm = "noise"
        out.append(Segment(float(start), float(end), norm))
    return out


_SILENCE_RE = re.compile(r"silence_(start|end):\s*([0-9.]+)")


def _segment_silence(wav_path: str, total_duration: float) -> List[Segment]:
    """Invert ffmpeg silencedetect output into non-silent ``unknown`` regions."""
    CONFIG.require("ffmpeg")
    cmd = [
        CONFIG.ffmpeg, "-i", wav_path,
        "-af", "silencedetect=noise=-30dB:d=0.8",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    starts: List[float] = []
    ends: List[float] = []
    for kind, value in _SILENCE_RE.findall(proc.stderr):
        (starts if kind == "start" else ends).append(float(value))

    # Build silence intervals, then invert to get non-silent (sound) intervals.
    silences = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else total_duration
        silences.append((s, e))
    silences.sort()

    sound: List[Segment] = []
    cursor = 0.0
    for s, e in silences:
        if s > cursor:
            sound.append(Segment(cursor, s, "unknown"))
        cursor = max(cursor, e)
    if cursor < total_duration:
        sound.append(Segment(cursor, total_duration, "unknown"))
    return sound


def segment_audio(wav_path: str, total_duration: float) -> tuple[List[Segment], str]:
    """Return (segments, backend_name)."""
    if _have_ina():
        try:
            return _segment_ina(wav_path), "inaSpeechSegmenter"
        except Exception:
            pass  # fall through to silence-based
    return _segment_silence(wav_path, total_duration), "silencedetect"


def merge_adjacent(segments: List[Segment], label: Label, gap_tol: float = 1.5) -> List[Segment]:
    """Merge consecutive segments of ``label`` separated by <= gap_tol seconds."""
    chosen = [s for s in segments if s.label == label]
    chosen.sort(key=lambda s: s.start)
    merged: List[Segment] = []
    for s in chosen:
        if merged and s.start - merged[-1].end <= gap_tol:
            merged[-1] = Segment(merged[-1].start, max(merged[-1].end, s.end), label)
        else:
            merged.append(Segment(s.start, s.end, label))
    return merged
