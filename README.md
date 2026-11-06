# Sault Ste. Marie Council Minutes Scraper

Two scripts:

1. **`1_download_minutes.py`** — finds and downloads council minutes PDFs from
   the last 2 years via the city's WordPress REST API, into `./pdfs/`.
2. **`2_parse_minutes.py`** — parses each PDF into structured JSON
   (`./parsed/*.json`) and a combined `./votes_rollup.csv` with one row per
   agenda item, including per-councillor votes when a recorded vote was held.

## Setup

```bash
pip install requests pdfplumber
python 1_download_minutes.py
python 2_parse_minutes.py
```

## Important: I have not run this against real files

I built this by hand-inspecting the actual text of one real minutes PDF (Sept
22, 2025) that I pulled during our conversation, plus what the "Council
Agendas, Minutes and Schedule" page and WordPress site structure told me. But
my sandbox's network access is restricted and doesn't include
`saultstemarie.ca`, so I was not able to actually execute either script or
test-download a real PDF end-to-end. Concretely, expect to spend some time
debugging:

- **The download script** relies on the WordPress REST API
  (`/wp-json/wp/v2/media`) being open to search queries. Most WP sites expose
  this by default, but some lock it down. Test it by pasting
  `https://saultstemarie.ca/wp-json/wp/v2/media?search=Regular-Council-Meeting`
  into your browser first — if you get JSON back, you're good; if you get an
  error or empty result, use the fallback approach documented in the comments
  at the bottom of `1_download_minutes.py` (crawling the human-facing agenda
  page instead).

- **The parser** (`minutes_parser.py`, used by `2_parse_minutes.py`) is
  layout-aware: item headers are found by their left-margin position and
  heading font, recorded-vote tables by column positions, and every motion in
  an item is kept (the item's mover/seconder/outcome are its main motion's).
  Agenda packages are parsed only up to the agenda's Adjournment; minutes of
  an earlier meeting attached to a package are used when that meeting has no
  minutes PDF of its own.

## Checking the data

- `python3 tests/test_gold.py` -- 11 hand-verified meetings (541 items) must
  parse exactly. After an intended parser change, regenerate a fixture with
  `python3 tests/make_gold.py <doc>` and review its diff against the PDF.
- `python3 audit_minutes.py` -- invariant checks over every council document;
  only flags not in `audit_allowlist.json` (verified quirks of the source
  PDFs, each with a reason) fail.
- `python3 check_regression.py` -- compares `web/public/data.json` with the
  committed version; final meetings may not disappear or change.

The daily GitHub Action runs all three after `./update_data.sh` and only
commits `data.json` if they pass.

## What you'll get either way

Per Ontario procedure, only a subset of agenda items get a *named* recorded
vote (when a councillor requests one, or for declared conflicts / contested
appointments). Everything else just shows "Carried" or "Defeated" with no
individual breakdown — that's a limit of the source data, not the scraper.
So `votes_rollup.csv` will have full mover/seconder/outcome for every item,
but per-councillor columns populated only for the subset with recorded votes.
