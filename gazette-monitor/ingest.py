"""Ingestion pipeline for the Canada Gazette Regulatory Monitor.

Flow:
  1. Poll the three RSS feeds. Each RSS item is one whole issue.
  2. Any issue within the lookback window that isn't already in the
     database gets fetched and parsed to the item level.
  3. Part I "Proposed Regulations" items get a second fetch to pull the
     RIAS summary and comment deadline from the regulation page.
  4. Every active watchlist rule is run against every item; INSERT OR
     IGNORE plus a UNIQUE(item_id, rule_id) constraint makes re-runs
     (and rule edits) safe and retroactive.

Callable standalone (`python ingest.py [--init]`) or from the Flask app.
"""

import argparse
import datetime as dt
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from models import get_db, init_db

FEEDS = {
    "I": "https://www.gazette.gc.ca/rss/p1-eng.xml",
    "II": "https://www.gazette.gc.ca/rss/p2-eng.xml",
    "III": "https://www.gazette.gc.ca/rss/en-ls-eng.xml",
}

HEADERS = {"User-Agent": "GazetteMonitor/1.0 (personal journalism research tool)"}
REQUEST_DELAY = 1.0  # seconds between HTTP requests — be polite to the server
RIAS_MAX_CHARS = 2000
DEFAULT_LOOKBACK_DAYS = 28

MONTHS = ("january february march april may june july august september "
          "october november december").split()


class IngestLogger:
    """Collects log lines so the web UI can display them; also prints."""

    def __init__(self, echo=True):
        self.lines = []
        self.echo = echo

    def log(self, msg):
        line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.lines.append(line)
        if self.echo:
            print(line)

    def warn(self, msg):
        self.log(f"WARNING: {msg}")


def _get(session, url, logger):
    time.sleep(REQUEST_DELAY)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# RSS parsing
# ---------------------------------------------------------------------------

def parse_feed(xml_text, logger):
    """Return a list of {title, link, guid, pub_date} dicts, newest first."""
    entries = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warn(f"RSS feed did not parse as XML: {exc}")
        return entries
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        pub_date = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                pub_date = parsedate_to_datetime(raw_date.strip()).date()
            except (ValueError, TypeError):
                logger.warn(f"Unparseable pubDate '{raw_date}' for {link}")
        if link:
            entries.append({"title": title, "link": link, "guid": guid,
                            "pub_date": pub_date})
    return entries


def parse_volume_number(title):
    """Extract (volume, number) from an RSS issue title, e.g.
    'Canada Gazette - Part I, July 4, 2026, volume 160, number 27'."""
    volume = number = None
    m = re.search(r"volume\s+(\d+)", title, re.I)
    if m:
        volume = int(m.group(1))
    m = re.search(r"number\s+([\w .-]+?)\s*$", title, re.I)
    if m:
        number = m.group(1).strip()
    return volume, number


# ---------------------------------------------------------------------------
# Index page parsing
# ---------------------------------------------------------------------------

def _inside_aside(el):
    return el.find_parent("aside") is not None


def parse_part1_index(html, index_url, logger):
    """Part I (and same-format) index pages: nested h2 section / h3
    department / h4 act headings, each followed by a ul of item links."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="content") or soup.find("main")
    if content is None:
        logger.warn(f"No #content container found on {index_url}")
        return []

    items = []
    section = department = act = None
    for el in content.find_all(["h2", "h3", "h4", "ul"]):
        if _inside_aside(el):  # skip the footnotes block
            continue
        if el.name == "h2":
            section = el.get_text(" ", strip=True)
            department = act = None
        elif el.name == "h3":
            department = el.get_text(" ", strip=True)
            act = None
        elif el.name == "h4":
            act = el.get_text(" ", strip=True)
        elif el.name == "ul":
            if section is None:
                continue  # nav/utility list before the first heading
            for li in el.find_all("li", recursive=False):
                a = li.find("a")
                if not a or not a.get("href"):
                    continue
                title = " ".join(a.get_text(" ", strip=True).split())
                if not title:
                    continue
                items.append({
                    "section": section,
                    "department": department,
                    "act": act,
                    "title": title,
                    "item_url": urljoin(index_url, a["href"]),
                })
    if not items:
        logger.warn(f"Index page parsed but yielded no items: {index_url}")
    return items


def extract_page_title(html):
    """Real item title from a Gazette page h1, e.g.
    'Canada Gazette, Part I, Volume 160, Number 5: Order Imposing…' → the
    part after the colon."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 is None:
        return None
    text = " ".join(h1.get_text(" ", strip=True).split())
    # Only strip a "Canada Gazette, Part I, Volume…:" prefix; other h1s can
    # legitimately contain colons (e.g. "Proclamation…: SI/2026-29").
    if text.lower().startswith("canada gazette") and ":" in text:
        after = text.split(":", 1)[1].strip()
        if after:
            return after
    return text or None


def parse_part2_index(html, index_url, logger):
    """Part II index pages: a flat ul where each li anchor holds the title
    and enabling act(s) separated by <br>, followed by a SOR/SI number."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="content") or soup.find("main")
    if content is None:
        logger.warn(f"No #content container found on {index_url}")
        return []

    items = []
    for li in content.find_all("li"):
        if _inside_aside(li):
            continue
        a = li.find("a")
        if not a or not a.get("href"):
            continue
        segments = [" ".join(s.split()) for s in a.stripped_strings]
        segments = [s for s in segments if s]
        if not segments:
            continue
        title, acts = segments[0], segments[1:]

        # Registration number (SOR/2026-114 or SI/2026-27) sits after the <a>
        registration = None
        for s in li.stripped_strings:
            s = " ".join(s.split())
            if re.match(r"^(SOR|SI)/", s):
                registration = s
                break
        if registration:
            title = f"{title} [{registration}]"
            section = ("Statutory Instruments (Regulations)"
                       if registration.startswith("SOR")
                       else "Statutory Instruments (Other than Regulations)")
        else:
            section = "Statutory Instruments"

        items.append({
            "section": section,
            "department": None,
            "act": "; ".join(acts) or None,
            "title": title,
            "item_url": urljoin(index_url, a["href"]),
        })
    if not items:
        logger.warn(f"Part II index parsed but yielded no items: {index_url}")
    return items


# ---------------------------------------------------------------------------
# Part I item pages: RIAS + comment deadline
# ---------------------------------------------------------------------------

def extract_rias(soup):
    """Text following the 'REGULATORY IMPACT ANALYSIS STATEMENT' h2,
    truncated to RIAS_MAX_CHARS."""
    heading = None
    for h2 in soup.find_all("h2"):
        if "REGULATORY IMPACT ANALYSIS" in h2.get_text(strip=True).upper():
            heading = h2
            break
    if heading is None:
        return None
    parts = []
    total = 0
    for sib in heading.find_next_siblings():
        if sib.name == "h2":
            break
        text = sib.get_text(" ", strip=True)
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= RIAS_MAX_CHARS:
            break
    if not parts:
        return None
    return " ".join(parts)[:RIAS_MAX_CHARS]


def _parse_written_date(s):
    s = s.replace("\xa0", " ").replace(",", "")
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})", s.strip())
    if not m:
        return None
    month_name = m.group(1).lower()
    if month_name not in MONTHS:
        return None
    return dt.date(int(m.group(3)), MONTHS.index(month_name) + 1, int(m.group(2)))


def extract_comment_deadline(page_text, issue_date):
    """Comment deadline for a Part I proposed regulation.

    Two forms appear in practice: an explicit date ('on or before
    August 15, 2026') near the 'make representations' sentence, or
    'within N days after the date of publication' (computed from the
    issue date).
    """
    text = page_text.replace("\xa0", " ")

    idx = text.lower().find("representations")
    if idx != -1:
        window = text[max(0, idx - 500): idx + 1500]
        m = re.search(
            r"(?:on or before|no later than|not later than|until|by)\s+"
            r"([A-Z][a-zé]+\s+\d{1,2},?\s+\d{4})", window)
        if m:
            parsed = _parse_written_date(m.group(1))
            if parsed:
                return parsed

    m = re.search(r"within\s+(\d+)\s+days?\s+after\s+the\s+date\s+of\s+publication",
                  text, re.I)
    if m and issue_date:
        return issue_date + dt.timedelta(days=int(m.group(1)))
    return None


def fetch_item_details(session, item_url, issue_date, logger):
    """Fetch a Part I proposed-regulation page; return (rias, deadline)."""
    try:
        html = _get(session, item_url, logger)
    except requests.RequestException as exc:
        logger.warn(f"Failed to fetch item page {item_url}: {exc}")
        return None, None
    soup = BeautifulSoup(html, "html.parser")
    rias = extract_rias(soup)
    if rias is None:
        logger.warn(f"No RIAS section found on {item_url}")
    content = soup.find(id="content") or soup
    deadline = extract_comment_deadline(content.get_text(" ", strip=True), issue_date)
    return rias, deadline


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def keyword_hit(keyword, blob):
    """Case-insensitive whole-word match, tolerating a plural suffix.
    Plain substring matching drowns the feed in false positives ('rent'
    inside 'current', 'import' inside 'important')."""
    return re.search(rf"\b{re.escape(keyword.lower())}(?:e?s)?\b", blob) is not None


def run_matching(conn, logger):
    """Run every active rule against every item. INSERT OR IGNORE + the
    UNIQUE(item_id, rule_id) constraint keep this idempotent, so rule
    edits apply retroactively on the next ingest run."""
    rules = conn.execute("SELECT * FROM watchlist_rules WHERE active = 1").fetchall()
    items = conn.execute(
        "SELECT id, title, department, rias_summary FROM gazette_items").fetchall()
    new_matches = 0
    now = dt.datetime.now().isoformat(timespec="seconds")

    for rule in rules:
        try:
            keywords = json.loads(rule["keywords"])
            departments = json.loads(rule["departments"] or "[]")
        except json.JSONDecodeError:
            logger.warn(f"Rule '{rule['label']}' has malformed JSON; skipping")
            continue

        for item in items:
            blob = " ".join(filter(None, [item["title"], item["rias_summary"],
                                          item["department"]])).lower()
            hits = [k for k in keywords if keyword_hit(k, blob)]
            if rule["match_mode"] == "all":
                keyword_ok = len(hits) == len(keywords) and keywords
            else:
                keyword_ok = bool(hits)
            if not keyword_ok:
                continue
            if departments:
                dept = (item["department"] or "").lower()
                dept_hits = [d for d in departments if d.lower() in dept]
                if not dept_hits:
                    continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO matches (item_id, rule_id, matched_on, created_at)"
                " VALUES (?, ?, ?, ?)",
                (item["id"], rule["id"], ", ".join(hits), now))
            new_matches += cur.rowcount
    conn.commit()
    return new_matches


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def process_issue(conn, session, part, entry, logger):
    """Insert one issue and its items. Returns count of new items."""
    volume, number = parse_volume_number(entry["title"])
    now = dt.datetime.now().isoformat(timespec="seconds")
    issue_date = entry["pub_date"].isoformat() if entry["pub_date"] else None

    cur = conn.execute(
        "INSERT OR IGNORE INTO gazette_issues"
        " (part, volume, number, issue_date, index_url, fetched_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (part, volume, number, issue_date, entry["link"], now))
    if cur.rowcount == 0:
        return 0  # already ingested
    issue_id = cur.lastrowid
    logger.log(f"Part {part}: new issue {entry['title']}")

    # --- parse items -------------------------------------------------------
    if part == "III" or entry["link"].lower().endswith(".pdf"):
        # Part III links straight to a PDF (no HTML index); record the
        # issue itself as a single item so it still shows up in the feed.
        conn.execute(
            "INSERT OR IGNORE INTO gazette_items"
            " (issue_id, section, department, act, title, item_url)"
            " VALUES (?, 'Acts of Parliament', NULL, NULL, ?, ?)",
            (issue_id, entry["title"], entry["link"]))
        conn.commit()
        return 1

    try:
        html = _get(session, entry["link"], logger)
    except requests.RequestException as exc:
        logger.warn(f"Failed to fetch index {entry['link']}: {exc}")
        conn.commit()
        return 0

    if part == "II":
        items = parse_part2_index(html, entry["link"], logger)
    else:
        items = parse_part1_index(html, entry["link"], logger)

    # Extra editions link straight to the item page rather than an index
    # (e.g. .../2026-06-08-x5/html/extra5-eng.html). Store the page itself
    # as a single item — extras are often urgent orders worth flagging.
    if not items and "extra" in entry["title"].lower():
        title = extract_page_title(html) or entry["title"]
        items = [{
            "section": "Extra edition",
            "department": None,
            "act": None,
            "title": title,
            "item_url": entry["link"],
        }]
        logger.log(f"  treated as extra edition: {title[:80]}")

    new_items = 0
    for it in items:
        cur = conn.execute(
            "INSERT OR IGNORE INTO gazette_items"
            " (issue_id, section, department, act, title, item_url)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (issue_id, it["section"], it["department"], it["act"],
             it["title"], it["item_url"]))
        new_items += cur.rowcount
    conn.commit()
    logger.log(f"  parsed {len(items)} items ({new_items} new)")

    # --- Part I proposed regs: fetch RIAS + comment deadline ---------------
    if part == "I":
        rows = conn.execute(
            "SELECT id, item_url FROM gazette_items WHERE issue_id = ?"
            " AND lower(section) LIKE '%proposed regulation%'"
            " AND full_text_fetched_at IS NULL", (issue_id,)).fetchall()
        for row in rows:
            rias, deadline = fetch_item_details(
                session, row["item_url"], entry["pub_date"], logger)
            conn.execute(
                "UPDATE gazette_items SET rias_summary = ?, comment_deadline = ?,"
                " full_text_fetched_at = ? WHERE id = ?",
                (rias, deadline.isoformat() if deadline else None, now, row["id"]))
            logger.log(f"  RIAS fetched: {row['item_url'].rsplit('/', 1)[-1]}"
                       f" (deadline: {deadline or 'none found'})")
        conn.commit()

    return new_items


def run_ingest(lookback_days=DEFAULT_LOOKBACK_DAYS, logger=None):
    """Full pipeline. Returns the logger (with .lines) for display."""
    logger = logger or IngestLogger()
    init_db()
    conn = get_db()
    session = requests.Session()
    session.headers.update(HEADERS)
    cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
    total_new_items = 0

    for part, feed_url in FEEDS.items():
        logger.log(f"Checking Part {part} feed…")
        try:
            resp = session.get(feed_url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warn(f"Feed fetch failed for Part {part}: {exc}")
            continue
        entries = parse_feed(resp.text, logger)
        if not entries:
            logger.warn(f"Part {part} feed had no entries")
            continue

        conn.execute(
            "INSERT INTO ingest_state (feed, last_guid, checked_at) VALUES (?, ?, ?)"
            " ON CONFLICT(feed) DO UPDATE SET last_guid = excluded.last_guid,"
            " checked_at = excluded.checked_at",
            (part, entries[0]["guid"], dt.datetime.now().isoformat(timespec="seconds")))
        conn.commit()

        fresh = [e for e in entries if e["pub_date"] and e["pub_date"] >= cutoff]
        if not fresh:
            logger.log(f"Part {part}: nothing new within {lookback_days} days")
            continue
        for entry in fresh:
            try:
                total_new_items += process_issue(conn, session, part, entry, logger)
            except Exception as exc:  # keep one bad issue from killing the run
                logger.warn(f"Unexpected error on {entry['link']}: {exc}")

    new_matches = run_matching(conn, logger)
    logger.log(f"Done. {total_new_items} new items, {new_matches} new matches.")
    conn.close()
    return logger


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canada Gazette ingest pipeline")
    parser.add_argument("--init", action="store_true",
                        help="first-run setup: create DB, seed rules, backfill 4 weeks")
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help="days of history to (re)process (default 28)")
    args = parser.parse_args()
    result = run_ingest(lookback_days=args.lookback)
    sys.exit(0)
