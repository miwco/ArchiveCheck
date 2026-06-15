"""Human-readable technical report: EBU R128 loudness + reference-only file info."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..audio.extract import MediaInfo
from ..audio.loudness import LoudnessResult
from ..config import CONFIG
from ..util import fmt_hms


def _flag(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _loudness_section(r: Optional[LoudnessResult]) -> list[str]:
    lines = ["Loudness (EBU R128)", "-------------------"]
    if r is None:
        lines.append("  (not analysed)")
        return lines
    if not r.ok:
        lines.append(f"  Measurement failed: {r.error}")
        return lines

    tol = CONFIG.loudness_tolerance_lu
    lines += [
        f"  Overall: {_flag(r.passed)}",
        f"  Integrated loudness : {r.integrated_lufs:6.1f} LUFS   "
        f"(target {CONFIG.loudness_target_lufs:.0f} +/- {tol:.0f})   [{_flag(r.integrated_pass)}]",
        f"  True peak           : {r.true_peak_dbtp:6.1f} dBTP   "
        f"(max {CONFIG.true_peak_max_dbtp:.0f})        [{_flag(r.true_peak_pass)}]",
        f"  Loudness range (LRA): {r.lra_lu:6.1f} LU     "
        f"(max {CONFIG.lra_max_lu:.0f})        [{_flag(r.lra_pass)}]",
    ]
    for reason in r.reasons:
        lines.append(f"  ! {reason}")
    return lines


def _fileinfo_section(info: MediaInfo) -> list[str]:
    res = f"{info.width}x{info.height}" if info.width else "unknown"
    fps = f"{info.fps:g} fps" if info.fps else "unknown"
    ch = f"{info.audio_channels} ch" if info.audio_channels else "no audio"
    sr = f"{info.audio_sample_rate} Hz" if info.audio_sample_rate else ""
    return [
        "",
        "File info (reference only -- proxy file; codec/container differ from master)",
        "---------------------------------------------------------------------------",
        f"  Duration   : {fmt_hms(info.duration_sec)}",
        f"  Resolution : {res}   {fps}",
        f"  Video codec: {info.video_codec or 'n/a'}",
        f"  Container  : {info.container or 'n/a'}",
        f"  Audio      : {info.audio_codec or 'n/a'}   {ch}   {sr}".rstrip(),
    ]


def write_tech_report(
    out_dir: str,
    info: MediaInfo,
    loudness: Optional[LoudnessResult],
    basename: str = "technical_report",
) -> str:
    """Write technical_report.txt and return its path."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    lines = _loudness_section(loudness) + _fileinfo_section(info)
    path = os.path.join(out_dir, f"{basename}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path
