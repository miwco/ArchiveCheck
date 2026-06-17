"""Server-side configuration for the web app (all from environment).

Everything cost/abuse-related is fixed here, server-side — clients can never change
the model, limits, or keys. The Anthropic/AcoustID keys themselves are read by
``archivecheck.config`` from the same environment; they are never exposed to the
browser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Importing the core config loads the .env file into os.environ, so the settings
# below (and the API keys read by archivecheck.config) see it.
import archivecheck.config  # noqa: F401,E402


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class WebSettings:
    # --- access (shared-code pilot; OAuth later) ---------------------------- #
    access_code: str = field(default_factory=lambda: os.environ.get("VC_ACCESS_CODE", ""))
    session_secret: str = field(
        default_factory=lambda: os.environ.get("VC_SESSION_SECRET", "dev-insecure-secret")
    )

    # --- model lock (clients can never change this) ------------------------- #
    model: str = field(default_factory=lambda: os.environ.get("VC_MODEL", "claude-haiku-4-5"))
    max_output_tokens: int = field(default_factory=lambda: _i("VC_MAX_OUTPUT_TOKENS", 4096))
    # Haiku pricing ($/1M tokens) for cost estimation/logging.
    price_in_per_mtok: float = field(default_factory=lambda: _f("VC_PRICE_IN", 1.0))
    price_out_per_mtok: float = field(default_factory=lambda: _f("VC_PRICE_OUT", 5.0))

    # --- hard limits -------------------------------------------------------- #
    max_duration_sec: float = field(default_factory=lambda: _f("VC_MAX_DURATION_SEC", 1200.0))  # 20 min
    max_per_day: int = field(default_factory=lambda: _i("VC_MAX_PER_DAY", 20))
    min_submit_interval_sec: float = field(default_factory=lambda: _f("VC_MIN_INTERVAL_SEC", 10.0))
    max_cost_per_video: float = field(default_factory=lambda: _f("VC_MAX_COST_PER_VIDEO", 0.05))
    max_cost_per_session: float = field(default_factory=lambda: _f("VC_MAX_COST_PER_SESSION", 1.0))
    max_concurrent_jobs: int = field(default_factory=lambda: _i("VC_MAX_CONCURRENT", 1))

    # --- storage ------------------------------------------------------------ #
    data_dir: str = field(default_factory=lambda: os.environ.get("VC_DATA_DIR", "web_data"))
    retention_days: int = field(default_factory=lambda: _i("VC_RETENTION_DAYS", 30))

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / "archivecheck.sqlite3")

    @property
    def results_dir(self) -> str:
        return str(Path(self.data_dir) / "results")


SETTINGS = WebSettings()
