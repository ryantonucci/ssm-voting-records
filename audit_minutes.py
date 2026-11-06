#!/usr/bin/env python3
"""
Deterministic sanity checks over parsed/*.json (City Council documents only).

Instead of eyeballing every meeting, this flags items whose parse looks
wrong -- text from one item bleeding into another, procedural motions
landing on a sub-item, page furniture inside resolution text, by-law
numbers attached to the wrong item, impossible names, vote tables that
don't add up -- so only those need checking against the PDF.

Each flag has a stable key "CODE|source_file|item_number". Flags that were
checked and turned out to be genuine quirks of the source PDF are listed,
with the reason, in audit_allowlist.json; only flags NOT in that list count
as failures.

Usage:
    python3 audit_minutes.py                 # report, exit 1 on new errors
    python3 audit_minutes.py --json out.json # also write a machine-readable report
    python3 audit_minutes.py --all           # also print allowlisted flags

Exit status: 0 = no new error-level flags, 1 = new flags found.
"""

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PARSED_DIR = PROJECT_ROOT / "parsed"
TERMS_FILE = PROJECT_ROOT / "council_terms.json"
ALLOWLIST_FILE = PROJECT_ROOT / "audit_allowlist.json"

# Severity per flag code. "error" flags fail the run unless allowlisted;
# "warn" flags are printed but never fail it (they're frequently genuine).
SEVERITY = {
    "NO_ITEMS": "error",
    "AGENDA_TOO_LONG": "error",
    "NUM_DUP": "error",
    "NUM_ORPHAN": "error",
    "NUM_GAP": "warn",
    "NUM_REUSED": "warn",
    "TEXT_HAS_MOTION_LINE": "error",
    "TEXT_HAS_PAGE_FURNITURE": "error",
    "TEXT_HAS_VOTE_TABLE": "error",
    "TITLE_HAS_PAGE_FURNITURE": "error",
    "TITLE_TOO_LONG": "error",
    "TEXT_TOO_LONG": "warn",
    "PROCEDURAL_IN_SUBITEM": "error",
    "BYLAW_TITLE_NOT_ENACTED": "error",
    "BYLAW_TEXT_MISMATCH": "error",
    "BYLAW_DUP_OWNER": "error",
    "MOVER_NO_OUTCOME": "error",
    "OUTCOME_NO_MOVER": "error",
    "MOVER_NO_SECONDER": "error",
    "TEXT_EMPTY": "error",
    "MOVER_EQ_SECONDER": "error",
    "UNKNOWN_NAME": "error",
    "VOTE_ROSTER": "error",
    "VOTE_RESULTS_MISMATCH": "error",
    "VOTE_OUTCOME_MISMATCH": "error",
    "AGENDA_MINUTES_TITLE": "warn",
}

# Running page headers / footers that leaked into text: "Page 25 of 500",
# or "September 22, 2025 Council Minutes" when not part of a sentence
# ("... appear on the August 28, 2023 Council Agenda" is legitimate).
PAGE_FURNITURE_RE = re.compile(
    r"Page \d+ of \d+|(?<!the )(?<!date )(?<!of )(?<!on )\b(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December) \d{1,2}, \d{4} (?:Council |Budget |Special )*(?:Meeting )?"
    r"(?:Minutes|Agenda)\b(?! item)"
)
MOTION_LINE_RE = re.compile(r"\b(?:Moved by|Seconded by):|\bMover Councillor\b|\bSeconder Councillor\b")
VOTE_TABLE_RE = re.compile(r"For Against Conflict Absent|\bResults \d+ \d+ \d+ \d+\b")
PROCEDURAL_RE = re.compile(
    r"^(?:Resolved that )?(?:the Agenda for .* be approved|the Minutes of .* be approved|"
    r"this Council now adjourn|all the items listed under date|all By-laws under item)",
    re.IGNORECASE,
)
BYLAW_TITLE_RE = re.compile(r"^By-?laws?\s+(\d{4}-\d+)", re.IGNORECASE)
BYLAW_ANY_RE = re.compile(r"\d{4}-\d+")


def load_rosters():
    terms = json.loads(TERMS_FILE.read_text())["terms"]
    terms.sort(key=lambda t: t["start"])
    return terms


def roster_for(terms, date):
    names = None
    for t in terms:
        if date and date >= t["start"]:
            names = [c["name"] for c in t["councillors"]]
    if names is None:
        names = [c["name"] for c in terms[0]["councillors"]]
    return set(names)


def audit_doc(doc, terms):
    flags = []
    src = doc["source_file"]
    items = doc["items"]
    is_minutes = doc["document_type"] == "minutes"
    roster = roster_for(terms, doc.get("meeting_date"))
    roster_with_mayor = roster | {"Mayor M. Shoemaker"}

    def flag(code, item, detail):
        num = item["item_number"] if item else "-"
        flags.append(
            {
                "key": f"{code}|{src}|{num}",
                "code": code,
                "severity": SEVERITY[code],
                "source_file": src,
                "meeting_date": doc.get("meeting_date"),
                "item_number": num,
                "title": (item or {}).get("title", "")[:100],
                "detail": detail,
            }
        )

    if not items:
        flag("NO_ITEMS", None, "no agenda items parsed")
        return flags
    pages = doc.get("pages") or [1, 1]
    if doc["document_type"] != "minutes" and pages[1] - pages[0] > 40:
        flag("AGENDA_TOO_LONG", None, f"agenda segment spans pages {pages[0]}-{pages[1]}")

    numbers = [it["item_number"] for it in items]
    base_numbers = [n.split(" ")[0] for n in numbers]
    counts = Counter(numbers)
    for n, c in counts.items():
        if c > 1:
            flag("NUM_DUP", {"item_number": n, "title": ""}, f"item number appears {c} times")
    for it in items:
        if it.get("number_in_source"):
            flag("NUM_REUSED", it, f"source reuses item number {it['number_in_source']}; kept as {it['item_number']}")
    present = set(base_numbers)
    for it in items:
        parts = it["item_number"].split(" ")[0].split(".")
        if len(parts) >= 3 and ".".join(parts[:-1]) not in present:
            flag("NUM_ORPHAN", it, f"parent {'.'.join(parts[:-1])} missing")
    siblings = defaultdict(list)
    for n in present:
        parts = n.split(".")
        if len(parts) >= 2:
            siblings[".".join(parts[:-1])].append(int(parts[-1]))
    for parent, kids in siblings.items():
        kids = sorted(kids)
        missing = sorted(set(range(1, kids[-1] + 1)) - set(kids))
        if missing:
            flag("NUM_GAP", {"item_number": parent, "title": ""},
                 f"sub-items {', '.join(parent + '.' + str(m) for m in missing)} missing")

    enacted_owner = defaultdict(list)
    texts = [len(it.get("resolution_text") or "") for it in items if it.get("resolution_text")]
    median = sorted(texts)[len(texts) // 2] if texts else 0

    for it in items:
        title = it["title"]
        text = it.get("resolution_text") or ""
        num = it["item_number"]
        is_top = "." not in num

        if MOTION_LINE_RE.search(text):
            flag("TEXT_HAS_MOTION_LINE", it, MOTION_LINE_RE.search(text).group(0))
        if PAGE_FURNITURE_RE.search(text):
            flag("TEXT_HAS_PAGE_FURNITURE", it, PAGE_FURNITURE_RE.search(text).group(0))
        if VOTE_TABLE_RE.search(text):
            flag("TEXT_HAS_VOTE_TABLE", it, VOTE_TABLE_RE.search(text).group(0))
        if PAGE_FURNITURE_RE.search(title) or MOTION_LINE_RE.search(title):
            flag("TITLE_HAS_PAGE_FURNITURE", it, title[:80])
        if len(title) > 300:
            flag("TITLE_TOO_LONG", it, f"{len(title)} chars")
        if len(text) > 8000 or (median and len(text) > 15 * median and len(text) > 3000):
            flag("TEXT_TOO_LONG", it, f"{len(text)} chars (median {median})")
        # A block motion is fine on the sub-section it names ("all By-laws
        # under item 12.1 ..." on item 12.1).
        if not is_top and PROCEDURAL_RE.search(text) and not re.search(rf"\bitems? {re.escape(num)}\b", text):
            flag("PROCEDURAL_IN_SUBITEM", it, text[:80])

        tm = BYLAW_TITLE_RE.match(title)
        if tm and tm.group(1) not in it["bylaw_numbers"]:
            flag("BYLAW_TITLE_NOT_ENACTED", it, f"title by-law {tm.group(1)} not in {it['bylaw_numbers']}")
        if tm and text and tm.group(1) not in text.replace(" ", ""):
            flag("BYLAW_TEXT_MISMATCH", it, f"text does not mention {tm.group(1)}")
        for b in it["bylaw_numbers"]:
            enacted_owner[b].append(num)

        mover, seconder, outcome = it.get("mover"), it.get("seconder"), it.get("outcome")
        if is_minutes:
            if mover and not outcome:
                flag("MOVER_NO_OUTCOME", it, f"moved by {mover} but no outcome")
            if outcome and not mover and outcome != "Not Dealt With":
                flag("OUTCOME_NO_MOVER", it, f"{outcome} but no mover")
            if mover and not text:
                flag("TEXT_EMPTY", it, "motion has a mover but no resolution text")
        if mover and not seconder:
            flag("MOVER_NO_SECONDER", it, f"moved by {mover}, no seconder")
        if mover and mover == seconder:
            flag("MOVER_EQ_SECONDER", it, mover)

        for mo in it.get("motions", []):
            for role in ("mover", "seconder"):
                name = mo.get(role)
                if name and name not in roster:
                    flag("UNKNOWN_NAME", it, f"{mo['kind']} {role} {name!r} not on the roster")
            rv = mo.get("recorded_vote")
            if rv:
                votes = rv["votes"]
                names = set(votes)
                if names != roster_with_mayor:
                    extra = sorted(names - roster_with_mayor)
                    missing = sorted(roster_with_mayor - names)
                    flag("VOTE_ROSTER", it, f"{mo['kind']}: extra {extra} missing {missing}")
                tally = Counter(v for v in votes.values() if v)
                res = rv.get("results") or {}
                if res and any(tally.get(k, 0) != res.get(k, 0) for k in ("for", "against", "conflict", "absent")):
                    flag("VOTE_RESULTS_MISMATCH", it, f"{mo['kind']}: marks {dict(tally)} vs results {res}")
                if mo.get("outcome") in ("Carried", "Defeated") and res:
                    passed = res.get("for", 0) > res.get("against", 0)
                    if passed != (mo["outcome"] == "Carried"):
                        flag("VOTE_OUTCOME_MISMATCH", it, f"{mo['kind']}: {res} but {mo['outcome']}")

    for b, owners in enacted_owner.items():
        if len(owners) > 1:
            flag("BYLAW_DUP_OWNER", {"item_number": owners[0], "title": ""},
                 f"by-law {b} enacted by items {owners}")
    return flags


def audit_pairs(docs):
    """Agenda vs minutes for the same meeting: an item number whose title
    differs a lot usually means one of the two parses split items wrongly."""
    flags = []
    by_date = defaultdict(dict)
    for d in docs:
        if d.get("meeting_date") and d.get("meeting_type"):
            by_date[(d["meeting_date"], d["meeting_type"])].setdefault(d["document_type"], d)
    for (date, _), group in by_date.items():
        if "agenda" not in group or "minutes" not in group:
            continue
        a = {it["item_number"]: it["title"] for it in group["agenda"]["items"]}
        for it in group["minutes"]["items"]:
            other = a.get(it["item_number"])
            if other is None:
                continue
            ratio = difflib.SequenceMatcher(None, other.lower()[:80], it["title"].lower()[:80]).ratio()
            if ratio < 0.5:
                src = group["minutes"]["source_file"]
                flags.append(
                    {
                        "key": f"AGENDA_MINUTES_TITLE|{src}|{it['item_number']}",
                        "code": "AGENDA_MINUTES_TITLE",
                        "severity": SEVERITY["AGENDA_MINUTES_TITLE"],
                        "source_file": src,
                        "meeting_date": date,
                        "item_number": it["item_number"],
                        "title": it["title"][:100],
                        "detail": f"agenda title: {other[:80]!r}",
                    }
                )
    return flags


def load_docs():
    docs = []
    for f in sorted(PARSED_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        if d.get("meeting_type"):  # City Council documents only
            docs.append(d)
    return docs


def run_audit():
    terms = load_rosters()
    docs = load_docs()
    flags = []
    for d in docs:
        flags.extend(audit_doc(d, terms))
    flags.extend(audit_pairs(docs))
    return docs, flags


def load_allowlist():
    if not ALLOWLIST_FILE.exists():
        return {}
    data = json.loads(ALLOWLIST_FILE.read_text())
    return {e["key"]: e.get("reason", "") for e in data.get("flags", [])}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", help="write the full report to this path")
    ap.add_argument("--all", action="store_true", help="also print allowlisted flags")
    args = ap.parse_args()

    docs, flags = run_audit()
    allow = load_allowlist()
    for f in flags:
        f["allowlisted"] = f["key"] in allow
        if f["allowlisted"]:
            f["allowlist_reason"] = allow[f["key"]]
    new_errors = [f for f in flags if f["severity"] == "error" and not f["allowlisted"]]
    warnings = [f for f in flags if f["severity"] == "warn" and not f["allowlisted"]]
    known = [f for f in flags if f["allowlisted"]]
    stale = sorted(set(allow) - {f["key"] for f in flags})

    n_items = sum(len(d["items"]) for d in docs)
    print(f"Audited {len(docs)} council documents, {n_items} items.")
    print(f"  new errors: {len(new_errors)}   warnings: {len(warnings)}   "
          f"known (allowlisted): {len(known)}   stale allowlist entries: {len(stale)}")
    by_code = Counter(f["code"] for f in flags if not f["allowlisted"])
    for code, n in sorted(by_code.items()):
        print(f"    {code:28s} {n:4d}  ({SEVERITY[code]})")

    def show(title, rows):
        if not rows:
            return
        print(f"\n{title}")
        for f in rows:
            print(f"  [{f['code']}] {f['meeting_date']} {f['source_file'][:60]} item {f['item_number']}: "
                  f"{f['detail']}" + (f"  -- {f['title'][:50]}" if f['title'] else ""))

    show("NEW ERRORS (fix the parser, or allowlist with a reason in audit_allowlist.json):", new_errors)
    show("Warnings:", warnings)
    if args.all:
        show("Allowlisted:", known)
    if stale:
        print("\nAllowlist entries that no longer fire (can be removed):")
        for k in stale:
            print(f"  {k}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"new_errors": new_errors, "warnings": warnings, "allowlisted": known, "stale_allowlist": stale},
            indent=2))
    return 1 if new_errors else 0


if __name__ == "__main__":
    sys.exit(main())
