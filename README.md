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

- **The parser** assumes minutes follow the layout I saw in the Sept 2025
  file: numbered item headers ("12.1.2 By-law..."), "Moved by:" / "Seconded
  by:" lines, a bare "Carried"/"Defeated" line, and — when a recorded vote
  happens — a bordered table with a For/Against/Conflict/Absent header row.
  Older minutes (pre-2023ish) or committee-of-the-whole sections may be
  formatted slightly differently. The script prints its progress as it goes
  so you can see which meetings parsed cleanly and which didn't.

- **Vote-table-to-item matching** is a heuristic (matches vote tables to
  items in document order). It worked correctly on the sample I inspected,
  but spot-check a handful of outputs against the source PDF before trusting
  the full rollup, especially for meetings with multiple recorded votes.

## What you'll get either way

Per Ontario procedure, only a subset of agenda items get a *named* recorded
vote (when a councillor requests one, or for declared conflicts / contested
appointments). Everything else just shows "Carried" or "Defeated" with no
individual breakdown — that's a limit of the source data, not the scraper.
So `votes_rollup.csv` will have full mover/seconder/outcome for every item,
but per-councillor columns populated only for the subset with recorded votes.
