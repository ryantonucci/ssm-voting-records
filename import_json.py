#!/usr/bin/env python3

import json
import sqlite3
from pathlib import Path
from datetime import datetime

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent

DB_FILE = PROJECT_ROOT / "dbs" / "council.db"
JSON_DIR = PROJECT_ROOT / "parsed"

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("PRAGMA foreign_keys = ON")

# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def get_or_create_councillor(name):

    if not name:
        return None

    cur.execute(
        "SELECT id FROM councillors WHERE name=?",
        (name,)
    )

    row = cur.fetchone()

    if row:
        return row["id"]

    cur.execute(
        "INSERT INTO councillors(name) VALUES(?)",
        (name,)
    )

    return cur.lastrowid


def meeting_date_from_filename(source_file):

    # 2024-08-12_minutes.pdf
    stem = Path(source_file).stem

    try:
        return str(datetime.strptime(stem[:10], "%Y-%m-%d").date())
    except:
        return None


# ------------------------------------------------------------
# Import
# ------------------------------------------------------------

meetings_added = 0
items_added = 0
bylaws_added = 0

for json_file in sorted(JSON_DIR.glob("*.json")):

    with open(json_file, encoding="utf-8") as f:
        meeting = json.load(f)

    source_file = meeting["source_file"]

    meeting_date = meeting.get("meeting_date") or meeting_date_from_filename(source_file)

    document_type = meeting.get("document_type", "unknown")
    meeting_type = meeting.get("meeting_type")

    # --------------------------------------------------------

    cur.execute("""
        INSERT OR IGNORE INTO meetings
        (meeting_date, source_file, document_type, meeting_type)
        VALUES (?, ?, ?, ?)
    """, (
        meeting_date,
        source_file,
        document_type,
        meeting_type
    ))

    if cur.rowcount:
        meetings_added += 1

    cur.execute(
        "SELECT id FROM meetings WHERE source_file=?",
        (source_file,)
    )

    meeting_id = cur.fetchone()["id"]

    # --------------------------------------------------------

    for item in meeting["items"]:

        mover_id = get_or_create_councillor(item.get("mover"))

        seconder_id = get_or_create_councillor(item.get("seconder"))

        cur.execute("""
            INSERT OR IGNORE INTO agenda_items(

                meeting_id,

                item_number,

                title,

                mover_id,

                seconder_id,

                outcome

            )

            VALUES (?, ?, ?, ?, ?, ?)

        """, (

            meeting_id,

            item["item_number"],

            item["title"],

            mover_id,

            seconder_id,

            item.get("outcome")

        ))

        if cur.rowcount == 0:
            # meeting_id + item_number already exists (e.g. a genuine duplicate
            # item number within one merged agenda PDF) -- skip its bylaws too,
            # rather than attaching them to a stale/unrelated agenda_item_id.
            continue

        agenda_item_id = cur.lastrowid

        items_added += 1

        for bylaw in item.get("bylaw_numbers", []):

            cur.execute("""
                INSERT OR IGNORE INTO bylaws(

                    meeting_id,

                    agenda_item_id,

                    bylaw_number

                )

                VALUES (?, ?, ?)

            """, (

                meeting_id,

                agenda_item_id,

                bylaw

            ))

            if cur.rowcount:
                bylaws_added += 1

conn.commit()

print()
print("Import complete")
print("----------------------------")
print(f"Meetings     : {meetings_added}")
print(f"Agenda items : {items_added}")
print(f"Bylaws       : {bylaws_added}")

cur.execute("SELECT COUNT(*) FROM councillors")
print(f"Councillors  : {cur.fetchone()[0]}")

conn.close()