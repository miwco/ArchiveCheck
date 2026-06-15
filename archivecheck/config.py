"""Central configuration and external-tool discovery.

Everything that depends on the host environment (binary locations, API keys,
tunable thresholds) lives here so the rest of the pipeline stays portable.

Values may be overridden via environment variables (optionally loaded from a
``.env`` file placed next to the project root) so no secrets live in code.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Minimal .env loader (no hard dependency on python-dotenv)
# --------------------------------------------------------------------------- #
def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a .env file in CWD or project root, if present.

    Existing environment variables always win, so an explicitly exported value
    is never clobbered by the file.
    """
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_dotenv()


def _find_tool(env_var: str, *names: str) -> Optional[str]:
    """Resolve an external binary from an env override or PATH.

    ``env_var`` may point at the binary directly or at a directory containing it.
    """
    override = os.environ.get(env_var)
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
        if p.is_dir():
            for name in names:
                cand = p / name
                if cand.is_file():
                    return str(cand)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


@dataclass
class Config:
    # --- external binaries (None means "not available on this host") -------- #
    ffmpeg: Optional[str] = field(default_factory=lambda: _find_tool("FFMPEG", "ffmpeg.exe", "ffmpeg"))
    ffprobe: Optional[str] = field(default_factory=lambda: _find_tool("FFPROBE", "ffprobe.exe", "ffprobe"))
    fpcalc: Optional[str] = field(default_factory=lambda: _find_tool("FPCALC", "fpcalc.exe", "fpcalc"))
    tesseract: Optional[str] = field(default_factory=lambda: _find_tool("TESSERACT", "tesseract.exe", "tesseract"))

    # --- API keys ----------------------------------------------------------- #
    acoustid_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("ACOUSTID_API_KEY"))
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))

    # --- audio / recognition tunables --------------------------------------- #
    audio_sample_rate: int = 16000          # mono downmix rate for analysis
    audio_channels: int = 1
    # Length of the snippet (seconds) fingerprinted per music segment.
    fingerprint_window_sec: float = 30.0
    # Segments shorter than this are ignored as music cues (likely stingers/SFX).
    min_music_segment_sec: float = 4.0
    # When no real segmenter is available, scan the whole track in fixed windows.
    fallback_window_sec: float = 30.0
    # Min AcoustID match score (0..1) to treat as a confident identification.
    min_recognition_score: float = 0.5

    # --- credits tunables --------------------------------------------------- #
    # How far from the end we assume credits live, when not auto-detecting.
    credits_window_sec: float = 180.0
    credits_fps: float = 1.0                # frames per second sampled in window
    # Fuzzy-match ratio (0..100) above which two OCR lines are "the same line".
    dedup_similarity: int = 88
    min_resolution_warn: int = 720          # warn if proxy height below this

    # --- loudness (EBU R128) ------------------------------------------------ #
    loudness_target_lufs: float = -23.0     # program loudness target
    loudness_tolerance_lu: float = 1.0      # pass if integrated within ± this
    lra_max_lu: float = 15.0                # max loudness range (variation)
    true_peak_max_dbtp: float = -1.0        # max true peak

    # Model used for credit structuring (Anthropic).
    anthropic_model: str = "claude-opus-4-8"

    # Controlled role vocabulary from the Arcada archive (SLUTTEXTER). When a
    # credit clearly matches one of these, the LLM normalises to this exact
    # spelling so output lines up with the archive; otherwise it keeps the
    # credit's own wording. Extend as the archive's vocabulary grows.
    archive_roles: tuple[str, ...] = (
        "A-foto", "B-foto", "Editerare", "Intervju", "Intervjuobjekt",
        "Ljud", "Manus&Regi", "Producent", "Regi", "Manus", "Klippning",
        "Foto", "Ljussättning", "Scenografi", "Mask", "Kostym", "Musik",
        "Skådespelare", "Roll", "Tack till",
    )

    # --- output ------------------------------------------------------------- #
    output_root: Optional[str] = field(default_factory=lambda: os.environ.get("VC_OUTPUT_ROOT"))

    def require(self, *tool_names: str) -> None:
        """Raise a clear error if any required binary is missing."""
        missing = [t for t in tool_names if getattr(self, t) is None]
        if missing:
            raise RuntimeError(
                "Required external tool(s) not found: "
                + ", ".join(missing)
                + ". Install them or set the matching env var "
                + "(" + ", ".join(t.upper() for t in missing) + ")."
            )


# Module-level singleton used throughout the pipeline.
CONFIG = Config()
