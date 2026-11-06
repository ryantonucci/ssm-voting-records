#!/usr/bin/env python3
"""Writes tests/gold/<doc>.json from the current parsed/ output.

Only for (re)creating a fixture: a freshly written fixture is NOT gold until
every item in it has been checked against the PDF by a person. When the
parser changes on purpose, re-run this for the affected meeting, review the
`git diff` of the fixture line by line against the PDF, and commit it.

    python3 tests/make_gold.py              # all GOLD_DOCS
    python3 tests/make_gold.py <doc-stem>   # one
"""

import json
import sys

from gold_common import GOLD_DIR, GOLD_DOCS, load_parsed, summarize


def main():
    stems = sys.argv[1:] or GOLD_DOCS
    GOLD_DIR.mkdir(exist_ok=True)
    for stem in stems:
        data = load_parsed(stem)
        if data is None:
            print(f"! parsed/{stem}.json not found -- run 2_parse_minutes.py first")
            continue
        out = {
            "source_file": data["source_file"],
            "meeting_date": data["meeting_date"],
            "items": [summarize(it) for it in data["items"]],
        }
        (GOLD_DIR / f"{stem}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote tests/gold/{stem}.json ({len(out['items'])} items)")


if __name__ == "__main__":
    main()
