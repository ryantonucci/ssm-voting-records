#!/usr/bin/env python3
"""Exports council.db into web/public/data.json for the dashboard.

Scope: every actual City Council meeting (Regular / Special / Budget /
Inaugural — as classified by meeting_type in 2_parse_minutes.py, not by
filename) for the full current council term, i.e. as far back and as
current as the source PDFs go. Sub-committees (Heritage, PRAC, etc.) are
excluded — different membership, not "council votes." Only actual
councillors (rows whose name starts with "Councillor ") are included; the
parser also picked up incidental names from other committees and OCR noise,
which we exclude here rather than in the app.

For dates where both an agenda and the final minutes exist, minutes win
(they have real outcomes/recorded votes; agendas are just proposed
motions). For the most recent meetings where minutes haven't been posted
yet, we fall back to the agenda so the dashboard stays as current as
possible — those rows are marked "Pending" instead of a real outcome.

Beyond what's in the database, this also re-reads the source PDFs to pull
the full "Resolved that ..." motion text for each item (the DB/CSV pipeline
only kept the short agenda title), and computes a simple keyword-based
"importance" score used to surface a Top 10 per councillor. Both are
heuristics — see score_item() — meant as a rough first pass to refine later,
not an authoritative ranking.
"""

import json
import re
from pathlib import Path

import pdfplumber

from council_data import connect, get_scoped_items, get_scoped_meetings, short_name

PROJECT_ROOT = Path(__file__).resolve().parent
PDF_DIR = PROJECT_ROOT / "pdfs"
OUT_FILE = PROJECT_ROOT / "web" / "public" / "data.json"

# Same header/moved/seconded/outcome patterns as 2_parse_minutes.py, reused
# here only to recover the resolution text between "Seconded by:" and the
# Carried/Defeated line for items already identified via the database.
ITEM_HEADER_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){0,3})\s+([A-Z(].+)$")
# Top-level section dividers like "5. Approve Agenda as Presented" or "7.
# Communications and Routine Reports ..." (lone number + period, no
# sub-number). These aren't real agenda items but they do carry their own
# Moved/Seconded/Resolved/Carried procedural motions -- without treating them
# as boundaries, that text (and any that follows before the next real N.M
# item) gets wrongly appended to whatever real item preceded them.
SECTION_DIVIDER_RE = re.compile(r"^\s*\d{1,2}\.\s+[A-Z(].+$")
MOVED_BY_RE = re.compile(r"^(?:Moved by|Mover):?\s*(.+)$")
SECONDED_BY_RE = re.compile(r"^(?:Seconded by|Seconder):?\s*(.+)$")
OUTCOME_LINE_RE = re.compile(r"^\s*(Carried|Defeated)\s*$")


def extract_resolution_texts(pdf_path):
    """Returns {item_number: resolution_text} for one minutes PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    lines = full_text.split("\n")

    result = {}
    current_number = None
    collecting = False
    buf = []

    def flush():
        if current_number and buf:
            text = " ".join(buf).strip()
            if text:
                result[current_number] = text

    for line in lines:
        stripped = line.strip()

        header_match = ITEM_HEADER_RE.match(stripped)
        if header_match and not stripped.lower().startswith(("moved by", "seconded by")):
            item_num, title = header_match.groups()
            if len(title) > 3 and not title.strip().isdigit():
                flush()
                current_number = item_num
                collecting = False
                buf = []
                continue

        if SECTION_DIVIDER_RE.match(stripped):
            flush()
            current_number = None
            collecting = False
            buf = []
            continue

        if current_number is None:
            continue

        if MOVED_BY_RE.match(stripped):
            collecting = False
            continue
        if SECONDED_BY_RE.match(stripped):
            collecting = True
            buf = []
            continue
        if OUTCOME_LINE_RE.match(stripped):
            flush()
            collecting = False
            continue

        if collecting and stripped:
            buf.append(stripped)

    flush()
    return result


# Keyword weights used to flag administratively significant items: budget /
# tax / borrowing / zoning / land items carry real financial or legal
# consequence, vs. routine appointments, correspondence, or by-law
# housekeeping. Weights are a rough first cut, not a validated model.
IMPORTANCE_KEYWORDS = [
    (r"\bbudget\b", 5),
    (r"\btax(es)?\b|\blevy\b|\blevies\b", 4),
    (r"\brezon(e|ing)\b|\bzoning\b|\bofficial plan\b", 4),
    (r"\bborrow(ing)?\b|\bdebenture\b", 4),
    (r"\bsurplus\b.*\bsale\b|\backquisition\b|\bexpropriation\b", 4),
    (r"\bdevelopment charges?\b", 3),
    (r"\bmaster plan\b|\bofficial plan\b", 3),
    (r"\bcapital\b", 3),
    (r"\btender\b|\baward of tender\b|\brfp\b", 3),
    (r"\bgrant\b|\bfinancial assistance\b", 2),
    (r"\bagreement\b", 1),
    (r"\bappointment\b", 1),
    (r"\$[\d,]+|\bmillion\b", 3),
]
IMPORTANCE_KEYWORDS = [(re.compile(p, re.IGNORECASE), w) for p, w in IMPORTANCE_KEYWORDS]


def score_item(title, full_text, outcome, bylaw_count):
    text = f"{title} {full_text}"
    score = 0
    for pattern, weight in IMPORTANCE_KEYWORDS:
        if pattern.search(text):
            score += weight
    if outcome == "Defeated":
        score += 5  # contested outcomes are inherently notable
    if bylaw_count:
        score += 1
    return score


def main():
    conn = connect()
    cur = conn.cursor()

    meetings = get_scoped_meetings(conn)
    if not meetings:
        print("No matching meetings found.")
        return

    cur.execute(
        "SELECT COUNT(*) FROM meetings WHERE meeting_type IS NOT NULL"
    )
    total_meetings = cur.fetchone()[0]
    dropped = total_meetings - len(meetings)
    if dropped:
        print(f"Resolved {dropped} duplicate/superseded meeting record(s) down to one per date.")

    items = get_scoped_items(conn, meetings)

    cur.execute(
        "SELECT meeting_id, agenda_item_id, bylaw_number FROM bylaws WHERE meeting_id IN ({})".format(
            ",".join(str(mid) for mid in meetings)
        )
    )
    bylaw_counts = {}
    for row in cur.fetchall():
        bylaw_counts[row["agenda_item_id"]] = bylaw_counts.get(row["agenda_item_id"], 0) + 1

    # Pull full resolution text straight from the source PDFs, per meeting.
    resolution_by_meeting = {}
    for mid, meeting in meetings.items():
        pdf_path = PDF_DIR / meeting["source_file"]
        if not pdf_path.exists():
            resolution_by_meeting[mid] = {}
            continue
        try:
            resolution_by_meeting[mid] = extract_resolution_texts(pdf_path)
        except Exception as e:
            print(f"  ! could not extract full text from {pdf_path.name}: {e}")
            resolution_by_meeting[mid] = {}

    for it in items:
        full_text = resolution_by_meeting.get(it["meeting_id"], {}).get(it["item_number"])
        it["fullText"] = full_text or it["title"]
        it["bylawCount"] = bylaw_counts.get(it["id"], 0)
        it["score"] = score_item(it["title"], it["fullText"], it["outcome"], it["bylawCount"])

    pending_count = sum(1 for it in items if it["pending"])

    councillor_names = sorted(
        {
            it[role]
            for it in items
            for role in ("mover", "seconder")
            if it[role] and it[role].startswith("Councillor ")
        }
    )

    def build_row(it, role):
        return {
            "date": it["date"],
            "number": it["item_number"],
            "description": it["title"],
            "fullText": it["fullText"],
            "role": role,
            "result": it["result"],
            "pending": it["pending"],
            "score": it["score"],
            "bylawCount": it["bylawCount"],
            "sourceFile": it["sourceFile"],
        }

    councillors = []
    for full_name in councillor_names:
        rows = []
        for it in items:
            if it["mover"] == full_name:
                rows.append(build_row(it, "Moved"))
            elif it["seconder"] == full_name:
                rows.append(build_row(it, "Seconded"))
        rows.sort(key=lambda r: (r["date"] or ""), reverse=True)

        top10 = sorted(rows, key=lambda r: (r["score"], r["date"] or ""), reverse=True)[:10]

        moved = sum(1 for r in rows if r["role"] == "Moved")
        seconded = sum(1 for r in rows if r["role"] == "Seconded")
        councillors.append(
            {
                "name": full_name,
                "shortName": short_name(full_name),
                "count": len(rows),
                "movedCount": moved,
                "secondedCount": seconded,
                "items": rows,
                "top10": top10,
            }
        )

    councillors.sort(key=lambda c: c["shortName"])

    meeting_dates = sorted(m["meeting_date"] for m in meetings.values() if m["meeting_date"])

    data = {
        "meetingCount": len(meetings),
        "itemCount": len(items),
        "termStart": meeting_dates[0] if meeting_dates else None,
        "latestMeetingDate": meeting_dates[-1] if meeting_dates else None,
        "pendingCount": pending_count,
        "councillors": councillors,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, indent=2))
    print(f"Wrote {OUT_FILE} — {len(meetings)} meetings, {len(items)} items, {len(councillors)} councillors")


if __name__ == "__main__":
    main()
