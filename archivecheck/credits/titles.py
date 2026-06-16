"""Controlled vocabulary of legit credit titles + role-to-title mapping.

Arcada's archive must store approved titles only, not whatever students wrote in
the credits. Titles live in a plain text file (one per line, typically
``Svenska / English``); each extracted role is mapped to the closest legit title.
"""

from __future__ import annotations

import difflib
import functools
import os
from typing import Optional, Tuple

from ..config import CONFIG


@functools.lru_cache(maxsize=1)
def load_titles() -> Tuple[str, ...]:
    """Load the canonical title list (falls back to CONFIG.archive_roles)."""
    path = CONFIG.titles_file
    if path and os.path.isfile(path):
        out = []
        for raw in open(path, encoding="utf-8"):
            t = raw.strip()
            if t and not t.startswith("#"):
                out.append(t)
        if out:
            return tuple(out)
    return tuple(CONFIG.archive_roles)


def _variants(title: str) -> list[str]:
    """Lower-cased keys a title can be matched by: full, and each ' / ' side."""
    keys = [title.strip().lower()]
    for part in title.split("/"):
        p = part.strip().lower()
        if p:
            keys.append(p)
    return keys


@functools.lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    """Map every matchable key (full title + each language side) -> canonical title."""
    lut: dict[str, str] = {}
    for title in load_titles():
        for key in _variants(title):
            lut.setdefault(key, title)
    return lut


def swedish_title(title: str) -> str:
    """Return the Swedish side of a 'Svenska / English' title (left of ' / ')."""
    return title.split(" / ", 1)[0].strip()


def map_role(role: str) -> Optional[str]:
    """Return the canonical title for a raw role, or None if no confident match.

    Tries exact match (full title or either language side), then fuzzy match
    above CONFIG.title_match_cutoff (high, so 'A-foto' never snaps to 'B-foto').
    """
    if not role or not role.strip():
        return None
    lut = _lookup()
    key = role.strip().lower()
    if key in lut:
        return lut[key]
    match = difflib.get_close_matches(key, list(lut), n=1, cutoff=CONFIG.title_match_cutoff)
    return lut[match[0]] if match else None
