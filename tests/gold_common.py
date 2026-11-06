"""Shared helpers for the gold-set fixtures (see test_gold.py)."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = PROJECT_ROOT / "parsed"
GOLD_DIR = Path(__file__).resolve().parent / "gold"

# The gold meetings: chosen to span 2022-2026 and every layout variant the
# parser has to handle. Each was checked item by item against the PDF text.
GOLD_DOCS = [
    "2022-11-21_minutes_2022_11_21_Minutes",                     # oldest format (F1/F2 fonts), postponement, recorded votes
    "2023-01-30_minutes_2023_01_30_Minutes",                     # Amendment + "Motion as Amended", substituted motion
    "2023-08-28_minutes_Post-Meeting-Minutes-Regular-Council-Meeting_Aug28_2023-English_1",  # item number reused in source
    "2023-12-11_minutes_Post-Meeting-Minutes-Budget-Meeting_Dec11_2023-English",  # budget: many motions per item
    "2024-06-24_minutes_2024_06_24-Minutes-1",                   # "Postponement:" label, by-law passed under item 8
    "2024-10-10_minutes_2024_10_10-Minutes",                     # special meeting, "Moved By" spelling
    "2025-01-13_minutes_Post-Meeting-Minutes-Regular-Council-Meeting_Jan13_2025-English",  # indented 4-level sub-items
    "2025-09-22_minutes_Post-Meeting-Minutes-Regular-Council-Meeting_Sep22_2025-English",  # consent agenda, many by-laws, split vote tables
    "2026-03-23_minutes_Post-Meeting-Minutes-Regular-Council-Meeting_Mar23_2026-English",  # unlabelled restated motion after amendment
    "2026-07-13_minutes_Minutes-attached-to-Merged-Agenda-Package-Regular-Council-Meeting_Aug10_2026",  # minutes recovered from an agenda package
    "2026-11-09_agenda_Agenda-Package-Regular-Council-Meeting_Nov09_2026",  # current agenda format (no movers yet)
]


def vote_results(item):
    for mo in item.get("motions", []):
        if mo["kind"] in ("main", "main_as_amended") and mo.get("recorded_vote"):
            res = mo["recorded_vote"].get("results")
            if res:
                return [res.get(k, 0) for k in ("for", "against", "conflict", "absent")]
    return None


def summarize(item):
    """The fields the gold set pins down for one item."""
    text = item.get("resolution_text") or ""
    return {
        "item_number": item["item_number"],
        "title": item["title"],
        "mover": item["mover"],
        "seconder": item["seconder"],
        "outcome": item["outcome"],
        "bylaw_numbers": item["bylaw_numbers"],
        "resolution_start": text[:80],
        "resolution_end": text[-40:],
        "resolution_len": len(text),
        "vote_results": vote_results(item),
        "motions": [[m["kind"], m["mover"], m["seconder"], m["outcome"]] for m in item.get("motions", [])],
    }


def load_parsed(stem):
    path = PARSED_DIR / f"{stem}.json"
    return json.loads(path.read_text()) if path.exists() else None
