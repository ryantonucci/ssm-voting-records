#!/usr/bin/env python3
"""Exports council.db into web/public/data.json for the dashboard.

Scope: every actual City Council meeting (Regular / Special / Budget /
Inaugural — as classified by meeting_type in 2_parse_minutes.py, not by
filename), as far back and as current as the source PDFs go, split into the
council terms listed in council_terms.json. Sub-committees (Heritage, PRAC, etc.) are
excluded — different membership, not "council votes." Only actual
councillors (rows whose name starts with "Councillor ") are included; the
parser also picked up incidental names from other committees and OCR noise,
which we exclude here rather than in the app.

For dates where both an agenda and the final minutes exist, minutes win
(they have real outcomes/recorded votes; agendas are just proposed
motions). For the most recent meetings where minutes haven't been posted
yet, we fall back to the agenda so the dashboard stays as current as
possible — those rows are marked "Pending" instead of a real outcome.

Beyond what's in the database, this also pulls the full "Resolved that
..." motion text for each item from parsed/*.json (the DB only keeps the
short agenda title). That text is produced by the same parser that found
the item's mover/seconder/outcome (minutes_parser.py), so the two can't
disagree about where one item ends and the next begins. It also computes a
simple keyword-based "importance" score used to surface a Top 10 per
councillor -- a heuristic (see score_item()), a rough first pass to refine
later, not an authoritative ranking.
"""

import json
import re
from pathlib import Path

from council_data import connect, get_scoped_items, get_scoped_meetings, short_name

PROJECT_ROOT = Path(__file__).resolve().parent
PARSED_DIR = PROJECT_ROOT / "parsed"
TERMS_FILE = PROJECT_ROOT / "council_terms.json"
OUT_FILE = PROJECT_ROOT / "web" / "public" / "data.json"


def load_parsed_items(source_file):
    """Returns {item_number: parsed item} for one meeting, from the parsed
    JSON that 2_parse_minutes.py wrote for its source document. First
    occurrence wins, matching import_json.py's INSERT OR IGNORE."""
    path = PARSED_DIR / (Path(source_file).stem + ".json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    result = {}
    for item in data["items"]:
        result.setdefault(item["item_number"], item)
    return result


MOTION_LABELS = {
    "main": "",
    "main_as_amended": " (motion as amended)",
    "amendment": " (amendment)",
    "additional": " (further motion)",
    "procedural": " (procedural motion)",
    "text": "",
}
VOTE_ROLES = {"for": "Voted for", "against": "Voted against", "conflict": "Conflict", "absent": "Absent"}


def recorded_votes(parsed_items, member):
    """One entry per recorded (named) vote `member` appears in, across all
    motions of the given parsed items."""
    out = []
    for item in parsed_items:
        for mo in item.get("motions", []):
            rv = mo.get("recorded_vote")
            if not rv or member not in rv["votes"]:
                continue
            out.append((item, mo, rv["votes"][member]))
    return out


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

    # Full resolution text (and recorded votes) per meeting, from parsed/*.json.
    parsed_by_meeting = {
        mid: load_parsed_items(meeting["source_file"]) for mid, meeting in meetings.items()
    }

    for it in items:
        parsed = parsed_by_meeting.get(it["meeting_id"], {}).get(it["item_number"]) or {}
        full_text = parsed.get("resolution_text")
        it["fullText"] = full_text or it["title"]
        it["bylawCount"] = bylaw_counts.get(it["id"], 0)
        it["score"] = score_item(it["title"], it["fullText"], it["outcome"], it["bylawCount"])

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

    def build_councillor(full_name, ward, term_items):
        rows = []
        for it in term_items:
            if it["mover"] == full_name:
                rows.append(build_row(it, "Moved"))
            elif it["seconder"] == full_name:
                rows.append(build_row(it, "Seconded"))
        rows.sort(key=lambda r: (r["date"] or ""), reverse=True)

        top10 = sorted(rows, key=lambda r: (r["score"], r["date"] or ""), reverse=True)[:10]

        return {
            "name": full_name,
            "shortName": short_name(full_name),
            "ward": ward,
            "count": len(rows),
            "movedCount": sum(1 for r in rows if r["role"] == "Moved"),
            "secondedCount": sum(1 for r in rows if r["role"] == "Seconded"),
            "items": rows,
            "top10": top10,
        }

    def build_mayor(full_name, term_items):
        """The mayor chairs meetings, so the minutes almost never list him as
        mover or seconder; his record is his recorded (named) votes, plus
        any moved/seconded rows the minutes do attribute to him."""
        base = build_councillor(full_name, None, term_items)
        by_key = {(it["meeting_id"], it["item_number"]): it for it in term_items}
        rows = []
        tally = {k: 0 for k in VOTE_ROLES}
        for mid in sorted({it["meeting_id"] for it in term_items}):
            if meetings[mid]["document_type"] != "minutes":
                continue
            parsed = [p for p in parsed_by_meeting.get(mid, {}).values()
                      if (mid, p["item_number"]) in by_key]
            for item, mo, vote in recorded_votes(parsed, full_name):
                it = by_key[(mid, item["item_number"])]
                if vote in tally:
                    tally[vote] += 1
                rows.append({
                    "date": it["date"],
                    "number": it["item_number"],
                    "description": it["title"] + MOTION_LABELS.get(mo["kind"], ""),
                    "fullText": mo.get("text") or it["fullText"],
                    "role": VOTE_ROLES.get(vote, "Not recorded"),
                    "result": mo.get("outcome") or "—",
                    "pending": False,
                    "score": it["score"],
                    "bylawCount": it["bylawCount"],
                    "sourceFile": it["sourceFile"],
                })
        rows.sort(key=lambda r: (r["date"] or ""), reverse=True)
        base.update(
            {
                "role": "Mayor",
                "shortName": re.sub(r"^Mayor\s+", "", full_name),
                "voteCount": len(rows),
                "votes": tally,
                "voteItems": rows,
            }
        )
        return base

    # Rosters come from council_terms.json, not the minutes: right after an
    # election the new councillors have no recorded votes yet but should still
    # be listed. Each item belongs to the term whose date range contains it;
    # anyone with votes in a term but missing from its roster (e.g. a
    # mid-term appointment) is still listed, just without a ward.
    terms_config = json.loads(TERMS_FILE.read_text())["terms"]
    terms_config.sort(key=lambda t: t["start"], reverse=True)

    terms = []
    for i, term in enumerate(terms_config):
        end = terms_config[i - 1]["start"] if i > 0 else None
        is_oldest = i == len(terms_config) - 1
        term_items = [
            it
            for it in items
            if (is_oldest or (it["date"] or "") >= term["start"])
            and (end is None or (it["date"] or "") < end)
        ]
        term_meeting_ids = {it["meeting_id"] for it in term_items}
        term_dates = sorted(
            meetings[mid]["meeting_date"]
            for mid in term_meeting_ids
            if meetings[mid]["meeting_date"]
        )

        ward_by_name = {c["name"]: c["ward"] for c in term["councillors"]}
        names = set(ward_by_name) | {
            it[role]
            for it in term_items
            for role in ("mover", "seconder")
            if it[role] and it[role].startswith("Councillor ")
        }
        councillors = [build_councillor(n, ward_by_name.get(n), term_items) for n in names]
        councillors.sort(key=lambda c: (c["ward"] is None, c["ward"] or 0, c["shortName"]))

        terms.append(
            {
                "term": term["term"],
                "start": term["start"],
                "end": end,
                "meetingCount": len(term_meeting_ids),
                "itemCount": len(term_items),
                "firstMeetingDate": term_dates[0] if term_dates else None,
                "latestMeetingDate": term_dates[-1] if term_dates else None,
                "pendingCount": sum(1 for it in term_items if it["pending"]),
                "mayor": build_mayor(term["mayor"], term_items) if term.get("mayor") else None,
                "councillors": councillors,
            }
        )

    data = {"terms": terms}

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, indent=2))
    print(f"Wrote {OUT_FILE}")
    for t in terms:
        print(
            f"  {t['term']}: {t['meetingCount']} meetings, {t['itemCount']} items, "
            f"{len(t['councillors'])} councillors"
        )

if __name__ == "__main__":
    main()
