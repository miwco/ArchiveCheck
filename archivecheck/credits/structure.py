"""Turn raw de-duplicated credit lines into structured role/name rows.

Primary path: an LLM (Anthropic) call, which handles the wide variance in credit
layouts far better than regex. Fallback path: a heuristic parser used when no API
key is configured or the call fails.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

from .dedup import CreditLine
from .titles import load_titles, map_role
from ..config import CONFIG

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class CreditEntry:
    role: str
    name: str
    timestamp: Optional[float] = None
    method: str = "heuristic"
    original_role: str = ""          # role text as written in the credits
    needs_check: bool = False        # role could not be mapped to a legit title
    check_reason: str = ""


_SEP_RE = re.compile(r"\s*(?::|–|—| - |\t|\s{2,})\s*")


def _looks_like_role_header(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.8 and len(text) <= 40


def _known_role(text: str) -> Optional[str]:
    """Return the canonical archive role if ``text`` matches one (case-insensitive)."""
    t = text.strip().lower()
    for role in CONFIG.archive_roles:
        if t == role.lower():
            return role
    return None


def heuristic_structure(lines: List[CreditLine]) -> List[CreditEntry]:
    entries: List[CreditEntry] = []
    current_role: Optional[str] = None
    for cl in lines:
        text = cl.text.strip()
        parts = _SEP_RE.split(text, maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            role, name = parts[0].strip(), parts[1].strip()
            entries.append(CreditEntry(role=role, name=name, timestamp=cl.timestamp))
            current_role = role
        elif _known_role(text):
            current_role = _known_role(text)
        elif _looks_like_role_header(text):
            current_role = text.title()
        elif current_role:
            entries.append(CreditEntry(role=current_role, name=text, timestamp=cl.timestamp))
        else:
            entries.append(CreditEntry(role="", name=text, timestamp=cl.timestamp))
    return entries


_PROMPT = (
    "You are parsing OCR text from a film's end credits (likely Swedish). The lines "
    "are in order but may contain OCR errors. Extract every role -> person mapping.\n"
    "Return ONLY a JSON array of objects with keys \"role\", \"name\", and "
    "\"original_role\":\n"
    "- \"name\": the person's name in normal capitalization 'Firstname Lastname' "
    "(fix all-caps/garbled casing; preserve particles/intercaps like 'von Essen', "
    "'af Hällström', 'McKay'). Emit one object per person; if a role lists several "
    "people, repeat the role once per person.\n"
    "- \"original_role\": the role text exactly as written in the credits (only "
    "correct obvious OCR errors).\n"
    "- \"role\": map original_role to the SINGLE closest title from the CONTROLLED "
    "TITLE LIST below and output that title VERBATIM. If none is a great match, pick "
    "the closest anyway. NEVER output a title that is not in the list.\n"
    "For cast lines that pair a character with an actor (e.g. 'Charlotta  Petra "
    "Sundqvist'), put the character in original_role, map role to the actor title "
    "(e.g. 'Skådespelare / Actor', or 'Statist / Extra' for extras), and put ONLY "
    "the actor's real name in \"name\".\n"
    "Skip section headers with no person, logos, copyright notices, and song/music "
    "license blocks (handled elsewhere). Do not invent entries.\n\n"
    "CONTROLLED TITLE LIST (output 'role' verbatim from here):\n{titles}\n\n"
    "CREDITS TEXT:\n"
)


def llm_structure(lines: List[CreditLine]) -> Optional[List[CreditEntry]]:
    if not CONFIG.anthropic_api_key:
        return None
    text = "\n".join(cl.text for cl in lines)
    prompt = _PROMPT.format(titles="\n".join(load_titles()))
    payload = {
        "model": CONFIG.anthropic_model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt + text}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": CONFIG.anthropic_api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        body = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        parsed = json.loads(_extract_json_array(body))
        return [
            CreditEntry(role=str(o.get("role", "")).strip(),
                        name=str(o.get("name", "")).strip(),
                        original_role=str(o.get("original_role", "")).strip(),
                        method="llm")
            for o in parsed
            if o.get("name")
        ]
    except Exception:
        return None


def _extract_json_array(body: str) -> str:
    start = body.find("[")
    end = body.rfind("]")
    if start != -1 and end != -1 and end > start:
        return body[start:end + 1]
    return body


def enforce_titles(entries: List[CreditEntry]) -> List[CreditEntry]:
    """Map every entry's role onto a legit title; flag ones that don't map.

    Keeps the credit's wording in ``original_role`` and overwrites ``role`` with
    the canonical title so the database only ever sees approved titles.
    """
    for e in entries:
        original = e.original_role or e.role
        e.original_role = original
        canon = map_role(e.role) or (map_role(original) if original != e.role else None)
        if canon:
            e.role = canon
        elif e.role or original:
            e.needs_check = True
            e.check_reason = "Roll saknas i titellistan – kontrollera"
    return entries


def structure_credits(lines: List[CreditLine]) -> tuple[List[CreditEntry], str]:
    """Return (entries, method_used). Roles are mapped to legit titles."""
    llm = llm_structure(lines)
    if llm is not None:
        return enforce_titles(llm), "llm"
    return enforce_titles(heuristic_structure(lines)), "heuristic"
