"""Pure cost/abuse-control logic (no I/O), so it can be unit-tested directly."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Decision:
    ok: bool
    reason: str = ""


def estimate_cost(input_tokens: int, output_tokens: int,
                  price_in_per_mtok: float, price_out_per_mtok: float) -> float:
    """Estimated USD cost of one LLM call."""
    return (input_tokens / 1_000_000.0) * price_in_per_mtok + \
           (output_tokens / 1_000_000.0) * price_out_per_mtok


def preflight(duration_sec: float, max_duration_sec: float) -> Decision:
    """Refuse (before any processing/spend) when a video is too long."""
    if duration_sec <= 0:
        return Decision(False, "Could not read the video's duration.")
    if duration_sec > max_duration_sec:
        return Decision(
            False,
            f"Video is {_hms(duration_sec)} long; the limit is "
            f"{_hms(max_duration_sec)}. Please use a shorter film.",
        )
    return Decision(True)


def check_quota(used_today: int, max_per_day: int) -> Decision:
    if used_today >= max_per_day:
        return Decision(
            False,
            f"Daily limit reached ({max_per_day} analyses/day). Try again tomorrow.",
        )
    return Decision(True)


def check_interval(seconds_since_last: Optional[float], min_interval: float) -> Decision:
    if seconds_since_last is not None and seconds_since_last < min_interval:
        wait = int(min_interval - seconds_since_last) + 1
        return Decision(False, f"Too fast — please wait {wait}s before submitting again.")
    return Decision(True)


def check_session_cost(spent: float, next_cost: float, cap: float) -> Decision:
    if spent + next_cost > cap:
        return Decision(False, "Session cost limit reached. Start a new session later.")
    return Decision(True)


# A stream URL looks like: .../mp4:2026031702_1163_web.mp4/playlist.m3u8
_MP4_RE = re.compile(r"([^/:]+)\.mp4", re.IGNORECASE)


def cache_key(stream_or_source_url: str) -> str:
    """Stable per-film key. Uses the archive mp4 basename when present (so the same
    film via different player tokens shares one cache entry); else a URL hash."""
    m = _MP4_RE.search(stream_or_source_url)
    if m:
        return m.group(1)
    return "h_" + hashlib.sha1(stream_or_source_url.encode("utf-8")).hexdigest()[:16]


def _hms(seconds: float) -> str:
    s = int(round(max(0.0, seconds)))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
