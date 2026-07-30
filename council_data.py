#!/usr/bin/env python3
"""Shared DB-scoping logic for council.db, used by both export_dashboard_data.py
(builds web/public/data.json) and the chatbot backend (chatbot/server.py).

Keeping this in one place matters because the scoping rules are non-trivial:
only actual City Council meetings (not sub-committees), one record per date
(minutes preferred over agenda), and only real councillor names. Duplicating
this logic across two files risks them drifting out of sync.
"""

import re
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DB_FILE = PROJECT_ROOT / "dbs" / "council.db"

NAME_FIX = {
    "Councillor M Bruni": "Councillor M. Bruni",
}

DOC_TYPE_PRIORITY = {"minutes": 0, "agenda": 1, "unknown": 2}


def connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def normalize(name):
    if not name:
        return name
    return NAME_FIX.get(name, name)


def short_name(full):
    return re.sub(r"^Councillor\s+", "", full)


def pick_one_meeting_per_date(all_meetings, item_counts):
    """Groups meetings by resolved meeting_date and keeps the single best
    record for each date: minutes > agenda > unknown, tie-broken by whichever
    has more agenda items parsed out of it (a proxy for "the complete /
    merged / revised version" when a date has multiple candidate PDFs)."""
    by_date = {}
    for m in all_meetings:
        key = m["meeting_date"] or f"__undated_{m['id']}"
        by_date.setdefault(key, []).append(m)

    winners = {}
    for key, candidates in by_date.items():
        candidates.sort(
            key=lambda m: (
                DOC_TYPE_PRIORITY.get(m["document_type"], 3),
                -item_counts.get(m["id"], 0),
            )
        )
        winner = candidates[0]
        winners[winner["id"]] = winner
    return winners


def get_scoped_meetings(conn):
    """Returns {meeting_id: meeting_dict} for the one-per-date, actual-council
    scope described in the module docstring."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.id, m.meeting_date, m.source_file, m.document_type
        FROM meetings m
        WHERE m.meeting_type IS NOT NULL
        """
    )
    all_meetings = [dict(row) for row in cur.fetchall()]
    if not all_meetings:
        return {}

    cur.execute(
        "SELECT meeting_id, COUNT(*) AS n FROM agenda_items WHERE meeting_id IN ({}) GROUP BY meeting_id".format(
            ",".join(str(m["id"]) for m in all_meetings)
        )
    )
    item_counts = {row["meeting_id"]: row["n"] for row in cur.fetchall()}
    return pick_one_meeting_per_date(all_meetings, item_counts)


def get_scoped_items(conn, meetings):
    """Returns agenda_items rows (as dicts) for the given scoped meetings,
    with mover/seconder names normalized and a "pending" flag set for rows
    from a meeting whose only source is an agenda (no outcome yet)."""
    if not meetings:
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ai.id, ai.meeting_id, ai.item_number, ai.title, ai.outcome,
               cm.name AS mover, cs.name AS seconder
        FROM agenda_items ai
        LEFT JOIN councillors cm ON ai.mover_id = cm.id
        LEFT JOIN councillors cs ON ai.seconder_id = cs.id
        WHERE ai.meeting_id IN ({})
        """.format(",".join(str(mid) for mid in meetings))
    )
    items = [dict(row) for row in cur.fetchall()]
    for it in items:
        it["mover"] = normalize(it["mover"])
        it["seconder"] = normalize(it["seconder"])
        meeting = meetings[it["meeting_id"]]
        it["date"] = meeting["meeting_date"]
        it["sourceFile"] = meeting["source_file"]
        it["pending"] = meeting["document_type"] != "minutes" and not it["outcome"]
        it["result"] = "Pending" if it["pending"] else (it["outcome"] or "—")
    return items


def get_councillor_names(items):
    return sorted(
        {
            it[role]
            for it in items
            for role in ("mover", "seconder")
            if it[role] and it[role].startswith("Councillor ")
        }
    )
