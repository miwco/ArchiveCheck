"""FastAPI app: the school-facing GUI over the archivecheck pipeline.

The server is the single control point: it holds the keys (via archivecheck.config),
forces the cheap model, runs every cost/abuse check, logs usage, and caches results.
"""

from __future__ import annotations

import csv
import json
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import store, limits, worker
from .settings import SETTINGS
from archivecheck.config import CONFIG
from archivecheck.audio.extract import probe
from archivecheck.input_source import resolve_stream, is_url

_HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))

# Downloadable result files (allowlist — no arbitrary paths).
_DOWNLOADS = {
    "credits.csv", "credits.xlsx", "credits.txt",
    "music_cuesheet.csv", "music_cuesheet.xlsx", "music_cuesheet.txt",
    "technical_report.txt",
}

app = FastAPI(title="ArchiveCheck")
app.add_middleware(SessionMiddleware, secret_key=SETTINGS.session_secret,
                   https_only=False, same_site="lax")
if (_HERE / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    store.init_db()
    CONFIG.anthropic_model = SETTINGS.model       # lock the model server-side
    Path(SETTINGS.results_dir).mkdir(parents=True, exist_ok=True)
    worker.start_workers(SETTINGS.max_concurrent_jobs)


@app.on_event("shutdown")
def _shutdown() -> None:
    worker.stop_workers()


# --- helpers --------------------------------------------------------------- #
def _sid(request: Request) -> Optional[str]:
    return request.session.get("sid") if request.session.get("authed") else None


def _quota(sid: str) -> dict:
    used = store.count_today(sid)
    return {"used": used, "max": SETTINGS.max_per_day,
            "remaining": max(0, SETTINGS.max_per_day - used)}


def _read_rows(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# --- auth ------------------------------------------------------------------ #
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    sid = _sid(request)
    if not sid:
        return templates.TemplateResponse(request, "login.html", {})
    return templates.TemplateResponse(
        request, "submit.html",
        {"quota": _quota(sid), "max_minutes": int(SETTINGS.max_duration_sec // 60)},
    )


@app.post("/login")
def login(request: Request, access_code: str = Form("")):
    if not SETTINGS.access_code or access_code != SETTINGS.access_code:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong access code."}, status_code=401,
        )
    request.session["authed"] = True
    request.session["sid"] = uuid.uuid4().hex
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# --- submit ---------------------------------------------------------------- #
@app.post("/submit")
def submit(request: Request, source: str = Form("")):
    sid = _sid(request)
    if not sid:
        return RedirectResponse("/", status_code=303)

    def refuse(msg: str, code: int = 200):
        return templates.TemplateResponse(
            request, "submit.html",
            {"quota": _quota(sid), "error": msg, "source": source,
             "max_minutes": int(SETTINGS.max_duration_sec // 60)},
            status_code=code,
        )

    source = (source or "").strip()
    if not source or not is_url(source):
        return refuse("Please paste an Arcada player link (https://...).")

    # anti-spam + quotas (cheap checks first)
    d = limits.check_interval(store.seconds_since_last(sid), SETTINGS.min_submit_interval_sec)
    if not d.ok:
        return refuse(d.reason)
    if store.running_count(sid) >= 1:
        return refuse("You already have an analysis running. Please wait for it to finish.")
    d = limits.check_quota(store.count_today(sid), SETTINGS.max_per_day)
    if not d.ok:
        return refuse(d.reason)
    d = limits.check_session_cost(store.cost_today(sid), SETTINGS.max_cost_per_video,
                                  SETTINGS.max_cost_per_session)
    if not d.ok:
        return refuse(d.reason)

    # resolve the player link -> stream URL (network GET; cheap)
    try:
        stream = resolve_stream(source)
    except Exception:
        return refuse("Could not read a video from that link. Check the URL and try again.")
    key = limits.cache_key(stream)

    # cache hit -> reuse, no compute, no spend, doesn't count toward quota
    cached = store.cache_get(key)
    if cached:
        job_id = store.create_job(sid, source, stream, key, cached["duration_sec"] or 0.0,
                                  status="done", counted=0, cache_hit=1,
                                  result_dir=cached["result_dir"],
                                  summary_json=cached["summary_json"])
        return RedirectResponse(f"/job/{job_id}", status_code=303)

    # pre-flight duration gate (no processing/spend if too long)
    try:
        info = probe(stream)
    except Exception:
        return refuse("Could not read the video's metadata from that link.")
    d = limits.preflight(info.duration_sec, SETTINGS.max_duration_sec)
    if not d.ok:
        return refuse(d.reason)

    job_id = store.create_job(sid, source, stream, key, info.duration_sec)
    return RedirectResponse(f"/job/{job_id}", status_code=303)


# --- job status / results -------------------------------------------------- #
@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    sid = _sid(request)
    if not sid:
        return RedirectResponse("/", status_code=303)
    job = store.get_job(job_id)
    if not job or job["session_id"] != sid:
        return templates.TemplateResponse(
            request, "job.html", {"not_found": True}, status_code=404)

    ctx = {"job": job, "status": job["status"]}
    if job["status"] == "done":
        rd = job["result_dir"] or ""
        summary = json.loads(job["summary_json"]) if job["summary_json"] else {}
        ctx.update({
            "summary": summary,
            "credits": _read_rows(os.path.join(rd, "credits.csv")),
            "music": _read_rows(os.path.join(rd, "music_cuesheet.csv")),
            "downloads": sorted(f for f in _DOWNLOADS if os.path.isfile(os.path.join(rd, f))),
            "cache_hit": bool(job["cache_hit"]),
        })
    return templates.TemplateResponse(request, "job.html", ctx)


@app.get("/job/{job_id}/download/{name}")
def download(request: Request, job_id: str, name: str):
    sid = _sid(request)
    job = store.get_job(job_id)
    if not sid or not job or job["session_id"] != sid or name not in _DOWNLOADS:
        return RedirectResponse("/", status_code=303)
    path = os.path.join(job["result_dir"] or "", name)
    if not os.path.isfile(path):
        return RedirectResponse(f"/job/{job_id}", status_code=303)
    return FileResponse(path, filename=name)
