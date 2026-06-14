"""Music recognition behind a swappable interface.

Default implementation: Chromaprint (``fpcalc``) -> AcoustID lookup, with a
best-effort MusicBrainz enrichment pass for ISRC/label. A paid service
(ACRCloud/AudD) can be added later by implementing the ``Recognizer`` protocol
and returning it from :func:`get_recognizer`.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from ..config import CONFIG

ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
MB_RECORDING_URL = "https://musicbrainz.org/ws/2/recording/"
USER_AGENT = "ArchiveCheck/0.1 (archival music identification)"


@dataclass
class Track:
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    isrc: Optional[str] = None
    label: Optional[str] = None
    score: float = 0.0
    recording_id: Optional[str] = None
    source: str = "acoustid"


@dataclass
class RecognitionResult:
    track: Optional[Track] = None
    reason: str = ""  # why nothing was returned (no key, no match, error...)
    candidates: List[Track] = field(default_factory=list)


class Recognizer(Protocol):
    def recognize(self, snippet_wav: str) -> RecognitionResult: ...


def _fingerprint(snippet_wav: str) -> Optional[tuple[int, str]]:
    """Return (duration, fingerprint) via fpcalc, or None if unavailable."""
    if not CONFIG.fpcalc:
        return None
    cmd = [CONFIG.fpcalc, "-json", "-length", str(int(CONFIG.fingerprint_window_sec)), snippet_wav]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        return int(round(float(data["duration"]))), data["fingerprint"]
    except Exception:
        return None


def _http_get_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


class AcoustIDRecognizer:
    """Chromaprint + AcoustID, with optional MusicBrainz enrichment."""

    def __init__(self, enrich: bool = True) -> None:
        self.enrich = enrich

    def recognize(self, snippet_wav: str) -> RecognitionResult:
        if not CONFIG.fpcalc:
            return RecognitionResult(reason="fpcalc (Chromaprint) not installed")
        if not CONFIG.acoustid_api_key:
            return RecognitionResult(reason="ACOUSTID_API_KEY not set")

        fp = _fingerprint(snippet_wav)
        if fp is None:
            return RecognitionResult(reason="fingerprinting failed")
        duration, fingerprint = fp

        params = urllib.parse.urlencode({
            "client": CONFIG.acoustid_api_key,
            "duration": duration,
            "fingerprint": fingerprint,
            "meta": "recordings+releasegroups+compress",
        })
        data = _http_get_json(f"{ACOUSTID_URL}?{params}")
        if not data or data.get("status") != "ok":
            return RecognitionResult(reason="acoustid lookup failed")

        results = data.get("results", [])
        if not results:
            return RecognitionResult(reason="no match")

        candidates: List[Track] = []
        for res in results:
            score = float(res.get("score", 0.0))
            for rec in res.get("recordings", []) or []:
                artists = rec.get("artists") or []
                artist = ", ".join(a.get("name", "") for a in artists) or None
                rgs = rec.get("releasegroups") or []
                album = rgs[0].get("title") if rgs else None
                candidates.append(Track(
                    title=rec.get("title"),
                    artist=artist,
                    album=album,
                    score=score,
                    recording_id=rec.get("id"),
                ))
            if not res.get("recordings"):
                candidates.append(Track(score=score))

        candidates.sort(key=lambda t: t.score, reverse=True)
        best = candidates[0]
        if best.score < CONFIG.min_recognition_score or not best.title:
            return RecognitionResult(
                reason=f"low confidence (best score {best.score:.2f})",
                candidates=candidates,
            )

        if self.enrich and best.recording_id:
            self._enrich(best)
        return RecognitionResult(track=best, candidates=candidates)

    def _enrich(self, track: Track) -> None:
        """Best-effort ISRC/label lookup from MusicBrainz."""
        rec_id = urllib.parse.quote(track.recording_id, safe="")
        url = f"{MB_RECORDING_URL}{rec_id}?fmt=json&inc=isrcs+releases+labels"
        data = _http_get_json(url)
        if not data:
            return
        isrcs = data.get("isrcs") or []
        if isrcs:
            track.isrc = isrcs[0]
        for rel in data.get("releases", []) or []:
            for li in rel.get("label-info", []) or []:
                lbl = (li.get("label") or {}).get("name")
                if lbl:
                    track.label = lbl
                    return


def get_recognizer() -> Recognizer:
    """Factory — swap this to return a paid recognizer later."""
    return AcoustIDRecognizer()
