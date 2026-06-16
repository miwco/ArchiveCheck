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
from .audio.loudness import analyze_loudness
from .audio.recognize import get_recognizer
from .audio.segment import merge_adjacent, segment_audio, Segment
from .config import CONFIG
from .credits.dedup import dedup_lines
from .credits.detect import detect_credits_window
from .credits.frames import credits_window, extract_credit_frames
from .credits.ocr import get_ocr_engine, ocr_frames
from .credits.structure import structure_credits
from .report.cuesheet import build_cuesheet, write_cuesheet
from .report.credits_report import write_credits
from .report.tech_report import write_tech_report
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
    label: str = ""                  # output-folder name / film id
    duration_tc: str = ""
    warnings: List[str] = field(default_factory=list)
    music: dict = field(default_factory=dict)
    credits: dict = field(default_factory=dict)
    loudness: dict = field(default_factory=dict)
    fileinfo: dict = field(default_factory=dict)


def process_video(
    video_path: str,
    out_dir: str,
    do_music: bool = True,
    do_credits: bool = True,
    do_loudness: bool = True,
    credits_window_sec: Optional[float] = None,
    keep_intermediate: bool = False,
) -> FilmSummary:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    work_dir = os.path.join(out_dir, "_work")
    Path(work_dir).mkdir(parents=True, exist_ok=True)

    info = probe(video_path)
    # Keep URLs as-is; only local paths get absolutised.
    src = video_path if "://" in video_path else os.path.abspath(video_path)
    summary = FilmSummary(video=src, duration_tc=fmt_timecode(info.duration_sec))

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
                # Window: explicit --credits-window wins; else auto-detect; else fixed.
                if credits_window_sec is not None:
                    start, end = credits_window(info.duration_sec, credits_window_sec)
                    win_method = "manual"
                elif CONFIG.auto_credits_window:
                    det = detect_credits_window(video_path, info.duration_sec, engine)
                    if det:
                        start, end, win_method = det[0], det[1], "auto-detected"
                    else:
                        start, end = credits_window(info.duration_sec)
                        win_method = "fallback (fixed window)"
                else:
                    start, end = credits_window(info.duration_sec)
                    win_method = "fixed window"
                frame_dir = os.path.join(work_dir, "credit_frames")
                # Upscale low-res proxies toward ~1080p so credit text OCRs well.
                upscale = 1
                if info.height:
                    upscale = max(1, round(CONFIG.credits_target_height / info.height))
                frames = extract_credit_frames(video_path, frame_dir, start, end,
                                               upscale=upscale)
                ocr = ocr_frames(frames, engine)
                lines = dedup_lines(ocr)
                entries, method = structure_credits(lines)
                outputs = write_credits(entries, out_dir)
                summary.credits = {
                    "ok": True,
                    "window_tc": f"{fmt_timecode(start)}-{fmt_timecode(end)}",
                    "window_method": win_method,
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

    # ---- loudness (EBU R128) + technical report --------------------------- #
    loudness_result = None
    if do_loudness and info.has_audio:
        try:
            loudness_result = analyze_loudness(video_path)
            if loudness_result.ok:
                summary.loudness = {
                    "ok": True,
                    "integrated_lufs": loudness_result.integrated_lufs,
                    "true_peak_dbtp": loudness_result.true_peak_dbtp,
                    "lra_lu": loudness_result.lra_lu,
                    "passed": loudness_result.passed,
                    "reasons": loudness_result.reasons,
                }
                if not loudness_result.passed:
                    summary.warnings.append(
                        "Loudness not EBU R128 compliant: "
                        + "; ".join(loudness_result.reasons)
                    )
            else:
                summary.loudness = {"ok": False, "error": loudness_result.error}
        except Exception as e:
            summary.loudness = {"ok": False, "error": repr(e)}

    # File info (reference only) + readable technical report (always written).
    summary.fileinfo = {
        "resolution": f"{info.width}x{info.height}" if info.width else None,
        "fps": info.fps,
        "video_codec": info.video_codec,
        "container": info.container,
        "audio_codec": info.audio_codec,
        "audio_channels": info.audio_channels,
        "audio_sample_rate": info.audio_sample_rate,
    }
    try:
        write_tech_report(out_dir, info, loudness_result)
    except Exception as e:
        summary.warnings.append(f"Could not write technical report: {e!r}")

    # ---- persist summary -------------------------------------------------- #
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(_summary_dict(summary), f, indent=2)

    if not keep_intermediate:
        shutil.rmtree(work_dir, ignore_errors=True)

    return summary


def _summary_dict(s: FilmSummary) -> dict:
    return {
        "video": s.video,
        "label": s.label,
        "duration_tc": s.duration_tc,
        "warnings": s.warnings,
        "music": s.music,
        "credits": s.credits,
        "loudness": s.loudness,
        "fileinfo": s.fileinfo,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
