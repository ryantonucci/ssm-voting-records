#!/usr/bin/env python3

from pathlib import Path
import sqlite3

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DB_DIR = PROJECT_ROOT / "dbs"
DB_DIR.mkdir(exist_ok=True)

DB_FILE = DB_DIR / "council.db"

# ---------------------------------------------------------------------
# Create database
# ---------------------------------------------------------------------

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

cur.execute("PRAGMA foreign_keys = ON;")

# ---------------------------------------------------------------------
# Meetings
# ---------------------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS meetings (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    meeting_date TEXT,
    source_file TEXT NOT NULL UNIQUE,
    document_type TEXT NOT NULL,
    meeting_type TEXT
);
""")

# ---------------------------------------------------------------------
# Councillors
# ---------------------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS councillors (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    name TEXT NOT NULL UNIQUE
);
""")

# ---------------------------------------------------------------------
# Agenda Items
# ---------------------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS agenda_items (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    meeting_id INTEGER NOT NULL,

    item_number TEXT,
    title TEXT NOT NULL,

    mover_id INTEGER,
    seconder_id INTEGER,

    outcome TEXT,

    FOREIGN KEY(meeting_id)
        REFERENCES meetings(id)
        ON DELETE CASCADE,

    FOREIGN KEY(mover_id)
        REFERENCES councillors(id),

    FOREIGN KEY(seconder_id)
        REFERENCES councillors(id)
    
    UNIQUE(meeting_id, item_number)
);
""")

# ---------------------------------------------------------------------
# Bylaws
# ---------------------------------------------------------------------

cur.execute("""
CREATE TABLE IF NOT EXISTS bylaws (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    meeting_id INTEGER NOT NULL,
    agenda_item_id INTEGER NOT NULL,

    bylaw_number TEXT NOT NULL,

    FOREIGN KEY(meeting_id)
        REFERENCES meetings(id)
        ON DELETE CASCADE,

    FOREIGN KEY(agenda_item_id)
        REFERENCES agenda_items(id)
        ON DELETE CASCADE,

    UNIQUE(meeting_id, bylaw_number)
);
""")

# ---------------------------------------------------------------------
# Helpful indexes
# ---------------------------------------------------------------------

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_meeting_date
ON meetings(meeting_date);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_agenda_meeting
ON agenda_items(meeting_id);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_agenda_title
ON agenda_items(title);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_mover
ON agenda_items(mover_id);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_seconder
ON agenda_items(seconder_id);
""")

cur.execute("""
CREATE INDEX IF NOT EXISTS idx_bylaw_number
ON bylaws(bylaw_number);
""")

conn.commit()
conn.close()

print(f"Database created successfully.")
print(f"Location: {DB_FILE}")
