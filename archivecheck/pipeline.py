"""Single-file orchestration: proxy in -> cue sheet + credits out."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .audio.extract import extract_audio, probe
from .audio.recognize import get_recognizer
from .audio.segment import merge_adjacent, segment_audio, Segment
from .config import CONFIG
from .credits.dedup import dedup_lines
from .credits.frames import credits_window, extract_credit_frames
from .credits.ocr import get_ocr_engine, ocr_frames
from .credits.structure import structure_credits
from .report.cuesheet import build_cuesheet, write_cuesheet
from .report.credits_report import write_credits
from .util import fmt_timecode


@dataclass
class StageResult:
    ok: bool = False
    note: str = ""
    outputs: List[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class FilmSummary:
    video: str
    duration_tc: str = ""
    warnings: List[str] = field(default_factory=list)
    music: dict = field(default_factory=dict)
    credits: dict = field(default_factory=dict)


def process_video(
    video_path: str,
    out_dir: str,
    do_music: bool = True,
    do_credits: bool = True,
    credits_window_sec: Optional[float] = None,
    keep_intermediate: bool = False,
) -> FilmSummary:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    work_dir = os.path.join(out_dir, "_work")
    Path(work_dir).mkdir(parents=True, exist_ok=True)

    info = probe(video_path)
    summary = FilmSummary(video=os.path.abspath(video_path),
                          duration_tc=fmt_timecode(info.duration_sec))

    if info.height and info.height < CONFIG.min_resolution_warn:
        summary.warnings.append(
            f"Low resolution ({info.width}x{info.height}); credit OCR may suffer."
        )
    if not info.has_audio:
        summary.warnings.append("No audio stream found; music analysis skipped.")
        do_music = False

    # ---- music engine ----------------------------------------------------- #
    if do_music:
        try:
            wav = os.path.join(work_dir, "audio.wav")
            extract_audio(video_path, wav)
            segments, backend = segment_audio(wav, info.duration_sec)
            # For the music-aware backend, merge fragmented music into clean runs.
            music_segments = merge_adjacent(segments, "music")
            ina = backend == "inaSpeechSegmenter"
            analysis_segments: List[Segment] = music_segments if ina else segments
            speech_segments = [s for s in segments if s.label == "speech"] if ina else None
            recognizer = get_recognizer()
            cues = build_cuesheet(video_path, analysis_segments, recognizer, work_dir,
                                  speech_segments=speech_segments)
            outputs = write_cuesheet(cues, out_dir)

            recognized = sum(1 for c in cues if c.status == "recognized")
            to_check = sum(1 for c in cues if c.needs_check)
            music_time = sum(s.duration for s in music_segments) if ina else None
            summary.music = {
                "ok": True,
                "backend": backend,
                "cues": len(cues),
                "recognized": recognized,
                "unidentified": len(cues) - recognized,
                "needs_check": to_check,
                "music_time_tc": fmt_timecode(music_time) if music_time is not None else None,
                "outputs": outputs,
            }
            if to_check:
                summary.warnings.append(
                    f"{to_check} music cue(s) overlap dialogue; verify their timings "
                    "(marked 'Kontrolleras' in the cue sheet)."
                )
            if not ina:
                summary.warnings.append(
                    "Music detector (inaSpeechSegmenter) not installed; only "
                    "recognised tracks are timed and background music may be missed."
                )
            if not CONFIG.fpcalc:
                summary.warnings.append("fpcalc not installed; no songs can be identified.")
            elif not CONFIG.acoustid_api_key:
                summary.warnings.append("ACOUSTID_API_KEY not set; no songs can be identified.")
        except Exception as e:  # keep credits engine alive on music failure
            summary.music = {"ok": False, "error": repr(e)}

    # ---- credits engine --------------------------------------------------- #
    if do_credits:
        try:
            engine = get_ocr_engine()
            if not engine.available():
                summary.credits = {"ok": False, "error": "tesseract not installed"}
                summary.warnings.append("tesseract not installed; credits OCR skipped.")
            else:
                start, end = credits_window(info.duration_sec, credits_window_sec)
                frame_dir = os.path.join(work_dir, "credit_frames")
                frames = extract_credit_frames(video_path, frame_dir, start, end)
                ocr = ocr_frames(frames, engine)
                lines = dedup_lines(ocr)
                entries, method = structure_credits(lines)
                outputs = write_credits(entries, out_dir)
                summary.credits = {
                    "ok": True,
                    "window_tc": f"{fmt_timecode(start)}-{fmt_timecode(end)}",
                    "frames": len(frames),
                    "unique_lines": len(lines),
                    "entries": len(entries),
                    "structuring": method,
                    "outputs": outputs,
                }
                if method == "heuristic" and not CONFIG.anthropic_api_key:
                    summary.warnings.append(
                        "ANTHROPIC_API_KEY not set; used heuristic credit parsing."
                    )
        except Exception as e:
            summary.credits = {"ok": False, "error": repr(e)}

    # ---- persist summary -------------------------------------------------- #
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(_summary_dict(summary), f, indent=2)

    if not keep_intermediate:
        shutil.rmtree(work_dir, ignore_errors=True)

    return summary


def _summary_dict(s: FilmSummary) -> dict:
    return {
        "video": s.video,
        "duration_tc": s.duration_tc,
        "warnings": s.warnings,
        "music": s.music,
        "credits": s.credits,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
