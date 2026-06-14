"""OCR behind a swappable interface (Tesseract default)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Protocol, Tuple

from ..config import CONFIG


@dataclass
class OcrFrame:
    timestamp: float
    lines: List[str]


class OcrEngine(Protocol):
    def available(self) -> bool: ...
    def image_to_lines(self, image_path: str) -> List[str]: ...


class TesseractEngine:
    """Uses the tesseract CLI directly to avoid a hard pytesseract dependency."""

    def available(self) -> bool:
        return CONFIG.tesseract is not None

    def image_to_lines(self, image_path: str) -> List[str]:
        if not CONFIG.tesseract:
            return []
        cmd = [CONFIG.tesseract, image_path, "stdout", "--psm", "6"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        except Exception:
            return []
        return [ln.strip() for ln in out.splitlines() if ln.strip()]


def get_ocr_engine() -> OcrEngine:
    return TesseractEngine()


def ocr_frames(frames: List[Tuple[float, str]], engine: OcrEngine) -> List[OcrFrame]:
    results: List[OcrFrame] = []
    for ts, path in frames:
        results.append(OcrFrame(timestamp=ts, lines=engine.image_to_lines(path)))
    return results
