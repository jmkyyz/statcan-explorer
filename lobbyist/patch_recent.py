#!/usr/bin/env python3
"""
patch_recent.py
---------------
Supplements lobby.db with communication reports that were posted to the live
lobbycanada.gc.ca registry after the last full build_db.py run.

The open-data ZIP is updated weekly; this script bridges the gap by pulling from
the site's "Recent Monthly Communication Reports" CSV export, which is real-time.

Usage:
    python patch_recent.py              # auto-detects window from DB built_at
    python patch_recent.py --days 14    # force a specific lookback window
"""

import argparse
import csv
import datetime
import json
import re
import sqlite3
import sys
from pathlib import Path

from curl_cffi import requests

DB_PATH = Path(__file__).parent / "lobby.db"
RECENT_URL = "https://lobbycanada.gc.ca/app/secure/ocl/lrs/do/rcntCmLgs"
MAX_DAYS_PER_REQUEST = 14  # chunk window to stay well under the site's 3000-row cap


def log(msg):
    print(msg, flush=True)


# ── Fetching ─────────────────────────────────────────────────────────────────

def fetch_csv_for_range(from_date: str, to_date: str) -> str:
    """Download the recent-comms CSV for a specific posted-date range."""
    r = requests.get(
        RECENT_URL,
        params={"dateType": "4", "fromDate": from_date, "toDate": to_date, "csv": ""},
        impersonate="chrome",
        timeout=120,
    )
    r.raise_for_status()
    return r.text


def fetch_all_chunks(from_date: str, to_date: str) -> list[dict]:
    """Fetch in MAX_DAYS_PER_REQUEST-day chunks and merge, deduplicating by comm number."""
    start = datetime.date.fromisoformat(from_date)
    end = datetime.date.fromisoformat(to_date)
    delta = datetime.timedelta(days=MAX_DAYS_PER_REQUEST)

    all_rows: dict[str, dict] = {}  # comm_number → first row seen (primary row)
    all_dpoh: dict[str, list[dict]] = {}  # comm_number → list of dpoh rows

    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + delta - datetime.timedelta(days=1), end)
        log(f"  Fetching {cursor} → {chunk_end} ...")
        try:
            text = fetch_csv_for_range(cursor.isoformat(), chunk_end.isoformat())
            rows = _parse_csv(text)
            log(f"    {len(rows):,} rows")
            for row in rows:
                cn = row.get("Communication Number", "")
                if cn not in all_rows:
                    all_rows[cn] = row
                    all_dpoh[cn] = []
                all_dpoh[cn].append(row)
        except Exception as e:
            log(f"  WARNING: chunk {cursor}→{chunk_end} failed: {e}")
        cursor = chunk_end + datetime.timedelta(days=1)

    # Flatten: attach all dpoh rows onto each primary row
    result = []
    for cn, primary in all_rows.items():
        primary["_dpoh_rows"] = all_dpoh[cn]
        result.append(primary)
    return result


def _parse_csv(text: str) -> list[dict]:
    """Parse the CSV, skipping the decorative title line."""
    lines = text.splitlines()
    if len(lines) < 2:
        return []
    reader = csv.DictReader(lines[1:])  # skip "Posted in the Last N Days" title
    return list(reader)


# ── Name helpers ──────────────────────────────────────────────────────────────

def split_name_first_last(full: str) -> tuple[str, str]:
    """'John Smith' → ('John', 'Smith'). Splits on first space only."""
    parts = full.strip().split(' ', 1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", full.strip())


def split_reg_name(full: str) -> tuple[str, str]:
    """Registrant name is 'FIRSTNAME LASTNAME'; split on last space."""
    parts = full.strip().rsplit(' ', 1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", full.strip())


# ── Subject / institution helpers ────────────────────────────────────────────

def build_subject_map(con: sqlite3.Connection) -> dict[str, str]:
    """Return {description: subject_code} from subject_types table."""
    return dict(con.execute("SELECT description, subject_code FROM subject_types").fetchall())


def lookup_reg_num(con: sqlite3.Connection, client_num: str, reg_first: str, reg_last: str) -> str:
    """Try to find an existing reg_num by name, falling back to client+name."""
    row = con.execute(
        "SELECT reg_num FROM communications "
        "WHERE client_num=? AND reg_first=? AND reg_last=? AND reg_num!='' LIMIT 1",
        (client_num, reg_first, reg_last),
    ).fetchone()
    if row:
        return row[0]
    row = con.execute(
        "SELECT reg_num FROM communications "
        "WHERE reg_first=? AND reg_last=? AND reg_num!='' LIMIT 1",
        (reg_first, reg_last),
    ).fetchone()
    return row[0] if row else ""


# ── Core patch logic ──────────────────────────────────────────────────────────

def patch(lookback_days: int | None = None):
    if not DB_PATH.exists():
        raise RuntimeError("lobby.db not found — run build_db.py first")

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")

    # Determine the start of our patch window
    now = datetime.datetime.now(datetime.timezone.utc)
    if lookback_days:
        from_dt = now - datetime.timedelta(days=lookback_days)
    else:
        row = con.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
        if row:
            built_dt = datetime.datetime.fromisoformat(row[0])
            # Go back one extra day to catch any late-posted records
            from_dt = built_dt - datetime.timedelta(days=1)
        else:
            from_dt = now - datetime.timedelta(days=14)

    from_date = from_dt.strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    log(f"Patch window: {from_date} → {to_date}")

    # Fetch
    rows = fetch_all_chunks(from_date, to_date)
    log(f"Total unique communication numbers fetched: {len(rows):,}")

    if not rows:
        log("No data returned — nothing to patch.")
        _write_patch_meta(con, 0)
        con.close()
        return

    subj_map = build_subject_map(con)

    # Parse communication IDs and filter to new ones
    by_comlog: dict[int, dict] = {}
    for row in rows:
        cn = row.get("Communication Number", "")
        parts = cn.rsplit('-', 1)
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        cid = int(parts[1])
        by_comlog[cid] = row

    if not by_comlog:
        log("No valid communication IDs parsed.")
        _write_patch_meta(con, 0)
        con.close()
        return

    existing_ids = {
        r[0]
        for r in con.execute(
            f"SELECT comlog_id FROM communications "
            f"WHERE comlog_id IN ({','.join('?'*len(by_comlog))})",
            list(by_comlog.keys()),
        ).fetchall()
    }
    new_ids = set(by_comlog.keys()) - existing_ids
    log(f"Already in DB: {len(existing_ids):,}  |  New: {len(new_ids):,}")

    if not new_ids:
        log("All records already in DB — nothing to insert.")
        _write_patch_meta(con, 0)
        con.close()
        return

    # Build insert batches
    comm_batch, dpoh_batch, subj_batch = [], [], []

    for cid in sorted(new_ids):
        primary = by_comlog[cid]
        cn = primary["Communication Number"]
        client_num = cn.rsplit('-', 1)[0]

        comm_date = primary.get("Communication Date", "").strip()
        if not comm_date or len(comm_date) < 7:
            continue

        client_name = primary.get("Organization, Corporation or Client Name", "").strip()
        reg_name = primary.get("Registrant Name", "").strip()
        reg_first, reg_last = split_reg_name(reg_name)
        reg_num = lookup_reg_num(con, client_num, reg_first, reg_last)

        comm_batch.append((
            cid, client_num, client_name, reg_num,
            reg_last, reg_first,
            comm_date, int(comm_date[:4]), comm_date[:7],
            0,  # reg_type unknown from live CSV
            0,  # is_amendment unknown from live CSV
        ))

        # DPOH rows
        seen_dpoh: set[tuple] = set()
        for dpoh_row in primary.get("_dpoh_rows", [primary]):
            dpoh_name = dpoh_row.get("DPOH Name", "").strip()
            institution = dpoh_row.get("DPOH Government Institution", "").strip()
            title = dpoh_row.get("DPOH Position Title", "").strip()

            key = (dpoh_name, institution)
            if key in seen_dpoh:
                continue
            seen_dpoh.add(key)

            dpoh_first, dpoh_last = split_name_first_last(dpoh_name)
            dpoh_batch.append((cid, dpoh_last, dpoh_first, title, "", institution))

        # Subject rows
        subj_str = primary.get("Subject Matters", "").strip()
        seen_codes: set[str] = set()
        for desc in subj_str.split(','):
            code = subj_map.get(desc.strip())
            if code and code not in seen_codes:
                seen_codes.add(code)
                subj_batch.append((cid, code))

    # Write
    con.executemany(
        "INSERT OR IGNORE INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        comm_batch,
    )
    con.executemany(
        "INSERT INTO dpoh (comlog_id,dpoh_last,dpoh_first,dpoh_title,branch,institution) "
        "VALUES (?,?,?,?,?,?)",
        dpoh_batch,
    )
    con.executemany(
        "INSERT OR IGNORE INTO subjects (comlog_id,subject_code) VALUES (?,?)",
        subj_batch,
    )
    con.commit()

    log(f"Inserted: {len(comm_batch):,} comms, {len(dpoh_batch):,} DPOH, {len(subj_batch):,} subjects")

    _write_patch_meta(con, len(comm_batch))

    # Recompute cached stats so the dashboard reflects the new records
    log("Recomputing default stats ...")
    from build_db import compute_default_stats
    compute_default_stats(con)

    con.close()
    log("Patch complete.")


def _write_patch_meta(con: sqlite3.Connection, new_count: int):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("patched_at", now))
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", ("patch_new_count", str(new_count)))
    con.commit()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Patch lobby.db with recent live data")
    parser.add_argument("--days", type=int, default=None,
                        help="Force lookback window in days (default: auto from built_at)")
    args = parser.parse_args()
    patch(lookback_days=args.days)
