"""Write the structured credits as TXT and CSV/XLSX."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import List

from ..credits.structure import CreditEntry
from ..util import fmt_timecode

# Headers mirror the archive's SLUTTEXTER (ALLA) table: Roll | Namn.
# Tidskod (timecode) is appended as evidence of where the line was seen.
_COLUMNS = ["Roll", "Namn", "Tidskod"]


def _row(e: CreditEntry) -> dict:
    return {
        "Roll": e.role,
        "Namn": e.name,
        "Tidskod": fmt_timecode(e.timestamp) if e.timestamp is not None else "",
    }


def write_credits(entries: List[CreditEntry], out_dir: str, basename: str = "credits") -> List[str]:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows = [_row(e) for e in entries]
    written: List[str] = []

    txt_path = os.path.join(out_dir, f"{basename}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for e in entries:
            if e.role:
                f.write(f"{e.role}: {e.name}\n")
            else:
                f.write(f"{e.name}\n")
    written.append(txt_path)

    csv_path = os.path.join(out_dir, f"{basename}.csv")
    # utf-8-sig so Excel on Windows renders Swedish characters (å/ä/ö) correctly.
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    written.append(csv_path)

    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Sluttexter"
        ws.append(_COLUMNS)
        for r in rows:
            ws.append([r[c] for c in _COLUMNS])
        xlsx_path = os.path.join(out_dir, f"{basename}.xlsx")
        wb.save(xlsx_path)
        written.append(xlsx_path)
    except Exception:
        pass

    return written
