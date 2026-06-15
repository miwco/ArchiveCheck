"""EBU R128 loudness analysis via a single ffmpeg ``loudnorm`` pass.

We run ffmpeg's ``loudnorm`` filter in analysis mode (``print_format=json``),
which measures integrated loudness, true peak and loudness range in one pass and
prints them as a JSON block on stderr. No extra dependencies.

The spec checked (configurable in :mod:`archivecheck.config`):
- integrated loudness  = -23 LUFS  (pass within ± tolerance)
- loudness range (LRA) <= 15 LU    (the "max variation")
- true peak           <= -1 dBTP
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from ..config import CONFIG


@dataclass
class LoudnessResult:
    ok: bool = False                         # measurement succeeded
    error: str = ""
    integrated_lufs: Optional[float] = None
    true_peak_dbtp: Optional[float] = None
    lra_lu: Optional[float] = None
    integrated_pass: bool = False
    true_peak_pass: bool = False
    lra_pass: bool = False
    passed: bool = False                      # overall compliance
    reasons: List[str] = field(default_factory=list)


# The JSON block is the last {...} ffmpeg prints on stderr.
_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _parse_loudnorm_json(stderr_text: str) -> dict:
    """Extract the trailing loudnorm JSON object from ffmpeg stderr."""
    matches = _JSON_RE.findall(stderr_text)
    if not matches:
        raise ValueError("no loudnorm JSON found in ffmpeg output")
    return json.loads(matches[-1])


def _evaluate(integrated: float, true_peak: float, lra: float) -> LoudnessResult:
    """Apply EBU R128 thresholds from config to measured values."""
    target = CONFIG.loudness_target_lufs
    tol = CONFIG.loudness_tolerance_lu
    res = LoudnessResult(
        ok=True,
        integrated_lufs=integrated,
        true_peak_dbtp=true_peak,
        lra_lu=lra,
    )
    res.integrated_pass = abs(integrated - target) <= tol
    res.true_peak_pass = true_peak <= CONFIG.true_peak_max_dbtp
    res.lra_pass = lra <= CONFIG.lra_max_lu

    if not res.integrated_pass:
        res.reasons.append(
            f"Integrated {integrated:.1f} LUFS outside {target:.0f}+/-{tol:.0f} LU"
        )
    if not res.true_peak_pass:
        res.reasons.append(
            f"True peak {true_peak:.1f} dBTP exceeds {CONFIG.true_peak_max_dbtp:.0f} dBTP"
        )
    if not res.lra_pass:
        res.reasons.append(
            f"Loudness range {lra:.1f} LU exceeds {CONFIG.lra_max_lu:.0f} LU"
        )
    res.passed = res.integrated_pass and res.true_peak_pass and res.lra_pass
    return res


def analyze_loudness(video_path: str) -> LoudnessResult:
    """Measure loudness and evaluate EBU R128 compliance."""
    CONFIG.require("ffmpeg")
    target = CONFIG.loudness_target_lufs
    cmd = [
        CONFIG.ffmpeg, "-hide_banner", "-nostats",
        "-i", video_path,
        "-af", f"loudnorm=I={target:g}:TP={CONFIG.true_peak_max_dbtp:g}:"
               f"LRA={CONFIG.lra_max_lu:g}:print_format=json",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = _parse_loudnorm_json(proc.stderr)
        return _evaluate(
            float(data["input_i"]),
            float(data["input_tp"]),
            float(data["input_lra"]),
        )
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        return LoudnessResult(ok=False, error=f"loudness analysis failed: {e}")
