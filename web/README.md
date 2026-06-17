# ArchiveCheck web app

A school-hosted web GUI over the `archivecheck` pipeline. Students/staff paste an
Arcada player link and get the music cue sheet, end credits, and EBU R128 loudness —
no install, no personal API keys. The **server** holds the keys, forces the cheap
model, enforces all cost/abuse limits, logs usage, and caches results per film.

## Run locally (dev)
```bash
pip install -r requirements.txt -r web/requirements.txt   # core + web deps
# set keys + access code in .env (see .env.example), then:
uvicorn web.app:app --reload --port 8000
```
Open http://localhost:8000 , sign in with `VC_ACCESS_CODE`, paste a player link.

## Deploy on-prem (Docker)
```bash
cp .env.example .env        # fill ANTHROPIC_API_KEY, ACOUSTID_API_KEY,
                            # VC_ACCESS_CODE, VC_SESSION_SECRET
docker compose up -d --build
```
The image bundles ffmpeg, Tesseract (+Swedish), Chromaprint, and TensorFlow.
Put a reverse proxy (nginx/Caddy) with **HTTPS** in front of port 8000, and keep the
app on the intranet (shared-code auth is for a pilot, not the open internet).

**Host needs:** ~2 vCPU / **4 GB RAM** (TensorFlow uses ~2 GB per concurrent job),
~5 GB disk, and **outbound internet** to `api.anthropic.com`, AcoustID, and the
`streamlock.net` HLS server. Confirm the firewall allows that outbound access.

## How limits work (all server-side, in `settings.py`)
- **Model locked** to `claude-haiku-4-5` (~1¢/film); clients can't change it.
- **Pre-flight**: the video's duration is probed *before* processing; films over
  `VC_MAX_DURATION_SEC` (20 min) are refused — no compute, no spend.
- **Cache by film ID**: a film is processed once; later requests return instantly.
- **Quotas**: `VC_MAX_PER_DAY` analyses/session/day, 1 concurrent job/session,
  `VC_MIN_INTERVAL_SEC` between submissions, per-session cost cap.
- **Concurrency** `VC_MAX_CONCURRENT` bounds RAM/compute.
- Every job is logged to SQLite (`web_data/archivecheck.sqlite3`): session, source,
  duration, tokens, estimated cost, status, cache hits.

## Data / privacy
Results and logs contain personal names. `web_data/` is gitignored; keep it on the
on-prem host, access-controlled. Set a retention policy (`VC_RETENTION_DAYS`) and a
cleanup job to delete old results (cleanup job: TODO / postponed).

## Not yet (postponed)
File upload; OAuth/Entra SSO (replaces the shared code — recommended next); admin
dashboard; automatic retention cleanup; multi-worker/Redis scaling.
