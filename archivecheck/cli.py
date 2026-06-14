"""Command-line entry point.

    py -m archivecheck <file-or-folder> [options]

Single file -> one output folder. Folder -> one output folder per video plus a
roll-up index.csv / index.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import List

from .config import CONFIG
from .pipeline import process_video, FilmSummary, _summary_dict
from .util import slugify

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mxf", ".webm", ".wmv"}


def _gather(path: str) -> List[str]:
    p = Path(path)
    if p.is_file():
        return [str(p)]
    if p.is_dir():
        return sorted(
            str(f) for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
        )
    raise FileNotFoundError(path)


def _print_summary(s: FilmSummary) -> None:
    print(f"  duration: {s.duration_tc}")
    if s.music:
        if s.music.get("ok"):
            check = s.music.get("needs_check", 0)
            check_str = f", {check} to check" if check else ""
            print(f"  music:   {s.music['recognized']} recognized / "
                  f"{s.music['unidentified']} unidentified{check_str}  "
                  f"({s.music['backend']})")
        else:
            print(f"  music:   FAILED - {s.music.get('error')}")
    if s.credits:
        if s.credits.get("ok"):
            print(f"  credits: {s.credits['entries']} entries "
                  f"({s.credits['structuring']}, {s.credits['frames']} frames)")
        else:
            print(f"  credits: FAILED - {s.credits.get('error')}")
    for w in s.warnings:
        print(f"  ! {w}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archivecheck",
                                     description="Music cue sheet + end-credits extractor.")
    parser.add_argument("input", nargs="?", help="video file or folder of videos")
    parser.add_argument("-o", "--output", help="output root (default: ./vc_output)")
    parser.add_argument("--no-music", action="store_true", help="skip music analysis")
    parser.add_argument("--no-credits", action="store_true", help="skip credits extraction")
    parser.add_argument("--credits-window", type=float,
                        help="seconds from the end to scan for credits")
    parser.add_argument("--keep-intermediate", action="store_true",
                        help="keep extracted audio/frames for debugging")
    parser.add_argument("--check", action="store_true",
                        help="print tool/key availability and exit")
    args = parser.parse_args(argv)

    if args.check:
        return _check()

    if not args.input:
        parser.error("the following arguments are required: input")

    try:
        videos = _gather(args.input)
    except FileNotFoundError:
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2
    if not videos:
        print("No video files found.", file=sys.stderr)
        return 2

    out_root = args.output or CONFIG.output_root or os.path.join(os.getcwd(), "vc_output")
    Path(out_root).mkdir(parents=True, exist_ok=True)

    summaries: List[FilmSummary] = []
    for video in videos:
        name = slugify(Path(video).stem)
        out_dir = os.path.join(out_root, name)
        print(f"\n== {Path(video).name} ==")
        summary = process_video(
            video, out_dir,
            do_music=not args.no_music,
            do_credits=not args.no_credits,
            credits_window_sec=args.credits_window,
            keep_intermediate=args.keep_intermediate,
        )
        _print_summary(summary)
        summaries.append(summary)

    if len(summaries) > 1:
        _write_index(out_root, summaries)
        print(f"\nIndex written to {out_root}")

    return 0


def _write_index(out_root: str, summaries: List[FilmSummary]) -> None:
    rows = []
    for s in summaries:
        rows.append({
            "video": os.path.basename(s.video),
            "duration": s.duration_tc,
            "music_recognized": s.music.get("recognized", "") if s.music else "",
            "music_unidentified": s.music.get("unidentified", "") if s.music else "",
            "music_to_check": s.music.get("needs_check", "") if s.music else "",
            "credit_entries": s.credits.get("entries", "") if s.credits else "",
            "warnings": "; ".join(s.warnings),
        })
    with open(os.path.join(out_root, "index.csv"), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(out_root, "index.json"), "w", encoding="utf-8") as f:
        json.dump([_summary_dict(s) for s in summaries], f, indent=2)


def _check() -> int:
    print("External tools:")
    for tool in ("ffmpeg", "ffprobe", "fpcalc", "tesseract"):
        val = getattr(CONFIG, tool)
        print(f"  {tool:10s}: {val or 'NOT FOUND'}")
    print("API keys:")
    print(f"  ACOUSTID_API_KEY : {'set' if CONFIG.acoustid_api_key else 'missing'}")
    print(f"  ANTHROPIC_API_KEY: {'set' if CONFIG.anthropic_api_key else 'missing'}")
    from .audio.segment import _have_ina
    has_ina = _have_ina()
    print(f"  {'segmenter':10s}: {'inaSpeechSegmenter' if has_ina else 'NOT INSTALLED (silence fallback)'}")
    print("\nCapabilities:")
    detector = "full (music vs speech)" if has_ina else "limited (recognised tracks only)"
    print(f"  music timing:        {detector if CONFIG.ffmpeg else 'no (needs ffmpeg)'}")
    can_id = bool(CONFIG.fpcalc and CONFIG.acoustid_api_key)
    print(f"  song identification: {'yes' if can_id else 'no (needs fpcalc + ACOUSTID_API_KEY)'}")
    print(f"  credits OCR:         {'yes' if CONFIG.tesseract else 'no (needs tesseract)'}")
    print(f"  credit structuring:  {'LLM' if CONFIG.anthropic_api_key else 'heuristic only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
