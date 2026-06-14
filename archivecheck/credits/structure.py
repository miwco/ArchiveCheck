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
from ..config import CONFIG

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class CreditEntry:
    role: str
    name: str
    timestamp: Optional[float] = None
    method: str = "heuristic"


_SEP_RE = re.compile(r"\s*(?::|–|—| - |\t|\s{2,})\s*")


def _looks_like_role_header(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.8 and len(text) <= 40


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
        elif _looks_like_role_header(text):
            current_role = text.title()
        elif current_role:
            entries.append(CreditEntry(role=current_role, name=text, timestamp=cl.timestamp))
        else:
            entries.append(CreditEntry(role="", name=text, timestamp=cl.timestamp))
    return entries


_PROMPT = (
    "You are parsing OCR text from a film's end credits (likely Swedish). The lines "
    "are in order but may contain OCR errors. Extract every role -> person mapping. "
    "Return ONLY a JSON array of objects with keys \"role\" and \"name\". If a single "
    "role has several people, emit one object per person. Skip titles, logos, "
    "copyright notices, and song/music license blocks (those are handled elsewhere). "
    "Do not invent entries.\n"
    "When a role clearly corresponds to one of these archive role names, use that "
    "EXACT spelling; otherwise keep the credit's own wording: {roles}.\n\n"
    "CREDITS TEXT:\n"
)


def llm_structure(lines: List[CreditLine]) -> Optional[List[CreditEntry]]:
    if not CONFIG.anthropic_api_key:
        return None
    text = "\n".join(cl.text for cl in lines)
    prompt = _PROMPT.format(roles=", ".join(CONFIG.archive_roles))
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


def structure_credits(lines: List[CreditLine]) -> tuple[List[CreditEntry], str]:
    """Return (entries, method_used)."""
    llm = llm_structure(lines)
    if llm is not None:
        return llm, "llm"
    return heuristic_structure(lines), "heuristic"
