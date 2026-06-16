"""OCR behind a swappable interface (Tesseract default)."""

from __future__ import annotations

import functools
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


@functools.lru_cache(maxsize=1)
def _installed_langs() -> frozenset[str]:
    """Languages Tesseract actually has installed."""
    if not CONFIG.tesseract:
        return frozenset()
    try:
        out = subprocess.run([CONFIG.tesseract, "--list-langs"],
                             capture_output=True, text=True).stdout
    except Exception:
        return frozenset()
    return frozenset(ln.strip() for ln in out.splitlines()[1:] if ln.strip())


def _resolve_lang(requested: str) -> str:
    """Keep only requested languages that are installed; fall back to eng."""
    have = _installed_langs()
    wanted = [l for l in requested.split("+") if l in have]
    if wanted:
        return "+".join(wanted)
    return "eng" if "eng" in have else (next(iter(have), "eng"))


class TesseractEngine:
    """Uses the tesseract CLI directly to avoid a hard pytesseract dependency."""

    def available(self) -> bool:
        return CONFIG.tesseract is not None

    def image_to_lines(self, image_path: str) -> List[str]:
        if not CONFIG.tesseract:
            return []
        lang = _resolve_lang(CONFIG.ocr_lang)
        # TSV mode gives word bounding boxes, so we can detect the wide gap
        # between a two-column "Roll  Namn" layout and mark it with a tab —
        # plain text mode collapses that gap to a single space.
        cmd = [CONFIG.tesseract, image_path, "stdout", "-l", lang, "--psm", "6", "tsv"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 check=True, encoding="utf-8").stdout
        except Exception:
            return []
        return _tsv_to_lines(out)


def _good_text(line: str) -> bool:
    """Reject OCR noise: require enough letters and a decent alphabetic ratio."""
    compact = line.replace("\t", "").replace(" ", "")
    if len(compact) < 3:
        return False
    letters = sum(1 for c in compact if c.isalpha())
    if letters < 3:
        return False
    return letters / len(compact) >= 0.5


def _tsv_to_lines(tsv: str) -> List[str]:
    """Reconstruct text lines from Tesseract TSV.

    Inserts a tab at the wide gap of a two-column "Roll  Namn" layout, and drops
    low-confidence / non-text lines (footage OCR'd before the credits roll).
    """
    from collections import OrderedDict

    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for row in tsv.splitlines():
        f = row.split("\t")
        if len(f) < 12 or f[0] == "level":
            continue
        try:
            if int(f[0]) != 5:                       # level 5 == word
                continue
            left, width, height = int(f[6]), int(f[8]), int(f[9])
            conf = float(f[10])
        except ValueError:
            continue
        text = f[11].strip()
        if not text:
            continue
        groups.setdefault((f[2], f[3], f[4]), []).append((left, width, height, text, conf))

    lines: List[str] = []
    for words in groups.values():
        words.sort(key=lambda w: w[0])
        confs = [w[4] for w in words if w[4] >= 0]
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        if mean_conf < CONFIG.ocr_min_confidence:
            continue
        heights = sorted(w[2] for w in words)
        med_h = heights[len(heights) // 2] if heights else 0
        gap_thr = max(med_h * 1.5, 12)               # column gap >> word spacing
        out = [words[0][3]]
        for prev, cur in zip(words, words[1:]):
            gap = cur[0] - (prev[0] + prev[1])
            out.append(("\t" if gap > gap_thr else " ") + cur[3])
        line = "".join(out).strip()
        if line and _good_text(line):
            lines.append(line)
    return lines


def get_ocr_engine() -> OcrEngine:
    return TesseractEngine()


def ocr_frames(frames: List[Tuple[float, str]], engine: OcrEngine) -> List[OcrFrame]:
    results: List[OcrFrame] = []
    for ts, path in frames:
        results.append(OcrFrame(timestamp=ts, lines=engine.image_to_lines(path)))
    return results
