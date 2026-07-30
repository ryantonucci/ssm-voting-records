#!/usr/bin/env python3
"""
Parses downloaded Sault Ste. Marie council minutes PDFs into structured data.

For each PDF in ./pdfs/, extracts:
  - agenda item number + title
  - mover / seconder
  - the resolution text
  - outcome (Carried / Defeated)
  - if a recorded (named) vote was held: each councillor's vote
    (For / Against / Conflict / Absent)

Output:
  ./parsed/<pdf-name>.json   -- full structured detail per meeting
  ./votes_rollup.csv         -- one row per agenda item across all meetings,
                                with per-councillor votes as columns when recorded

Usage:
    pip install pdfplumber
    python 2_parse_minutes.py

NOTE: This is a best-effort parser based on the layout of minutes I inspected
(Sept 22 2025 and similar). Ontario municipal minutes formats are fairly
standardized but not guaranteed identical across years -- if a meeting's
layout is meaningfully different (e.g. pre-2023 minutes, or a Committee of
the Whole session formatted differently), you'll likely need to tweak the
regexes below. Print statements are left in deliberately so you can see
what's being skipped/misparsed as you run it against your real corpus.
"""

import csv
import json
import re
from pathlib import Path

import pdfplumber

PDF_DIR = Path("pdfs")
PARSED_DIR = Path("parsed")
PARSED_DIR.mkdir(exist_ok=True)


# Item headers look like "7.4 Sackville Road Extension" or "12.1.2 By-law...".
# Require: (a) the top-level number component is small (real agendas rarely
# exceed ~20 top-level items -- this rejects false positives like a bare
# "2024" from a line-wrapped year), and (b) the text after the number starts
# with a capital letter or "(" -- real headers are titles; continuation text
# wrapped from the previous line ("2024\nbe received as information.") starts
# lowercase and gets rejected.
ITEM_HEADER_RE = re.compile(
    r"^\s*(\d{1,2}(?:\.\d{1,3}){0,3})\s+([A-Z(].+)$"
)
# Strips a trailing page-range like " 27 - 36" that Sault Ste. Marie agendas
# (not minutes) append to each item title from their table of contents.
TITLE_PAGE_RANGE_RE = re.compile(r"\s+\d+\s*[-–]\s*\d+\s*$")

BYLAW_RE = re.compile(r"By-?[Ll]aw\s+(\d{4}-\d+)")

# Minutes use "Moved by: Councillor X" / "Seconded by: Councillor Y" (with
# colon). Agendas use "Mover Councillor X" / "Seconder Councillor Y" (no
# colon). Support both -- this was the main reason mover/seconder came back
# null on agenda documents.
MOVED_BY_RE = re.compile(r"^(?:Moved by|Mover):?\s*(.+)$")
SECONDED_BY_RE = re.compile(r"^(?:Seconded by|Seconder):?\s*(.+)$")
OUTCOME_RE = re.compile(r"^\s*(Carried|Defeated)\s*$", re.MULTILINE)

VOTE_HEADER_CELLS = {"for", "against", "conflict", "absent"}

# Every agenda/minutes PDF states its meeting date near the top of page 1,
# e.g. "Monday, April 7, 2025" or "Tuesday, October 1, 2024". This is more
# reliable than the filename (which is sometimes missing a date entirely --
# see download-time "unknown-date_..." files) and lets us double check the
# filename-derived date too.
MEETING_DATE_RE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})\b"
)
MONTH_NAME_TO_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


# Identifies actual City Council meetings (as opposed to sub-committees like
# Municipal Heritage Committee, PRAC, etc., which have different membership
# and aren't part of "council votes"). Filename text is unreliable for this
# across the corpus (older files are just "2022_11_15_Minutes.pdf" with no
# descriptive text), but every PDF states its meeting type in a heading on
# page 1, e.g. "REGULAR MEETING OF CITY COUNCIL" or "Budget Meeting of City
# Council".
MEETING_TYPE_RE = re.compile(
    r"(Inaugural|Regular|Special|Budget)\s+Meeting\s+of\s+City\s+Council", re.IGNORECASE
)


def extract_meeting_type(full_text):
    """Returns 'Regular' / 'Special' / 'Budget' / 'Inaugural' if this PDF is
    an actual City Council meeting, else None (a committee or other body)."""
    m = MEETING_TYPE_RE.search(full_text[:300])
    if not m:
        return None
    return m.group(1).capitalize()


def extract_meeting_date(full_text):
    """Returns 'YYYY-MM-DD' parsed from the first date-like line in the PDF
    text (searched only near the top, to avoid matching a date mentioned
    inside some unrelated agenda item further down), or None."""
    m = MEETING_DATE_RE.search(full_text[:1500])
    if not m:
        return None
    month_name, day, year = m.groups()
    month = MONTH_NAME_TO_NUM[month_name.lower()]
    try:
        return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    except ValueError:
        return None


def find_vote_tables(pdf):
    """
    Scans every page for bordered tables whose header row matches
    For/Against/Conflict/Absent, and returns a list of
    (page_number, {councillor_name: vote}) tuples in document order.
    """
    results = []
    for page_num, page in enumerate(pdf.pages, start=1):
        tables = page.extract_tables()
        for table in tables:
            if not table or not table[0]:
                continue
            header = [c.strip().lower() if c else "" for c in table[0]]
            if not VOTE_HEADER_CELLS.issubset(set(header)):
                continue

            votes = {}
            for row in table[1:]:
                if not row or not row[0]:
                    continue
                name = row[0].replace("\n", " ").strip()
                if name.lower().startswith("results"):
                    continue
                choice = None
                for col_idx, col_name in enumerate(header):
                    if col_idx < len(row) and row[col_idx] and row[col_idx].strip().upper() == "X":
                        choice = col_name
                        break
                if name:
                    votes[name] = choice
            results.append((page_num, votes))
    return results


def parse_pdf(path):
    with pdfplumber.open(path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        vote_tables = find_vote_tables(pdf)

    lines = full_text.split("\n")

    items = []
    current = None
    vote_table_iter = iter(vote_tables)
    next_vote_table = next(vote_table_iter, None)

    for line in lines:
        stripped = line.strip()

        header_match = ITEM_HEADER_RE.match(stripped)
        # Heuristic: treat as a new agenda item header only if it starts with
        # a number like "7.4" or "12.1.2" followed by real title text (not a
        # lone number, not something already captured as Moved/Seconded).
        if header_match and not stripped.lower().startswith(("moved by", "seconded by")):
            item_num, title = header_match.groups()
            title = TITLE_PAGE_RANGE_RE.sub("", title).strip()
            # Filter out false positives: page numbers, dates, etc.
            if len(title) > 3 and not title.strip().isdigit():
                if current:
                    items.append(current)
                current = {
                    "item_number": item_num,
                    "title": title.strip(),
                    "bylaw_numbers": [],
                    "mover": None,
                    "seconder": None,
                    "outcome": None,
                    "recorded_vote": None,
                }

        if current is None:
            continue

        bylaw_matches = BYLAW_RE.findall(line)
        for b in bylaw_matches:
            if b not in current["bylaw_numbers"]:
                current["bylaw_numbers"].append(b)

        m = MOVED_BY_RE.search(line)
        if m:
            current["mover"] = m.group(1).strip()

        s = SECONDED_BY_RE.search(line)
        if s:
            current["seconder"] = s.group(1).strip()

        if stripped in ("Carried", "Defeated"):
            current["outcome"] = stripped

    if current:
        items.append(current)

    # Attach vote tables to items in order of appearance. This is a heuristic:
    # we assume vote tables appear in the same order as the items that
    # triggered them, which held true in the samples inspected, but you
    # should spot-check a few outputs against the source PDF.
    non_none_items = [i for i in items if i["outcome"] is not None or i["bylaw_numbers"]]
    for (page_num, votes), item in zip(vote_tables, non_none_items[-len(vote_tables):] if vote_tables else []):
        item["recorded_vote"] = votes

    lower_name = path.name.lower()
    if "minutes" in lower_name:
        doc_type = "minutes"
    elif "agenda" in lower_name:
        doc_type = "agenda"
    else:
        doc_type = "unknown"

    return {
        "source_file": path.name,
        "document_type": doc_type,
        "meeting_date": extract_meeting_date(full_text),
        "meeting_type": extract_meeting_type(full_text),
        "items": items,
    }


def main():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}/. Run 1_download_minutes.py first.")
        return

    all_rows = []
    all_councillors = set()

    for pdf_path in pdfs:
        print(f"Parsing {pdf_path.name} ...")
        try:
            data = parse_pdf(pdf_path)
        except Exception as e:
            print(f"  ! failed to parse {pdf_path.name}: {e}")
            continue

        if data["document_type"] == "agenda":
            print(f"  ! WARNING: {pdf_path.name} is an AGENDA, not minutes -- "
                  "outcomes and recorded votes will be missing/incomplete. "
                  "Find the real minutes file for this date if you need votes.")
        elif data["document_type"] == "unknown":
            print(f"  ? {pdf_path.name}: couldn't tell agenda vs minutes from filename, check manually.")

        out_path = PARSED_DIR / (pdf_path.stem + ".json")
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)

        # Prefer the date parsed out of the PDF's own text (authoritative) over
        # the filename prefix (which is sometimes "unknown-date").
        filename_date = pdf_path.name.split("_")[0]
        meeting_date = data.get("meeting_date") or filename_date
        if data.get("meeting_date") and data["meeting_date"] != filename_date and filename_date != "unknown-date":
            print(f"  ! filename date ({filename_date}) disagrees with in-PDF date ({data['meeting_date']}); using in-PDF date")
        for item in data["items"]:
            row = {
                "meeting_date": meeting_date,
                "document_type": data["document_type"],
                "item_number": item["item_number"],
                "title": item["title"],
                "bylaw_numbers": "; ".join(item["bylaw_numbers"]),
                "mover": item["mover"],
                "seconder": item["seconder"],
                "outcome": item["outcome"],
                "recorded_vote": bool(item["recorded_vote"]),
            }
            if item["recorded_vote"]:
                for councillor, vote in item["recorded_vote"].items():
                    all_councillors.add(councillor)
                    row[councillor] = vote
            all_rows.append(row)

    if not all_rows:
        print("No agenda items parsed -- check the parser against a sample PDF manually.")
        return

    fieldnames = ["meeting_date", "document_type", "item_number", "title", "bylaw_numbers",
                  "mover", "seconder", "outcome", "recorded_vote"] + sorted(all_councillors)

    with open("votes_rollup.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"\nParsed {len(pdfs)} PDFs, {len(all_rows)} agenda items total.")
    print("Per-meeting JSON in ./parsed/, rollup in ./votes_rollup.csv")


if __name__ == "__main__":
    main()
