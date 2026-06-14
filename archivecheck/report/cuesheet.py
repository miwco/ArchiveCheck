"""Turn music segments into a timed, identified cue sheet."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from ..audio.extract import extract_audio_segment
from ..audio.recognize import Recognizer, Track
from ..audio.segment import Segment
from ..config import CONFIG
from ..util import fmt_hms


@dataclass
class Cue:
    start: float
    end: float
    status: str            # "recognized" | "unidentified music"
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    isrc: Optional[str] = None
    label: Optional[str] = None
    score: float = 0.0
    note: str = ""
    recording_id: Optional[str] = None
    needs_check: bool = False   # boundaries unreliable (e.g. music under dialogue)
    check_reason: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _probe_windows(seg: Segment, max_probes: int = 2):
    """Yield up to ``max_probes`` (start, end) snippets to sample for ID.

    The segmenter already bounds the piece, so we only need a couple of probes
    to learn *what* it is — not a full sweep. We probe near the start and, if
    needed, near the middle.
    """
    win = CONFIG.fingerprint_window_sec
    offsets = [seg.start + 1.0]
    if seg.duration > win * 1.5 and max_probes > 1:
        offsets.append(seg.start + seg.duration / 2.0 - win / 2.0)
    for off in offsets[:max_probes]:
        start = max(seg.start, off)
        end = min(seg.end, start + win)
        if end - start >= 3.0:
            yield start, end


def build_cuesheet(
    video_path: str,
    segments: List[Segment],
    recognizer: Recognizer,
    work_dir: str,
    speech_segments: Optional[List[Segment]] = None,
) -> List[Cue]:
    """One detected music region -> one cue (Musikstycke).

    Boundaries (start/stop/length) come from the segmenter; recognition only
    *annotates* what the track is. A confident match -> ``recognized`` (likely a
    commercial track to clear); no match -> ``unidentified music`` (likely
    student-made or free music — timed for manual entry).

    If ``speech_segments`` are supplied, any music cue that overlaps speech is
    flagged ``needs_check`` — that's music playing under dialogue, where the
    detector's boundaries are unreliable and a human should verify the times.

    For ``unknown`` segments (silence-fallback backend, where music and speech
    can't be told apart) an unidentified region is dropped, since it may be
    speech. Use the inaSpeechSegmenter backend to time unidentified music.
    """
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    raw: List[Cue] = []
    idx = 0
    for seg in segments:
        if seg.label not in ("music", "unknown"):
            continue
        if seg.duration < CONFIG.min_music_segment_sec:
            continue

        track: Track | None = None
        reason = ""
        for w_start, w_end in _probe_windows(seg):
            snippet = os.path.join(work_dir, f"snip_{idx:04d}.wav")
            idx += 1
            extract_audio_segment(video_path, w_start, w_end - w_start, snippet)
            result = recognizer.recognize(snippet)
            try:
                os.remove(snippet)
            except OSError:
                pass
            reason = result.reason or reason
            if result.track and result.track.title:
                track = result.track
                break

        if track is not None:
            cue = Cue(
                start=seg.start, end=seg.end, status="recognized",
                title=track.title, artist=track.artist, album=track.album,
                isrc=track.isrc, label=track.label, score=track.score,
                recording_id=track.recording_id,
            )
        elif seg.label == "music":
            cue = Cue(
                start=seg.start, end=seg.end, status="unidentified music",
                note=reason,
            )
        else:
            # unknown + no match -> skip (likely speech)
            continue

        overlap = _speech_overlap(cue, speech_segments)
        if overlap >= 0.5:
            cue.needs_check = True
            cue.check_reason = "Musik under dialog – kontrollera tiderna"
        raw.append(cue)

    return _merge(raw)


def _speech_overlap(cue: Cue, speech_segments: Optional[List[Segment]]) -> float:
    """Total seconds of speech overlapping the cue's time span."""
    if not speech_segments:
        return 0.0
    total = 0.0
    for sp in speech_segments:
        total += max(0.0, min(cue.end, sp.end) - max(cue.start, sp.start))
    return total


def _merge(raw: List[Cue], gap_tol: float = 2.0) -> List[Cue]:
    """Merge contiguous cues that share the same identity."""
    raw.sort(key=lambda c: c.start)
    merged: List[Cue] = []
    for c in raw:
        if merged:
            prev = merged[-1]
            same = (
                c.start - prev.end <= gap_tol
                and prev.status == c.status
                and prev.recording_id == c.recording_id
            )
            if same:
                prev.end = max(prev.end, c.end)
                prev.score = max(prev.score, c.score)
                if c.needs_check:
                    prev.needs_check = True
                    prev.check_reason = prev.check_reason or c.check_reason
                continue
        merged.append(c)
    return merged


# Columns mirror the Arcada archive's MUSIKINFORMATION block (Swedish field
# names) so a cue sheet maps 1:1 onto a "Musikstycke". Fields automation cannot
# fill (composer, lyricist, etc.) are emitted blank for a human, exactly as the
# archive shows them. Recognition evidence is appended after the archive fields.
_ARCHIVE_COLUMNS = [
    "Musikstycke",          # piece index (1, 2, 3, ...)
    "Namn",                 # title
    "Stycket börjar",       # start timecode
    "Stycket slutar",       # end timecode
    "Längd",                # duration
    "Kompositör",           # composer (human)
    "Instrumental",         # (human)
    "Textförfattare",       # lyricist (human)
    "Arrangör",             # arranger (human)
    "Artist",               # artist
    "Musiktyp",             # (human)
    "Har Arcada alla rättigheter till stycket?",  # (human)
    "Musiklicens",          # license (human)
]
_EVIDENCE_COLUMNS = [
    "Status",               # recognized / unidentified music
    "Kontrolleras",         # "Ja" when boundaries need a human check
    "Säkerhet",             # AcoustID confidence
    "ISRC",                 # identification evidence
    "Skivbolag",            # label (evidence)
    "Album",                # album (evidence)
    "Kommentar",            # note / reason
]
_COLUMNS = _ARCHIVE_COLUMNS + _EVIDENCE_COLUMNS


def _row(c: Cue, index: int) -> dict:
    return {
        "Musikstycke": index,
        "Namn": c.title or "",
        "Stycket börjar": fmt_hms(c.start),
        "Stycket slutar": fmt_hms(c.end),
        "Längd": fmt_hms(c.duration),
        "Kompositör": "",
        "Instrumental": "",
        "Textförfattare": "",
        "Arrangör": "",
        "Artist": c.artist or "",
        "Musiktyp": "",
        "Har Arcada alla rättigheter till stycket?": "",
        "Musiklicens": "",
        "Status": c.status,
        "Kontrolleras": "Ja" if c.needs_check else "",
        "Säkerhet": round(c.score, 2) if c.score else "",
        "ISRC": c.isrc or "",
        "Skivbolag": c.label or "",
        "Album": c.album or "",
        "Kommentar": "; ".join(x for x in (c.check_reason, c.note) if x),
    }


def write_cuesheet(cues: List[Cue], out_dir: str, basename: str = "music_cuesheet") -> List[str]:
    """Write CSV (always) and XLSX (if openpyxl available). Returns paths."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows = [_row(c, i) for i, c in enumerate(cues, start=1)]
    written: List[str] = []

    csv_path = os.path.join(out_dir, f"{basename}.csv")
    # utf-8-sig so Excel on Windows renders Swedish characters (å/ä/ö) correctly.
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    written.append(csv_path)

    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Musikinformation"
        ws.append(_COLUMNS)
        for r in rows:
            ws.append([r[c] for c in _COLUMNS])
        xlsx_path = os.path.join(out_dir, f"{basename}.xlsx")
        wb.save(xlsx_path)
        written.append(xlsx_path)
    except Exception:
        pass

    return written
