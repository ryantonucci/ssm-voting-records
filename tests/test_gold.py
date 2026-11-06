#!/usr/bin/env python3
"""Gold-set regression test: the parser's output for a set of hand-verified
meetings must match tests/gold/*.json exactly (item numbers, titles,
mover/seconder/outcome, enacted by-laws, resolution text boundaries,
recorded-vote tallies, and every motion within each item).

Reads parsed/ (so run 2_parse_minutes.py first); takes well under a second.

    python3 -m pytest tests/        # with pytest
    python3 tests/test_gold.py      # without
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gold_common import GOLD_DIR, GOLD_DOCS, load_parsed, summarize  # noqa: E402


def compare(stem):
    """Returns a list of human-readable mismatches for one gold meeting."""
    gold = json.loads((GOLD_DIR / f"{stem}.json").read_text())
    data = load_parsed(stem)
    if data is None:
        return [f"{stem}: parsed/{stem}.json missing (meeting disappeared?)"]
    problems = []
    got = {it["item_number"]: summarize(it) for it in data["items"]}
    want = {it["item_number"]: it for it in gold["items"]}
    for num in want:
        if num not in got:
            problems.append(f"{stem} item {num}: missing")
            continue
        for field, value in want[num].items():
            if got[num][field] != value:
                problems.append(f"{stem} item {num} {field}: expected {value!r}, got {got[num][field]!r}")
    for num in got:
        if num not in want:
            problems.append(f"{stem} item {num}: unexpected extra item {got[num]['title'][:60]!r}")
    if [i["item_number"] for i in data["items"]] != [i["item_number"] for i in gold["items"]] and not problems:
        problems.append(f"{stem}: item order differs")
    return problems


def test_gold_set():
    problems = [p for stem in GOLD_DOCS for p in compare(stem)]
    assert not problems, "\n".join(problems[:50])


def main():
    total = checked = 0
    problems = []
    for stem in GOLD_DOCS:
        gold = json.loads((GOLD_DIR / f"{stem}.json").read_text())
        total += len(gold["items"])
        p = compare(stem)
        problems += p
        checked += 1
    for p in problems[:100]:
        print("  " + p)
    print(f"Gold set: {checked} meetings, {total} items, {len(problems)} mismatches.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
