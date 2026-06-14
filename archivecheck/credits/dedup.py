"""Collapse the same credit line repeated across scrolled frames.

Scrolling credits make one physical line appear in many consecutive frames at
shifting positions. We walk frames in time order and drop a line if it fuzzily
matches one we accepted recently, keeping first-seen order and timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List

from .ocr import OcrFrame
from ..config import CONFIG


@dataclass
class CreditLine:
    timestamp: float
    text: str


def _similar(a: str, b: str) -> int:
    return int(round(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100))


def dedup_lines(frames: List[OcrFrame], window: int = 60) -> List[CreditLine]:
    accepted: List[CreditLine] = []
    threshold = CONFIG.dedup_similarity
    for frame in frames:
        for raw in frame.lines:
            text = raw.strip()
            if len(text) < 2:
                continue
            recent = accepted[-window:]
            if any(_similar(text, c.text) >= threshold for c in recent):
                continue
            accepted.append(CreditLine(timestamp=frame.timestamp, text=text))
    return accepted
