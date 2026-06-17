"""SQLite persistence: jobs, usage accounting, and the film-ID result cache.

One file, WAL mode, a fresh connection per call — safe for the request threadpool
plus a small number of worker threads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from .settings import SETTINGS


def _connect() -> sqlite3.Connection:
    Path(SETTINGS.data_dir).mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(SETTINGS.db_path, timeout=30.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def init_db() -> None:
    with _connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source TEXT NOT NULL,
                stream_url TEXT,
                cache_key TEXT,
                status TEXT NOT NULL,           -- queued|running|done|error
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                duration_sec REAL,
                result_dir TEXT,
                summary_json TEXT,
                error TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0,
                cache_hit INTEGER DEFAULT 0,
                counted INTEGER DEFAULT 1       -- counts toward quota/cost (cache hits = 0)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_jobs_session ON jobs(session_id, created_at)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                result_dir TEXT NOT NULL,
                summary_json TEXT,
                duration_sec REAL,
                created_at REAL NOT NULL
            )
        """)


# --- jobs ------------------------------------------------------------------ #
def create_job(session_id: str, source: str, stream_url: str, cache_key: str,
               duration_sec: float, status: str = "queued",
               counted: int = 1, cache_hit: int = 0,
               result_dir: Optional[str] = None,
               summary_json: Optional[str] = None) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with _connect() as con:
        con.execute(
            "INSERT INTO jobs (id, session_id, source, stream_url, cache_key, status, "
            "created_at, duration_sec, counted, cache_hit, result_dir, summary_json, "
            "finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, session_id, source, stream_url, cache_key, status, now,
             duration_sec, counted, cache_hit, result_dir, summary_json,
             now if status == "done" else None),
        )
    return job_id


def get_job(job_id: str) -> Optional[sqlite3.Row]:
    with _connect() as con:
        return con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def claim_next_job() -> Optional[sqlite3.Row]:
    """Atomically pick the oldest queued job and mark it running."""
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            con.execute("ROLLBACK")
            return None
        con.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                    (time.time(), row["id"]))
        con.commit()
        return row


def finish_job(job_id: str, status: str, *, result_dir: Optional[str] = None,
               summary_json: Optional[str] = None, error: Optional[str] = None,
               input_tokens: int = 0, output_tokens: int = 0, cost: float = 0.0) -> None:
    with _connect() as con:
        con.execute(
            "UPDATE jobs SET status=?, finished_at=?, result_dir=?, summary_json=?, "
            "error=?, input_tokens=?, output_tokens=?, cost=? WHERE id=?",
            (status, time.time(), result_dir, summary_json, error,
             input_tokens, output_tokens, cost, job_id),
        )


def running_count(session_id: str) -> int:
    with _connect() as con:
        return con.execute(
            "SELECT COUNT(*) FROM jobs WHERE session_id=? AND status IN ('queued','running')",
            (session_id,),
        ).fetchone()[0]


# --- usage accounting (per session, last 24h) ------------------------------ #
def _since_24h() -> float:
    return time.time() - 24 * 3600


def count_today(session_id: str) -> int:
    with _connect() as con:
        return con.execute(
            "SELECT COUNT(*) FROM jobs WHERE session_id=? AND counted=1 AND created_at>=?",
            (session_id, _since_24h()),
        ).fetchone()[0]


def cost_today(session_id: str) -> float:
    with _connect() as con:
        v = con.execute(
            "SELECT COALESCE(SUM(cost),0) FROM jobs WHERE session_id=? AND created_at>=?",
            (session_id, _since_24h()),
        ).fetchone()[0]
        return float(v or 0.0)


def seconds_since_last(session_id: str) -> Optional[float]:
    with _connect() as con:
        row = con.execute(
            "SELECT MAX(created_at) FROM jobs WHERE session_id=?", (session_id,)
        ).fetchone()
    if row and row[0]:
        return time.time() - float(row[0])
    return None


# --- film cache ------------------------------------------------------------ #
def cache_get(cache_key: str) -> Optional[sqlite3.Row]:
    with _connect() as con:
        return con.execute("SELECT * FROM cache WHERE cache_key=?", (cache_key,)).fetchone()


def cache_put(cache_key: str, result_dir: str, summary_json: str, duration_sec: float) -> None:
    with _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO cache (cache_key, result_dir, summary_json, "
            "duration_sec, created_at) VALUES (?,?,?,?,?)",
            (cache_key, result_dir, summary_json, duration_sec, time.time()),
        )
