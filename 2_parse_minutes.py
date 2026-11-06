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

The actual parsing lives in minutes_parser.py (layout-aware: item headers
are recognised by their left-margin position, recorded-vote tables by
column positions, and every motion within an item is kept). Each item's
mover/seconder/outcome/resolution_text describe its main motion; all
motions (amendments, budget amendments, ...) are in item["motions"].

Agenda packages are parsed only up to the agenda's own Adjournment item.
Minutes of an earlier meeting attached to a package (for adoption) are
written as their own document -- but only when that meeting's own minutes
PDF hasn't been downloaded -- so meetings whose minutes were never posted
separately still get real outcomes.

Check results with audit_minutes.py and tests/ (gold set).
"""

import csv
import json
import re
from multiprocessing import Pool
from pathlib import Path

from minutes_parser import parse_pdf

PDF_DIR = Path("pdfs")
PARSED_DIR = Path("parsed")
PARSED_DIR.mkdir(exist_ok=True)

# Minutes recovered from inside a later meeting's agenda package (see
# minutes_parser.parse_pdf) are written under this synthetic source name.
EMBEDDED_MARKER = "_minutes_Minutes-attached-to-"


def doc_type_from_name(name):
    lower_name = name.lower()
    if "minutes" in lower_name:
        return "minutes"
    if "agenda" in lower_name:
        return "agenda"
    return "unknown"


def parse_one(pdf_path):
    """Worker: parses one PDF, returns (pdf_path, main_doc, embedded) or
    (pdf_path, None, error message)."""
    try:
        doc_type = doc_type_from_name(pdf_path.name)
        main, embedded = parse_pdf(pdf_path, doc_type)
        return pdf_path, main, embedded
    except Exception as e:  # keep going -- one bad PDF shouldn't stop the run
        return pdf_path, None, str(e)


def to_record(source_file, doc_type, doc, source_pdf=None):
    return {
        "source_file": source_file,
        "source_pdf": source_pdf or source_file,
        "document_type": doc_type,
        "meeting_date": doc["meeting_date"],
        "meeting_type": doc["meeting_type"],
        "pages": doc["pages"],
        "items": doc["items"],
    }


def main():
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}/. Run 1_download_minutes.py first.")
        return

    # parsed/ is fully derived; clear it so a PDF that was removed, or
    # minutes once recovered from an agenda package and since published on
    # their own, never leave a stale JSON behind.
    for old in PARSED_DIR.glob("*.json"):
        old.unlink()

    with Pool() as pool:
        results = pool.map(parse_one, pdfs, chunksize=1)

    records = []
    embedded_records = []
    for pdf_path, data, extra in results:
        print(f"Parsing {pdf_path.name} ...")
        if data is None:
            print(f"  ! failed to parse {pdf_path.name}: {extra}")
            continue
        doc_type = doc_type_from_name(pdf_path.name)
        if doc_type == "agenda":
            print(f"  ! WARNING: {pdf_path.name} is an AGENDA, not minutes -- "
                  "outcomes and recorded votes will be missing/incomplete.")
        elif doc_type == "unknown":
            print(f"  ? {pdf_path.name}: couldn't tell agenda vs minutes from filename, check manually.")
        records.append(to_record(pdf_path.name, doc_type, data))

        rest = re.sub(r"^[^_]+_[^_]+_", "", pdf_path.stem)
        for emb in extra:
            if not emb["meeting_date"]:
                continue
            name = f"{emb['meeting_date']}{EMBEDDED_MARKER}{rest}.pdf"
            print(f"  + found minutes of {emb['meeting_date']} attached (pages {emb['pages'][0]}-{emb['pages'][1]})")
            embedded_records.append(to_record(name, "minutes", emb, source_pdf=pdf_path.name))

    # Attached minutes are only used for meetings whose own minutes PDF we
    # don't have; a published minutes PDF always wins.
    have_minutes = {
        (r["meeting_date"], r["meeting_type"])
        for r in records
        if r["document_type"] == "minutes" and r["meeting_type"]
    }
    seen = set()
    for r in embedded_records:
        key = (r["meeting_date"], r["meeting_type"])
        if key in have_minutes or key in seen:
            continue
        seen.add(key)
        records.append(r)

    all_rows = []
    all_councillors = set()
    for data in records:
        out_path = PARSED_DIR / (Path(data["source_file"]).stem + ".json")
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)

        # Prefer the date parsed out of the PDF's own text (authoritative) over
        # the filename prefix (which is sometimes "unknown-date").
        filename_date = data["source_file"].split("_")[0]
        meeting_date = data.get("meeting_date") or filename_date
        if data.get("meeting_date") and data["meeting_date"] != filename_date and filename_date != "unknown-date":
            print(f"  ! {data['source_file']}: filename date ({filename_date}) disagrees with in-PDF date ({data['meeting_date']}); using in-PDF date")
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

    print(f"\nParsed {len(pdfs)} PDFs ({len(records)} documents incl. attached minutes), "
          f"{len(all_rows)} agenda items total.")
    print("Per-meeting JSON in ./parsed/, rollup in ./votes_rollup.csv")


if __name__ == "__main__":
    main()
