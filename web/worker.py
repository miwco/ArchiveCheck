"""Background job worker(s): claim queued jobs and run the archivecheck pipeline.

A small fixed number of daemon threads bound concurrency (and thus RAM/compute).
The heavy work (ina/OCR/ffmpeg) runs here, never in the request path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import traceback

from .settings import SETTINGS
from . import store, limits

_stop = threading.Event()
_threads: list[threading.Thread] = []


def _estimate_cost(summary: dict) -> tuple[int, int, float]:
    """Rough token/cost estimate from the credits summary (good enough for the
    backstop + logging; Haiku cost is ~1 cent regardless)."""
    cr = summary.get("credits") or {}
    in_tok = 1800 + int(cr.get("unique_lines") or 0) * 12   # prompt+titles + OCR text
    out_tok = int(cr.get("entries") or 0) * 14
    cost = limits.estimate_cost(in_tok, out_tok,
                                SETTINGS.price_in_per_mtok, SETTINGS.price_out_per_mtok)
    return in_tok, out_tok, cost


def _process(job) -> None:
    result_dir = os.path.join(SETTINGS.results_dir, job["cache_key"])
    os.makedirs(result_dir, exist_ok=True)
    # Isolated subprocess: a crash/timeout can't kill the web server, and gives a
    # hard compute cap. process_video writes summary.json into result_dir.
    timeout = SETTINGS.max_duration_sec * 3 + 300
    proc = subprocess.run(
        [sys.executable, "-m", "web.runjob", job["stream_url"], result_dir],
        capture_output=True, text=True, timeout=timeout, cwd=os.getcwd(),
    )
    sj_path = os.path.join(result_dir, "summary.json")
    if proc.returncode != 0 or not os.path.isfile(sj_path):
        raise RuntimeError(f"runjob rc={proc.returncode}: {(proc.stderr or '')[-800:]}")
    with open(sj_path, encoding="utf-8") as f:
        sd = json.load(f)
    in_tok, out_tok, cost = _estimate_cost(sd)
    sj = json.dumps(sd, ensure_ascii=False)
    store.finish_job(job["id"], "done", result_dir=result_dir, summary_json=sj,
                     input_tokens=in_tok, output_tokens=out_tok, cost=cost)
    store.cache_put(job["cache_key"], result_dir, sj, job["duration_sec"] or 0.0)


def _loop() -> None:
    while not _stop.is_set():
        job = store.claim_next_job()
        if job is None:
            _stop.wait(1.0)
            continue
        try:
            _process(job)
        except Exception as e:  # noqa: BLE001 — log and keep the worker alive
            store.finish_job(job["id"], "error",
                             error=f"{e!r}\n{traceback.format_exc()[-1500:]}")


def start_workers(n: int) -> None:
    for _ in range(max(1, n)):
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        _threads.append(t)


def stop_workers() -> None:
    _stop.set()
