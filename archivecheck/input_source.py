"""Resolve inputs into something ffmpeg can read.

Accepts, transparently:
- a local file or folder of videos (the originals),
- a direct media URL (``.m3u8`` / ``.mp4`` / ...),
- a player page URL (e.g. Arcada ``player.php?id=...``) — the page is fetched and
  its embedded video source extracted,
- a ``.txt`` links file with ``ID URL`` lines (one film per line).

ffmpeg/ffprobe read HLS and HTTP sources natively, so a resolved stream URL flows
through the rest of the pipeline exactly like a local path.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Tuple

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mxf", ".webm", ".wmv"}
_MEDIA_EXTS = (".m3u8", ".mp4", ".mpd", ".webm", ".m4v", ".mov")

# Matches a player page's embedded source, e.g. <source ... src="....m3u8">
_SRC_RE = re.compile(
    r"""src\s*=\s*["']([^"']+\.(?:m3u8|mpd|mp4|webm)[^"']*)["']""", re.IGNORECASE
)


def is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


def resolve_stream(url: str, timeout: float = 30.0) -> str:
    """Return a directly-playable media URL for a media or player-page URL."""
    base = url.split("?", 1)[0].lower()
    if base.endswith(_MEDIA_EXTS):
        return url  # already a direct media URL
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ArchiveCheck"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", "replace")
    m = _SRC_RE.search(html)
    if not m:
        raise ValueError(f"no embedded video source found at {url}")
    return urllib.parse.urljoin(url, m.group(1))


def parse_links_file(path: str) -> List[Tuple[str, str]]:
    """Parse a links file into (label, url) pairs.

    Each non-empty line is ``ID URL`` (label is the ID) or just ``URL``.
    """
    pairs: List[Tuple[str, str]] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and is_url(parts[-1]):
            pairs.append((parts[0], parts[-1]))
        elif is_url(parts[0]):
            pairs.append((parts[0], parts[0]))
    return pairs


def _label_from_url(url: str) -> str:
    """Best-effort label for an output folder from a URL."""
    q = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(q.query)
    if "id" in params:
        return params["id"][0][:16]
    stem = Path(q.path).stem
    return stem or (q.netloc or "stream")


def gather_inputs(arg: str) -> List[Tuple[str, str]]:
    """Return (label, source) pairs, where source is a path or playable URL.

    Network resolution of player pages is deferred to the caller per item so one
    bad link does not abort a batch; here we only resolve direct cases. Player
    page URLs are returned as-is and resolved at processing time.
    """
    if is_url(arg):
        return [(_label_from_url(arg), arg)]

    p = Path(arg)
    if p.is_file() and p.suffix.lower() == ".txt":
        return [(label, url) for label, url in parse_links_file(arg)]
    if p.is_file():
        return [(p.stem, str(p))]
    if p.is_dir():
        return sorted(
            (f.stem, str(f)) for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS
        )
    raise FileNotFoundError(arg)
