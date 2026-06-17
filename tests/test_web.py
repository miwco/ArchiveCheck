"""Unit tests for the web app's pure cost/abuse-control logic (no server needed)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.limits import (  # noqa: E402
    preflight, check_quota, check_interval, check_session_cost,
    estimate_cost, cache_key,
)

passed = 0


def check(name, cond):
    global passed
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    assert cond, name
    passed += 1


def test_preflight():
    check("ok within limit", preflight(300, 1200).ok)
    check("refuse too long", not preflight(1500, 1200).ok)
    check("refuse unknown duration", not preflight(0, 1200).ok)
    check("refusal explains", "limit" in preflight(1500, 1200).reason.lower())


def test_quota_interval_cost():
    check("quota left", check_quota(5, 20).ok)
    check("quota exhausted", not check_quota(20, 20).ok)
    check("interval too fast", not check_interval(5, 10).ok)
    check("interval ok", check_interval(15, 10).ok)
    check("interval first submit", check_interval(None, 10).ok)
    check("session cost ok", check_session_cost(0.10, 0.05, 1.0).ok)
    check("session cost capped", not check_session_cost(0.99, 0.05, 1.0).ok)


def test_estimate_cost():
    check("input price", abs(estimate_cost(1_000_000, 0, 1.0, 5.0) - 1.0) < 1e-9)
    check("output price", abs(estimate_cost(0, 1_000_000, 1.0, 5.0) - 5.0) < 1e-9)


def test_cache_key():
    url = "https://h.net/filarkiv/_definst_/mp4:2026031702_1163_web.mp4/playlist.m3u8"
    check("film key from mp4 name", cache_key(url) == "2026031702_1163_web")
    check("same film, different token -> same key",
          cache_key(url) == cache_key(url.replace("h.net", "other.net")))
    k = cache_key("https://x/player.php?id=abc")
    check("non-mp4 url -> hashed key", k.startswith("h_") and len(k) > 5)


if __name__ == "__main__":
    test_preflight()
    test_quota_interval_cost()
    test_estimate_cost()
    test_cache_key()
    print(f"\n{passed} checks passed.")
