#!/usr/bin/env python3
"""
Layout-aware parser for Sault Ste. Marie City Council minutes / agenda PDFs.

This is the single source of truth for how a PDF is split into agenda items
and motions. Both 2_parse_minutes.py (which writes parsed/*.json) and, via
those JSON files, export_dashboard_data.py (resolution text for the
dashboard) use it, so item boundaries can't drift between two different
regex walkers again.

Why layout-aware: plain extract_text() loses the information that actually
distinguishes an agenda item header from body text. In every council
minutes/agenda format 2022-2026, item headers start at the page's left
margin (x ~= 36pt in minutes, ~24pt in agendas) while everything else --
resolution text, numbered lists inside a resolution, the "Present:" block,
recorded-vote tables -- is indented. Using that x position:

  * a numbered list inside a resolution ("1. The Council of ...") can no
    longer end the item early,
  * an item title that begins with a digit ("7.2 2025 City Credit Rating")
    is still recognised as a header (the old regex required a capital
    letter, so such items were silently merged into the previous one),
  * top-level sections ("5. Approve Agenda as Presented", "7. ... Consent
    Agenda", "12. Consideration and Passing of By-laws") are real items with
    their own motions, instead of having their mover/seconder overwrite the
    preceding sub-item.

Other layout facts used here:
  * running page headers ("September 22, 2025 Council Minutes") and footers
    (page numbers, "Page 25 of 500") are dropped by position + pattern;
  * recorded-vote tables are borderless text tables; they are parsed from
    character x positions (which column each "X" sits under) and attached
    to the motion that is open at that point in the document, rather than
    being matched to items by order afterwards;
  * an item may carry several motions (main motion, "Amendment:", budget
    amendments, a motion to refer ...). Each is kept in item["motions"]; the
    item-level mover/seconder/outcome come from the main motion (the first
    one not labelled as an amendment) instead of whichever came last;
  * merged agenda packages (500+ pages) contain the agenda itself, then all
    attachments -- including the previous meeting's minutes. Only the agenda
    pages (up to its Adjournment item) are parsed as the agenda; minutes
    found immediately after are returned separately as their own documents
    (see parse_pdf()).
"""

import re
from collections import Counter

import pdfplumber

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# "7.4 Title", "12.1.2 By-law 2025-123 ...", "5. Approve Agenda", "8.8.1.1 X"
ITEM_NUM_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})(\.?)\s+(\S.*)$")
TOP_LEVEL_RE = re.compile(r"^\d{1,2}\.\s+\S")

MOVED_BY_RE = re.compile(r"^(?:Moved by|Mover)\b:?\s*(.*)$", re.IGNORECASE)
SECONDED_BY_RE = re.compile(r"^(?:Seconded by|Seconder)\b:?\s*(.*)$", re.IGNORECASE)
# Mover and seconder occasionally come out of the PDF glued onto one line:
# "Councillor M. ScottSeconded by: Councillor L. Vezeau-Allen".
GLUED_SECONDER_RE = re.compile(r"\s*Seconded by:?\s*", re.IGNORECASE)

OUTCOME_RE = re.compile(
    r"^(Carried(?: as amended)?|Carrie|Defeated|Tied,?\s*Defeated|Lost|Postponed|Deferred|Tabled|"
    r"Officially Read and Not Dealt With|Not Dealt With\b.*|Not Read|Withdrawn\b.*)[\s.\\]*$",
    re.IGNORECASE,
)

# Short (usually bold) whole-line labels that introduce a motion other than
# the first/main one within an item.
MOTION_LABEL_RE = re.compile(
    r"^(?:(?:First |Second |Third |Proposed )?Amendment|Amending Motion|Amendment to (?:the )?(?:Main )?Motion|"
    r"Motion to (?:Refer|Defer|Table|Postpone|Amend)|Referral(?: Motion)?|Deferral(?: Motion)?|Postponement|"
    r"(?:Main )?Motion as Amended|Amended (?:Main )?Motion|Main Motion)\s*:?\s*$",
    re.IGNORECASE,
)


def label_kind(label):
    """Motion kind for a MOTION_LABEL_RE label."""
    low = label.lower()
    if "as amended" in low or low.startswith("amended") or low.startswith("main motion"):
        return "main_as_amended"
    if "amend" in low:
        return "amendment"
    return "procedural"


# Lines that start an item's body, never a wrapped title.
BODY_START_RE = re.compile(
    r"^(?:The report of|A report of|The relevant By-?laws?|Correspondence from|"
    r"(?:Mayor|Councillor) [A-Z]\. [\w-]+ declared)", re.IGNORECASE
)
SIGNATURE_LABEL_RE = re.compile(r"^(?:Mayor|City Clerk|Deputy City Clerk|Clerk)$")
# A first motion that is only procedural (suspending the rules so someone
# can speak) when a substantive motion follows in the same item.
PROCEDURAL_MOTION_RE = re.compile(r"\bsuspend the rules\b", re.IGNORECASE)
SUBSTITUTED_RE = re.compile(r"\s*The following motion was substituted for the original\.?\s*$", re.IGNORECASE)
DEFERRED_NOTE_RE = re.compile(r"\((?:deferred|postponed) to [^)]*\)\.?$", re.IGNORECASE)


# A motion with no "Moved by" (agenda drafts, some committee-of-the-whole
# motions) still starts with one of these.
RESOLUTION_START_RE = re.compile(
    r"^(Resolved\b|Be It Resolved|Now Therefore|Whereas\b|Further Be It Resolved)", re.IGNORECASE
)

BYLAW_RE = re.compile(r"\bBy-?laws?\s+((?:\d{4}-\d+)(?:\s*(?:,|and|&)\s*(?:By-?laws?\s+)?\d{4}-\d+)*)", re.IGNORECASE)
BYLAW_NUM_RE = re.compile(r"\d{4}-\d+")
# By-laws an item actually enacts: "By-law 2025-128 being a by-law ...",
# "By-laws 2025-141 and 2025-142 be passed ...", or an item whose title is
# "By-law 2025-128 (...)". Everything else ("The relevant By-law 2025-128 is
# listed under item 12", "to amend By-law 2024-171", "save and except
# By-law 2025-140") is only a reference.
ENACTING_TAIL_RE = re.compile(
    r"^\s*(?:\([^)]*\)\s*)?(?:being\b|be\s+(?:passed|read|approved|adopted|enacted)|is\s+(?:hereby\s+)?(?:passed|enacted))",
    re.IGNORECASE,
)

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
RUNNING_HEADER_RE = re.compile(
    rf"^(?:{MONTHS})\s+\d{{1,2}},\s+\d{{4}}\b.*\b(?:Minutes|Agenda|Minute)s?\b", re.IGNORECASE
)
FOOTER_RE = re.compile(r"^(?:\d{1,3}\s+)?(?:Page\s+\d+\s+of\s+\d+)?(?:\s+.*(?:Minutes|Agenda))?$|^\d{1,3}$")
PAGE_OF_RE = re.compile(r"Page\s+\d+\s+of\s+\d+")
SIGNATURE_RE = re.compile(r"^_{5,}$")

TITLE_PAGE_RANGE_RE = re.compile(r"\s+\d+\s*[-–]\s*\d+\s*$")

VOTE_COLUMNS = ("for", "against", "conflict", "absent")
VOTE_HEADER_RE = re.compile(r"^For\s+Against\s+Conflict\s+Absent$", re.IGNORECASE)

MEETING_TYPE_RE = re.compile(
    r"(Inaugural|Regular|Special|Budget)\s+Meeting\s+of\s+City\s+Council", re.IGNORECASE
)
MEETING_DATE_RE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    rf"({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b"
)
MONTH_NAME_TO_NUM = {m.lower(): i for i, m in enumerate(MONTHS.split("|"), start=1)}

# Canonical spellings for mover/seconder names that appear mangled in a few
# PDFs. Keys are compared after whitespace normalisation.
NAME_FIXES = {
    "Councillor M Bruni": "Councillor M. Bruni",
    "Coun. A. Caputo": "Councillor A. Caputo",
    "Coun. L. Vezeau-Allen": "Councillor L. Vezeau-Allen",
    # vote-table typo in the December 12, 2022 minutes
    "Councillor M. Shoemaker": "Mayor M. Shoemaker",
}


# ---------------------------------------------------------------------------
# Page-level helpers
# ---------------------------------------------------------------------------

def extract_meeting_type(text):
    """'Regular' / 'Special' / 'Budget' / 'Inaugural' for a City Council
    document (from the heading on its first page), else None."""
    m = MEETING_TYPE_RE.search(text[:300])
    return m.group(1).capitalize() if m else None


def extract_meeting_date(text):
    """'YYYY-MM-DD' from the first weekday-date near the top, else None."""
    m = MEETING_DATE_RE.search(text[:1500])
    if not m:
        return None
    month_name, day, year = m.groups()
    return f"{int(year):04d}-{MONTH_NAME_TO_NUM[month_name.lower()]:02d}-{int(day):02d}"


def is_minutes_start(text):
    """True if a page is the first page of a City Council minutes document."""
    head = text[:400]
    return bool(MEETING_TYPE_RE.search(head)) and bool(re.search(r"^\s*MINUTES\s*$", head, re.M | re.I))


def _words_from_chars(chars):
    """Groups a line's chars into words: [(text, x0, x1)]."""
    words = []
    cur, x0, x1 = "", None, None
    for c in sorted(chars, key=lambda c: c["x0"]):
        if c["text"].isspace():
            if cur:
                words.append((cur, x0, x1))
            cur, x0, x1 = "", None, None
            continue
        if cur and c["x0"] - x1 > 1.5:
            words.append((cur, x0, x1))
            cur, x0 = "", None
        if not cur:
            x0 = c["x0"]
        cur += c["text"]
        x1 = c["x1"]
    if cur:
        words.append((cur, x0, x1))
    return words


def _strip_right_page_range(line):
    """Agendas print the attachment's page range right-aligned after each
    item title ("8.3.1 Appointment of ... 5 - 8"). Drop it only when it is
    visually separated from the title (so a title that really ends in e.g.
    "2025 - 2026" is kept)."""
    text = line["text"]
    m = TITLE_PAGE_RANGE_RE.search(text)
    if not m:
        return text
    words = line["words"]
    tail = "".join(m.group(0).split())
    # The range is written "5 - 8" (3 words), "5 -8" (2) or "5-8" (1).
    for k in (3, 2, 1):
        if len(words) > k and "".join(w[0] for w in words[-k:]) == tail:
            gap = words[-k][1] - words[-k - 1][2]
            return text[: m.start()].rstrip() if gap > 20 else text
    return text


def read_lines(pdf, page_indices):
    """Returns the document's lines in reading order, each a dict with
    page, top, x0, size, bold, text and words; running headers, footers and
    signature rules are removed."""
    out = []
    for pi in page_indices:
        page = pdf.pages[pi]
        height = page.height
        for ln in page.extract_text_lines(return_chars=True):
            text = ln["text"].strip()
            if not text:
                continue
            chars = [c for c in ln["chars"] if not c["text"].isspace()]
            if not chars:
                continue
            top = ln["top"]
            if top < 62 and (RUNNING_HEADER_RE.match(text) or PAGE_OF_RE.search(text)):
                continue
            if top > height - 66 and (FOOTER_RE.match(text) or PAGE_OF_RE.search(text)):
                continue
            if SIGNATURE_RE.match(text):
                continue
            fonts = Counter(c.get("fontname", "") for c in chars)
            font = fonts.most_common(1)[0][0]
            out.append(
                {
                    "page": pi + 1,
                    "top": top,
                    "x0": ln["x0"],
                    "size": round(chars[0].get("size", 12), 1),
                    "font": font,
                    "bold": "bold" in font.lower(),
                    "text": text,
                    "words": _words_from_chars(chars),
                }
            )
    return out


def header_margin(lines):
    """The x position of item headers in this document. Headers sit at the
    left margin and everything else is indented, so this is the leftmost x
    shared by several numbered lines (numbered lists inside resolutions are
    indented further and can't win)."""
    xs = Counter(round(l["x0"] / 2) * 2 for l in lines if ITEM_NUM_RE.match(l["text"]))
    common = sorted(x for x, n in xs.items() if n >= 3)
    if common:
        return common[0]
    return min(xs) if xs else None


# ---------------------------------------------------------------------------
# Vote tables
# ---------------------------------------------------------------------------

def _vote_columns(line):
    cols = {}
    for text, x0, x1 in line["words"]:
        key = text.lower()
        if key in VOTE_COLUMNS:
            cols[key] = (x0 + x1) / 2
    return cols if len(cols) == 4 else None


def _nearest_column(cols, x):
    return min(cols, key=lambda k: abs(cols[k] - x))


class VoteTable:
    def __init__(self, cols, page, top):
        self.cols = cols
        self.page = page
        self.top = top
        self.rows = []  # [name, choice]
        self.results = None
        self.name_x1 = min(cols.values()) - 25

    def feed(self, line):
        """Consumes one line. Returns False when the table has ended (the
        line is not part of it)."""
        words = line["words"]
        if VOTE_HEADER_RE.match(line["text"]):
            return True  # header repeated after a page break -- same table
        if words and words[0][0].lower() == "results":
            nums = [w for w in words[1:] if w[0].isdigit()]
            self.results = {_nearest_column(self.cols, (w[1] + w[2]) / 2): int(w[0]) for w in nums}
            return "done"
        name_words = [w for w in words if w[2] <= self.name_x1 + 20 and not (w[0].upper() == "X" and w[1] > self.name_x1)]
        marks = [w for w in words if w[0].upper() == "X" and w[1] > self.name_x1]
        if not name_words and not marks:
            return False
        if any(w[1] > self.name_x1 + 20 and w[0].upper() != "X" for w in words):
            return False  # ordinary text line -- table is over
        name = " ".join(w[0] for w in name_words)
        choice = _nearest_column(self.cols, (marks[0][1] + marks[0][2]) / 2) if marks else None
        if marks or not self.rows:
            self.rows.append([name, choice])
        else:
            # wrapped name ("Councillor S." / "Hollingsworth")
            self.rows[-1][0] = join_lines([self.rows[-1][0], name])
        return True

    def as_dict(self):
        votes = {}
        for name, choice in self.rows:
            name = clean_name(name)
            if name:
                votes[name] = choice
        return {"votes": votes, "results": self.results, "page": self.page}


# ---------------------------------------------------------------------------
# Item / motion state machine
# ---------------------------------------------------------------------------

def clean_name(raw):
    if raw is None:
        return None
    name = re.sub(r"\s+", " ", raw).strip().rstrip(".,;")
    name = re.sub(r"^Councilor\b", "Councillor", name)
    name = NAME_FIXES.get(name, name)
    return name or None


def join_lines(lines):
    """Joins wrapped lines, re-attaching words hyphen-split across a line
    break ("By-law 2005-" + "150", "Vezeau-" + "Allen")."""
    out = ""
    for s in lines:
        if not out:
            out = s
        elif out.endswith("-") and s[:1].isalnum():
            out += s
        else:
            out += " " + s
    return out.strip()


def _new_item(number, title_line, page):
    return {
        "item_number": number,
        "_title_lines": [title_line],
        "_page": page,
        "motions": [],
        "_notes": [],
    }


def _new_motion(kind, page):
    return {
        "kind": kind,
        "mover": None,
        "seconder": None,
        "_text": [],
        "outcome": None,
        "recorded_vote": None,
        "page": page,
    }


def bylaw_mentions(text):
    """All by-law numbers mentioned in text, with whether each mention is
    enacting (the by-law is the subject of the motion) or a reference."""
    found = []
    for m in BYLAW_RE.finditer(text):
        nums = BYLAW_NUM_RE.findall(m.group(1))
        # Enacting only when the by-law is the grammatical subject
        # ("Resolved that By-law X being a by-law ... be passed"), not
        # "to amend Schedule A to By-law X being a by-law ..." or "save and
        # except By-law X be approved".
        before = text[max(0, m.start() - 12):m.start()]
        subject = m.start() == 0 or re.search(r"\bthat\s*$", before, re.IGNORECASE)
        enacting = bool(subject and ENACTING_TAIL_RE.match(text[m.end():]))
        for n in nums:
            found.append((n, enacting))
    return found


def _finish_item(item, doc_type):
    title = join_lines(item.pop("_title_lines"))
    item["title"] = title
    notes = item.pop("_notes")
    item.pop("_page", None)
    for mo in item["motions"]:
        mo["text"] = join_lines(mo.pop("_text"))
        mo["mover"] = clean_name(mo["mover"])
        mo["seconder"] = clean_name(mo["seconder"])

    motions = item["motions"]
    if len(motions) > 1 and motions[0]["kind"] == "main" and PROCEDURAL_MOTION_RE.search(motions[0]["text"]):
        motions[0]["kind"] = "procedural"
        nxt = next((m for m in motions[1:] if m["kind"] == "additional"), None)
        if nxt:
            nxt["kind"] = "main"
    # Resolution text printed before the actual motion (e.g. shareholder
    # resolutions quoted ahead of "Moved by ... that Council meet as
    # shareholder"): the first motion somebody moved is the main one.
    first = next((m for m in motions if m["kind"] == "main"), None)
    if first and not first["mover"] and not first["seconder"]:
        moved = next((m for m in motions if m["kind"] == "additional" and (m["mover"] or m["seconder"])), None)
        if moved:
            first["kind"] = "text"
            moved["kind"] = "main"

    # "The following motion was substituted for the original." -- the next
    # motion replaces the main one and is what was voted on.
    main0 = next((m for m in motions if m["kind"] == "main"), None)
    if main0 and SUBSTITUTED_RE.search(main0["text"]):
        main0["text"] = SUBSTITUTED_RE.sub("", main0["text"]).strip()
        nxt = next((m for m in motions[motions.index(main0) + 1:] if m["kind"] == "additional"), None)
        if nxt:
            nxt["kind"] = "main_as_amended"

    # Unlabelled restatement of the main motion after an amendment carried
    # (same mover and seconder): that's the vote on the motion as amended.
    main0 = next((m for m in motions if m["kind"] == "main"), None)
    if main0 and main0["outcome"] is None and not any(m["kind"] == "main_as_amended" for m in motions):
        for m in motions[motions.index(main0) + 1:]:
            if (m["kind"] == "additional" and m["mover"] == main0["mover"]
                    and m["seconder"] == main0["seconder"]):
                m["kind"] = "main_as_amended"
                break
    for mo in motions:
        if mo["outcome"] is None and DEFERRED_NOTE_RE.search(mo["text"]):
            mo["outcome"] = "Postponed" if "postponed" in mo["text"][-60:].lower() else "Deferred"

    early = item.pop("_early_outcome", None)
    if early and motions and motions[0]["outcome"] is None:
        motions[0]["outcome"] = early

    # The item's mover/seconder are those of its main motion. When the main
    # motion was amended, the minutes record the final vote separately
    # ("Motion as Amended"); that vote is the item's outcome and its text the
    # item's final resolution.
    main = next((m for m in item["motions"] if m["kind"] == "main"), None)
    final = next((m for m in reversed(item["motions"]) if m["kind"] == "main_as_amended"), None)
    if main is None and final is not None:
        main = final
    final = final or main
    item["mover"] = main["mover"] if main else None
    item["seconder"] = main["seconder"] if main else None
    item["outcome"] = (final["outcome"] or main["outcome"]) if main else None
    item["resolution_text"] = (final["text"] or main["text"] or None) if main else None
    rv = (final["recorded_vote"] or main["recorded_vote"]) if main else None
    item["recorded_vote"] = rv["votes"] if rv else None

    enacted, refs = [], []
    tm = re.match(r"^By-?laws?\s+(\d{4}-\d+)", title, re.IGNORECASE)
    if tm:
        enacted.append(tm.group(1))
    for n, enacting in bylaw_mentions(title):
        (refs if n not in enacted else enacted).append(n)
    texts = [m["text"] for m in item["motions"] if m["kind"] in ("main", "main_as_amended")]
    for t in texts:
        for n, enacting in bylaw_mentions(t):
            # For a by-law item the number in its title is authoritative; a
            # different number in the motion text is a typo in the minutes
            # (e.g. "By-law 2022-2" under "By-law 2023-2 (Taxes)").
            (enacted if enacting and not tm else refs).append(n)
    other = [m["text"] for m in item["motions"] if m["kind"] not in ("main", "main_as_amended")] + [join_lines(notes)]
    for t in other:
        for n, _ in bylaw_mentions(t):
            refs.append(n)
    enacted = list(dict.fromkeys(enacted))
    refs = [n for n in dict.fromkeys(refs) if n not in enacted]
    item["bylaw_numbers"] = enacted
    item["bylaw_references"] = refs
    return item


def parse_lines(lines, doc_type):
    """Turns the line stream of one document into a list of items."""
    margin = header_margin(lines)
    # The font used for item headers in this document ("Arial-BoldMT", or an
    # opaque "F2" in older PDFs). Deeper sub-items are sometimes indented
    # ("8.8.2.1 Anti-Hate Committee" at the body indent) but keep this font.
    head_fonts = Counter(
        l["font"] for l in lines
        if margin is not None and abs(l["x0"] - margin) <= 8 and ITEM_NUM_RE.match(l["text"])
    )
    heading_font = head_fonts.most_common(1)[0][0] if head_fonts else None
    body_fonts = Counter(l["font"] for l in lines)
    if heading_font and body_fonts.most_common(1)[0][0] == heading_font:
        heading_font = None  # no visual distinction in this PDF

    def heading_style(ln):
        # Real font names vary within one PDF ("Arial-BoldMT", "Arial,Bold",
        # "Helvetica-Bold"); compare boldness when the name says so.
        if "bold" in heading_font.lower():
            return ln["bold"]
        return ln["font"] == heading_font

    items = []
    cur = None
    motion = None          # motion currently collecting (no outcome yet)
    collecting = False     # inside the motion's resolution text
    pending_kind = None    # label like "Amendment:" seen, waiting for Moved by
    title_mode = False
    prev = None
    table = None

    def close_motion():
        nonlocal motion, collecting
        motion = None
        collecting = False

    def start_motion(page):
        nonlocal motion, pending_kind
        if pending_kind:
            kind = pending_kind
        elif any(m["kind"] == "main" for m in cur["motions"]):
            kind = "additional"
        else:
            kind = "main"
        pending_kind = None
        motion = _new_motion(kind, page)
        cur["motions"].append(motion)
        return motion

    for ln in lines:
        s = ln["text"]

        # --- recorded vote table rows ------------------------------------
        if table is not None:
            r = table.feed(ln)
            if r is True:
                prev = ln
                continue
            target = motion or (cur["motions"][-1] if cur and cur["motions"] else None)
            if target is not None:
                target["recorded_vote"] = table.as_dict()
            table = None
            if r == "done":
                prev = ln
                continue
        if VOTE_HEADER_RE.match(s):
            cols = _vote_columns(ln)
            if cols:
                table = VoteTable(cols, ln["page"], ln["top"])
                collecting = False
                prev = ln
                continue

        # --- item headers --------------------------------------------------
        hm = ITEM_NUM_RE.match(s)
        at_margin = margin is None or abs(ln["x0"] - margin) <= 8
        if hm and not at_margin and cur and heading_font and heading_style(ln):
            at_margin = ln["x0"] - margin <= 80 and _plausible_child(hm.group(1), cur["item_number"])
        if hm and at_margin and heading_font and not heading_style(ln):
            at_margin = False  # e.g. a numbered list line that wrapped to the margin
        if hm and at_margin and not MOVED_BY_RE.match(s):
            number, dot, title = hm.groups()
            is_top = "." not in number
            # A top-level header needs its trailing period ("5. Approve");
            # sub-items never have one in these documents but tolerate it.
            # Some minutes number an amendment or the final vote as a
            # sub-item ("7.14.1 Proposed Amendment", "9.3.1 Motion as
            # Amended"). Those are motions of the parent item, not items.
            if (cur and number.startswith(cur["item_number"] + ".")
                    and MOTION_LABEL_RE.match(title)):
                close_motion()
                pending_kind = label_kind(title)
                prev = ln
                continue
            if (not is_top or dot) and int(number.split(".")[0]) <= 30:
                if cur:
                    items.append(_finish_item(cur, doc_type))
                cur = _new_item(number, title, ln["page"])
                if doc_type != "minutes":
                    # page ranges only appear in agendas
                    t = _strip_right_page_range(ln)
                    m2 = ITEM_NUM_RE.match(t)
                    cur["_title_lines"] = [m2.group(3) if m2 else title]
                close_motion()
                pending_kind = None
                title_mode = True
                prev = ln
                continue

        if cur is None:
            prev = ln
            continue

        # The signature block ("Mayor" / "City Clerk") ends the minutes.
        if (doc_type == "minutes" and SIGNATURE_LABEL_RE.match(s)
                and "adjourn" in cur["_title_lines"][0].lower()):
            break

        # --- wrapped title lines ------------------------------------------
        if title_mode:
            gap = ln["top"] - prev["top"] if prev and prev["page"] == ln["page"] else 99
            indented = margin is None or ln["x0"] > margin + 6
            known = (MOVED_BY_RE.match(s) or SECONDED_BY_RE.match(s) or OUTCOME_RE.match(s)
                     or RESOLUTION_START_RE.match(s) or MOTION_LABEL_RE.match(s)
                     or BODY_START_RE.match(s))
            # In PDFs with real bold fonts, a wrapped title is bold like
            # the header line; body text never is.
            style_break = heading_font is not None and not heading_style(ln)
            if gap <= 1.6 * ln["size"] and indented and not known and not style_break:
                t = _strip_right_page_range(ln) if doc_type != "minutes" else s
                cur["_title_lines"].append(t)
                prev = ln
                continue
            title_mode = False

        # --- motions ----------------------------------------------------
        mm = MOVED_BY_RE.match(s)
        if mm:
            rest = mm.group(1)
            seconder = None
            parts = GLUED_SECONDER_RE.split(rest, maxsplit=1)
            if len(parts) == 2:
                rest, seconder = parts
            mo = start_motion(ln["page"])
            mo["mover"] = rest
            if seconder:
                mo["seconder"] = seconder
                collecting = True
            else:
                collecting = False
            prev = ln
            continue

        sm = SECONDED_BY_RE.match(s)
        if sm:
            if motion is None or motion["seconder"] is not None or motion["_text"]:
                start_motion(ln["page"])
            motion["seconder"] = sm.group(1)
            collecting = True
            prev = ln
            continue

        trailing = _split_trailing_outcome(ln)
        if trailing and motion is not None and collecting:
            # "... Queen Street and Church Street.            Not Read"
            motion["_text"].append(trailing[0])
            s = trailing[1]
        om = OUTCOME_RE.match(s)
        if om:
            outcome = normalize_outcome(om.group(1))
            if outcome == "Not Dealt With":
                # "Officially read and not dealt with" disposes of the whole
                # item (e.g. no seconder for the main motion).
                for mo in cur["motions"]:
                    if mo["outcome"] is None:
                        mo["outcome"] = outcome
            if motion is not None:
                motion["outcome"] = outcome
            elif cur["motions"] and cur["motions"][-1]["outcome"] is None:
                cur["motions"][-1]["outcome"] = outcome
            elif not cur["motions"]:
                # Outcome printed ahead of the motion it disposes of
                # ("Withdrawn at the request of mover and seconder." then
                # the motion text).
                cur["_early_outcome"] = outcome
            else:
                mo = start_motion(ln["page"])
                mo["outcome"] = outcome
            close_motion()
            prev = ln
            continue

        if MOTION_LABEL_RE.match(s):
            close_motion()
            pending_kind = label_kind(s)
            prev = ln
            continue

        if motion is not None and collecting:
            motion["_text"].append(s)
        elif motion is not None and motion["mover"] and not motion["seconder"] and RESOLUTION_START_RE.match(s):
            # "Moved by" without a seconder line (rare) -- text still belongs to it
            collecting = True
            motion["_text"].append(s)
        elif RESOLUTION_START_RE.match(s):
            start_motion(ln["page"])
            collecting = True
            motion["_text"].append(s)
        else:
            cur["_notes"].append(s)
        prev = ln

    if table is not None:
        target = motion or (cur["motions"][-1] if cur and cur["motions"] else None)
        if target is not None:
            target["recorded_vote"] = table.as_dict()
    if cur:
        items.append(_finish_item(cur, doc_type))

    # Some minutes repeat a block of items verbatim (e.g. the whole by-law
    # list printed twice on December 18, 2023). Keep one copy of each
    # identical item -- the more complete one.
    deduped = []
    seen = {}
    for it in items:
        key = (it["item_number"], it["title"].lower())
        if key in seen:
            kept = seen[key]
            if kept["outcome"] is None and it["outcome"] is not None:
                deduped[deduped.index(kept)] = it
                seen[key] = it
            continue
        seen[key] = it
        deduped.append(it)
    items = deduped

    # A number genuinely used twice for different items (a numbering slip in
    # the minutes, e.g. two "8.3.1"s on August 28, 2023) would otherwise be
    # dropped by the database's one-row-per-number rule; keep both.
    used = Counter()
    for it in items:
        used[it["item_number"]] += 1
        if used[it["item_number"]] > 1:
            it["number_in_source"] = it["item_number"]
            it["item_number"] = f"{it['item_number']} ({used[it['item_number']]})"

    # Top-level sections ("8. Reports of City Departments") are only kept
    # when they carry a motion of their own; otherwise they're just
    # dividers and would add empty rows.
    items = [it for it in items if "." in it["item_number"] or it["motions"]]
    return items


def _plausible_child(number, current):
    """True if `number` can follow item `current` as an (indented) sub-item:
    its child, sibling, or a sibling of one of its ancestors."""
    parts = number.split(".")
    if len(parts) < 2:
        return False
    parent = ".".join(parts[:-1])
    return current == parent or (current + ".").startswith(parent + ".")


def _split_trailing_outcome(line):
    """(text, outcome) when a line ends with an outcome printed in the
    right-hand outcome column on the same baseline as the last text line."""
    words = line["words"]
    for k in (4, 3, 2, 1):
        if len(words) > k:
            tail = " ".join(w[0] for w in words[-k:])
            gap = words[-k][1] - words[-k - 1][2]
            if gap > 25 and OUTCOME_RE.match(tail):
                text = line["text"]
                idx = text.rfind(words[-k][0])
                return text[:idx].rstrip(), tail
    return None


def normalize_outcome(raw):
    r = raw.strip().rstrip(".\\").lower()
    if r.startswith("carrie"):  # includes one PDF's "Carrie" typo
        return "Carried"
    if "defeated" in r or r == "lost":
        return "Defeated"
    if r.startswith("withdrawn"):
        return "Withdrawn"
    if "not dealt with" in r or r == "not read":
        return "Not Dealt With"
    if r in ("postponed", "deferred", "tabled"):
        return "Postponed" if r == "postponed" else r.capitalize()
    return raw.strip()


# ---------------------------------------------------------------------------
# Document segmentation
# ---------------------------------------------------------------------------

ADJOURN_RE = re.compile(r"^\s*\d{1,2}\.\s+Adjournment\b", re.IGNORECASE | re.MULTILINE)


# The first line of a page that continues the previous page's motion
# (an Adjournment header at the very bottom of a page, its motion overleaf).
CONTINUATION_RE = re.compile(
    r"^(?:Moved by|Mover|Seconded by|Seconder|Resolved that this Council|Carried|Defeated)\b", re.IGNORECASE
)


def _first_line(text):
    for line in text.split("\n"):
        line = line.strip()
        if line and not RUNNING_HEADER_RE.match(line):
            return line
    return ""


def parse_pdf(path, doc_type):
    """Parses one PDF. Returns (main_doc, embedded_minutes_docs).

    main_doc: {"meeting_date", "meeting_type", "items", "pages": [first, last]}
    embedded_minutes_docs: minutes of earlier meetings that an agenda
    package carries as attachments (for adoption), each in the same shape.
    """
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        texts = {}

        def text_of(i):
            if i not in texts:
                texts[i] = pdf.pages[i].extract_text() or ""
            return texts[i]

        first = text_of(0)
        if doc_type == "minutes":
            end = n
        else:
            end = None
            for i in range(n):
                if ADJOURN_RE.search(text_of(i)):
                    end = i + 1
                    if end < n and CONTINUATION_RE.match(_first_line(text_of(end))):
                        end += 1
                    break
                if i > 0 and is_minutes_start(text_of(i)):
                    end = i
                    break
            end = end or n

        main_lines = read_lines(pdf, range(0, end))
        main = {
            "meeting_date": extract_meeting_date(first),
            "meeting_type": extract_meeting_type(first),
            "pages": [1, end],
            "items": parse_lines(main_lines, "minutes" if doc_type == "minutes" else "agenda"),
        }

        embedded = []
        if doc_type != "minutes":
            i = end
            lookahead = 3
            while i < n and lookahead > 0:
                if is_minutes_start(text_of(i)):
                    seg_end = None
                    for j in range(i, n):
                        if j > i and is_minutes_start(text_of(j)):
                            seg_end = j
                            break
                        if ADJOURN_RE.search(text_of(j)):
                            seg_end = j + 1
                            if seg_end < n and CONTINUATION_RE.match(_first_line(text_of(seg_end))):
                                seg_end += 1
                            break
                    if seg_end is None:
                        break
                    lines = read_lines(pdf, range(i, seg_end))
                    embedded.append(
                        {
                            "meeting_date": extract_meeting_date(text_of(i)),
                            "meeting_type": extract_meeting_type(text_of(i)),
                            "pages": [i + 1, seg_end],
                            "items": parse_lines(lines, "minutes"),
                        }
                    )
                    i = seg_end
                    lookahead = 3
                else:
                    i += 1
                    lookahead -= 1
    return main, embedded
