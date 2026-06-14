"""Small shared helpers."""

from __future__ import annotations

import re


def fmt_timecode(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    ms = int(round((seconds - int(seconds)) * 1000))
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def fmt_hms(seconds: float) -> str:
    """Format seconds as HH:MM:SS (no milliseconds), matching the archive UI."""
    if seconds < 0:
        seconds = 0.0
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(name: str) -> str:
    """Filesystem-safe slug for output folder names.

    Guards against path traversal: collapses ``..`` and never returns a name made
    only of dots, so a crafted filename cannot redirect output outside its root.
    """
    slug = _SLUG_RE.sub("_", name)
    slug = slug.replace("..", "_").strip("._-")
    if not slug or set(slug) <= {"."}:
        return "film"
    return slug
