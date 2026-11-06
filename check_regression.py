#!/usr/bin/env python3
"""
Compares a freshly built web/public/data.json against the last known-good
one (by default the version committed at HEAD) and fails if published,
final data got worse:

  * the number of meetings, or of final (non-pending) items, went down;
  * a meeting that was already final (from minutes) disappeared, or any of
    its rows changed: a different mover/seconder, a different outcome, a row
    gone or a new row added;
  * a member's count of final rows went down.

Expected changes are allowed: agenda-only "Pending" rows being replaced by
minutes outcomes, pending rows changing while still pending, and new
meetings being added.

Usage:
    python3 check_regression.py                        # baseline = git HEAD
    python3 check_regression.py --baseline old.json    # explicit baseline
    ALLOW_DATA_REGRESSION=1 python3 check_regression.py  # report only

Exit status 0 = OK (or overridden), 1 = regression found.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_FILE = PROJECT_ROOT / "web" / "public" / "data.json"
DATA_REL = "web/public/data.json"


def load_baseline(path):
    if path:
        return json.loads(Path(path).read_text())
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{DATA_REL}"], cwd=PROJECT_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return json.loads(out)


def members(term):
    """All people with rows in a term: councillors plus the mayor card."""
    people = list(term.get("councillors", []))
    if term.get("mayor"):
        people.append(term["mayor"])
    return people


def rows_by_date(data):
    """{date: {(term, number, role, name): result}} for final rows, plus the
    set of dates that have any pending row."""
    final = defaultdict(dict)
    pending_dates = set()
    for term in data["terms"]:
        for person in members(term):
            for r in person.get("items", []):
                if r.get("pending"):
                    pending_dates.add(r["date"])
                    continue
                final[r["date"]][(term["term"], r["number"], r["role"], person["name"])] = r["result"]
    return final, pending_dates


def final_counts(data):
    counts = {}
    for term in data["terms"]:
        for person in members(term):
            n = sum(1 for r in person.get("items", []) if not r.get("pending"))
            counts[(term["term"], person["name"])] = n
    return counts


def compare(old, new):
    problems = []

    def total(data, key):
        return sum(t.get(key, 0) or 0 for t in data["terms"])

    old_meetings, new_meetings = total(old, "meetingCount"), total(new, "meetingCount")
    if new_meetings < old_meetings:
        problems.append(f"meeting count dropped: {old_meetings} -> {new_meetings}")
    old_final = total(old, "itemCount") - total(old, "pendingCount")
    new_final = total(new, "itemCount") - total(new, "pendingCount")
    if new_final < old_final:
        problems.append(f"final (non-pending) item count dropped: {old_final} -> {new_final}")

    old_rows, _ = rows_by_date(old)
    new_rows, _ = rows_by_date(new)
    for date in sorted(old_rows):
        before, after = old_rows[date], new_rows.get(date)
        if not after:
            problems.append(f"{date}: final meeting disappeared ({len(before)} rows)")
            continue
        if before == after:
            continue
        for key in sorted(set(before) | set(after)):
            term, number, role, name = key
            if key not in after:
                problems.append(f"{date} item {number}: {role} {name} ({before[key]}) is gone")
            elif key not in before:
                problems.append(f"{date} item {number}: new final row {role} {name} ({after[key]})")
            elif before[key] != after[key]:
                problems.append(f"{date} item {number}: outcome {before[key]} -> {after[key]}")

    old_counts, new_counts = final_counts(old), final_counts(new)
    for key, n in sorted(old_counts.items()):
        m = new_counts.get(key, 0)
        if m < n:
            problems.append(f"{key[1]} ({key[0]}): final row count dropped {n} -> {m}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--baseline", help="last known-good data.json (default: git HEAD)")
    ap.add_argument("--new", default=str(DATA_FILE), help="freshly built data.json")
    args = ap.parse_args()

    old = load_baseline(args.baseline)
    if old is None:
        print("No baseline data.json found -- nothing to compare against.")
        return 0
    new = json.loads(Path(args.new).read_text())
    problems = compare(old, new)
    if not problems:
        print("Regression check passed: no final data was lost or changed.")
        return 0
    print(f"Regression check found {len(problems)} problem(s):")
    for p in problems[:200]:
        print(f"  {p}")
    if os.environ.get("ALLOW_DATA_REGRESSION") == "1":
        print("ALLOW_DATA_REGRESSION=1 set -- not failing.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
