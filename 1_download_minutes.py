#!/usr/bin/env python3
"""
Downloads Sault Ste. Marie, Ontario city council minutes PDFs from the last N days
(default 2 years) by querying the site's WordPress REST API for media files.

Why this approach: the minutes PDFs are WordPress media uploads. Their upload
folder (e.g. /wp-content/uploads/2026/05/) has NO relationship to the meeting
date, so guessing URLs doesn't work reliably. The WP REST API lets us search
media by filename text instead, which is far more robust.

Usage:
    pip install requests
    python 1_download_minutes.py

Output:
    ./pdfs/<YYYY-MM-DD>_<original-filename>.pdf
    ./manifest.json   (list of every file found + its detected meeting date + URL)

If the REST API is disabled or returns nothing (some WP sites lock this down),
see the fallback notes at the bottom of this file.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests

BASE = "https://saultstemarie.ca"
API = f"{BASE}/wp-json/wp/v2/media"
OUT_DIR = Path("pdfs")
OUT_DIR.mkdir(exist_ok=True)

# How far back to go. Fixed at the start of the current council term (the
# inaugural meeting of the 2023-2026 Council was Nov 15, 2022) rather than a
# rolling window, so re-running this later doesn't quietly shrink the term
# we've already collected.
CUTOFF = datetime(2022, 11, 15)

# Search terms to try against the media library. We cast a slightly wide net
# and de-duplicate, because the city varies file-naming conventions over time
# (e.g. "Post-Meeting-Minutes-Regular-Council-Meeting_Sep22_2025-English.pdf" vs
# older "Merged-Agenda-Package-Regular-Council-Meeting_Nov12_2024.pdf").
SEARCH_TERMS = [
    "Regular-Council-Meeting",
    "Council-Meeting-Minutes",
    "Post-Meeting-Minutes",
    "Special-Meeting-of-City-Council",
    "Council-Minutes",
    "Minutes",  # catches older numeric-date scheme, e.g. "2024_08_12-Minutes.pdf"
]

# The city has used at least THREE different filename date schemes across
# the corpus seen so far:
#   - "Post-Meeting-Minutes-Regular-Council-Meeting_Sep22_2025-English.pdf" (month-name)
#   - "Merged-Agenda-Package-Regular-Council-Meeting_Nov12_2024.pdf"        (month-name)
#   - "2024_08_12-Minutes.pdf"                                             (numeric, older)
# We try the numeric pattern first (more specific/less ambiguous), then fall
# back to the month-name pattern.
MONTHS = (
    "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    "Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
NUMERIC_DATE_RE = re.compile(r"(\d{4})[_-](\d{1,2})[_-](\d{1,2})")
MONTH_NAME_DATE_RE = re.compile(rf"({MONTHS})_?(\d{{1,2}})_(\d{{4}})", re.IGNORECASE)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def month_to_num(text):
    key = text[:3].lower()
    return MONTH_MAP.get(key)


def extract_date(filename):
    m = NUMERIC_DATE_RE.search(filename)
    if m:
        year, month, day = m.groups()
        try:
            return datetime(int(year), int(month), int(day))
        except ValueError:
            pass  # fall through and try the other pattern

    m = MONTH_NAME_DATE_RE.search(filename)
    if m:
        mon_text, day, year = m.groups()
        month = month_to_num(mon_text)
        if month:
            try:
                return datetime(int(year), month, int(day))
            except ValueError:
                pass

    return None


def fetch_media_for_term(term):
    """Page through the WP media API for a given search term. Returns raw items."""
    items = []
    page = 1
    while True:
        try:
            resp = requests.get(
                API,
                params={"search": term, "per_page": 100, "page": page, "media_type": "application"},
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (research script; contact: you@example.com)"},
            )
        except requests.RequestException as e:
            print(f"  ! request failed for '{term}' page {page}: {e}")
            break

        if resp.status_code == 400:
            # WP returns 400 once you page past the last page
            break
        if resp.status_code != 200:
            print(f"  ! HTTP {resp.status_code} for '{term}' page {page}: {resp.text[:200]}")
            break

        batch = resp.json()
        if not batch:
            break
        items.extend(batch)

        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)  # be polite
    return items


def main():
    print("Querying WordPress media API...")
    all_items = {}  # id -> item, de-duplicated across search terms
    for term in SEARCH_TERMS:
        print(f"  searching for: {term}")
        for item in fetch_media_for_term(term):
            all_items[item["id"]] = item

    print(f"Found {len(all_items)} unique media items across all search terms.")

    candidates = []
    for item in all_items.values():
        source_url = item.get("source_url", "")
        filename = source_url.rsplit("/", 1)[-1]
        lower = filename.lower()

        if not lower.endswith(".pdf"):
            continue
        if "correspondence" in lower or "committee-of-adjustment" in lower:
            continue
        if "council" not in lower and "minutes" not in lower:
            continue

        meeting_date = extract_date(filename)
        if meeting_date is None:
            print(f"  (could not parse a date from filename, keeping anyway: {filename})")
        elif meeting_date < CUTOFF:
            continue  # older than our window

        # IMPORTANT: distinguish minutes (the actual record of what happened,
        # incl. votes) from agendas (proposed motions, drafted BEFORE the
        # meeting -- no outcomes, no recorded votes, mover/seconder often
        # missing for routine items). We want minutes. Agendas are kept only
        # as a fallback so you can see what's missing.
        if "minutes" in lower:
            doc_type = "minutes"
        elif "agenda" in lower:
            doc_type = "agenda"
        else:
            doc_type = "unknown"

        candidates.append({
            "id": item["id"],
            "title": item.get("title", {}).get("rendered", ""),
            "filename": filename,
            "source_url": source_url,
            "meeting_date": meeting_date.strftime("%Y-%m-%d") if meeting_date else None,
            "doc_type": doc_type,
        })

    # For each meeting date, prefer the minutes doc. Only fall back to the
    # agenda if no minutes doc was found for that date, and say so loudly --
    # an agenda substituted for minutes will look plausible but is missing
    # outcomes and most recorded votes.
    by_date = {}
    for c in candidates:
        key = c["meeting_date"] or c["filename"]  # undated files each stand alone
        existing = by_date.get(key)
        if existing is None:
            by_date[key] = c
        elif existing["doc_type"] != "minutes" and c["doc_type"] == "minutes":
            by_date[key] = c  # upgrade agenda -> minutes if we find the real minutes later

    manifest = list(by_date.values())
    manifest.sort(key=lambda x: x["meeting_date"] or "0000-00-00")

    missing_minutes = [m for m in manifest if m["doc_type"] != "minutes"]
    if missing_minutes:
        print(f"\nWARNING: no 'minutes' file found for {len(missing_minutes)} meeting date(s) --")
        print("falling back to whatever was found (agenda/unknown), which will NOT have")
        print("outcomes or recorded votes. Check these manually on the city's website:")
        for m in missing_minutes:
            print(f"    {m['meeting_date']}: {m['filename']} (doc_type={m['doc_type']})")

    print(f"\n{len(manifest)} files since {CUTOFF.date()} to download.\n")

    for entry in manifest:
        date_prefix = entry["meeting_date"] or "unknown-date"
        out_name = f"{date_prefix}_{entry['doc_type']}_{entry['filename']}"
        out_path = OUT_DIR / out_name

        if out_path.exists():
            print(f"  already have: {out_name}")
            continue

        print(f"  downloading: {out_name}")
        try:
            r = requests.get(entry["source_url"], timeout=60)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        except requests.RequestException as e:
            print(f"    ! failed: {e}")
        time.sleep(0.3)

    with open("manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nDone. PDFs are in ./{OUT_DIR}/, manifest saved to ./manifest.json")


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# FALLBACK if the REST API search above turns up nothing (some WP installs
# disable the media search endpoint, or lock it to authenticated users):
#
# 1. Try browsing the endpoint directly in your own browser first:
#      https://saultstemarie.ca/wp-json/wp/v2/media?search=Regular-Council-Meeting
#    If that returns JSON, the script above should work as-is.
#
# 2. If it returns an error, fall back to crawling the human-facing page:
#      https://saultstemarie.ca/government/city-council/council-agendas-minutes-and-schedule/
#    This is built on the "Modern Events Calendar" plugin. Each meeting is its
#    own "event" page (e.g. /events/city-council-11-227-654-.../), and the
#    Minutes PDF link is embedded in that page's HTML. You'd need to:
#      a. Paginate the "Recent Meetings" list (look for a "?mec_next_page="
#         query parameter, or check if MEC exposes a REST/AJAX endpoint at
#         /wp-admin/admin-ajax.php with action=mec_monthly_view or similar --
#         inspect Network tab in your browser's dev tools while clicking
#         "Next" to find the exact request it makes).
#      b. For each event URL discovered, fetch the page and regex out
#         the href ending in ".pdf" near the text "Minutes".
#    This is more fragile (breaks if the plugin/theme changes) but works when
#    the REST API is unavailable.
#
# 3. Also worth checking manually: saultstemarie.ca/sitemap.xml or
#    /wp-sitemap.xml -- WordPress auto-generates these, and they often
#    include a dedicated sitemap of all media/attachment URLs, which you
#    could grep for "Minutes" instead of using the REST API at all.
# ---------------------------------------------------------------------------
