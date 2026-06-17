"""Run one analysis in an isolated subprocess (so a crash/timeout can't take down
the web server, and TensorFlow runs in its own process, not a server thread).

    python -m web.runjob <stream_url> <result_dir>

process_video writes summary.json + the output files into <result_dir>.
"""

from __future__ import annotations

import sys

from archivecheck.config import CONFIG
from archivecheck.pipeline import process_video
from .settings import SETTINGS


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python -m web.runjob <stream_url> <result_dir>", file=sys.stderr)
        return 2
    stream_url, result_dir = sys.argv[1], sys.argv[2]
    CONFIG.anthropic_model = SETTINGS.model        # lock the cheap model here too
    process_video(stream_url, result_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
