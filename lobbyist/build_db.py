#!/usr/bin/env python3
"""
build_db.py
-----------
Downloads the Office of the Commissioner of Lobbying open data,
filters communications to 2014-onwards, and builds lobby.db (SQLite).

Run during Render's build step, or locally to refresh the database:
    python -u build_db.py
"""

import csv
import io
import sqlite3
import sys
import zipfile
from pathlib import Path

import requests

COMMS_URL = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
DB_PATH = Path(__file__).parent / "lobby.db"
MIN_DATE = "2014-01-01"
BATCH = 5_000


def get_remote_last_modified() -> str:
    """Return the Last-Modified header from the zip URL, or empty string."""
    try:
        r = requests.head(COMMS_URL, timeout=30)
        return r.headers.get("Last-Modified", "")
    except Exception:
        return ""


def log(msg):
    print(msg, flush=True)


def download_zip(url: str) -> zipfile.ZipFile:
    log(f"Downloading {url} ...")
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    log(f"  {len(r.content) / 1e6:.1f} MB downloaded")
    return zipfile.ZipFile(io.BytesIO(r.content))


def open_csv(zf: zipfile.ZipFile, name: str):
    """Return a csv.DictReader for a file inside the zip."""
    f = zf.open(name)
    # utf-8-sig strips the BOM if present
    return f, csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"))


def clean(val):
    v = (val or "").strip()
    return "" if v.lower() == "null" else v


def build():
    remote_last_modified = get_remote_last_modified()
    log(f"Remote Last-Modified: {remote_last_modified or '(unknown)'}")

    zf = download_zip(COMMS_URL)

    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")  # faster writes during bulk load

    con.executescript("""
        CREATE TABLE meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE communications (
            comlog_id    INTEGER PRIMARY KEY,
            client_num   TEXT,
            client_name  TEXT,
            reg_num      TEXT,
            reg_last     TEXT,
            reg_first    TEXT,
            comm_date    TEXT,
            comm_year    INTEGER,
            comm_month   TEXT,
            reg_type     INTEGER,
            is_amendment INTEGER
        );
        CREATE TABLE dpoh (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            comlog_id    INTEGER,
            dpoh_last    TEXT,
            dpoh_first   TEXT,
            dpoh_title   TEXT,
            branch       TEXT,
            institution  TEXT
        );
        CREATE TABLE subjects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            comlog_id    INTEGER,
            subject_code TEXT
        );
        CREATE TABLE subject_types (
            subject_code TEXT PRIMARY KEY,
            description  TEXT
        );
        CREATE TABLE subject_details (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            comlog_id    INTEGER,
            detail_text  TEXT
        );
    """)

    # ── 1. Primary communications ────────────────────────────────────────────
    log("Reading Communication_PrimaryExport.csv ...")
    valid_ids = set()
    n_primary = 0
    batch = []

    f, reader = open_csv(zf, "Communication_PrimaryExport.csv")
    for row in reader:
        comm_date = clean(row.get("COMM_DATE", ""))
        if comm_date < MIN_DATE:
            continue

        cid = int(clean(row["COMLOG_ID"]))
        valid_ids.add(cid)
        prev = clean(row.get("PREV_COMLOG_ID_PRECEDNT", ""))
        reg_type_raw = clean(row.get("REG_TYPE_ENR", ""))

        batch.append((
            cid,
            clean(row.get("CLIENT_ORG_CORP_NUM", "")),
            clean(row.get("EN_CLIENT_ORG_CORP_NM_AN", "")),
            clean(row.get("REGISTRANT_NUM_DECLARANT", "")),
            clean(row.get("RGSTRNT_LAST_NM_DCLRNT", "")),
            clean(row.get("RGSTRNT_1ST_NM_PRENOM_DCLRNT", "")),
            comm_date,
            int(comm_date[:4]),
            comm_date[:7],
            int(reg_type_raw) if reg_type_raw else 0,
            1 if prev else 0,
        ))

        if len(batch) >= BATCH:
            con.executemany("INSERT INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
            con.commit()
            n_primary += len(batch)
            batch.clear()

    if batch:
        con.executemany("INSERT INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
        con.commit()
        n_primary += len(batch)
    f.close()

    log(f"  {n_primary:,} communications inserted ({len(valid_ids):,} unique IDs)")

    # ── 2. DPOH records ───────────────────────────────────────────────────────
    log("Reading Communication_DpohExport.csv ...")
    n_dpoh = 0
    batch = []

    f, reader = open_csv(zf, "Communication_DpohExport.csv")
    for row in reader:
        cid_raw = clean(row.get("COMLOG_ID", ""))
        if not cid_raw:
            continue
        cid = int(cid_raw)
        if cid not in valid_ids:
            continue

        batch.append((
            cid,
            clean(row.get("DPOH_LAST_NM_TCPD", "")),
            clean(row.get("DPOH_FIRST_NM_PRENOM_TCPD", "")),
            clean(row.get("DPOH_TITLE_TITRE_TCPD", "")),
            clean(row.get("BRANCH_UNIT_DIRECTION_SERVICE", "")),
            clean(row.get("INSTITUTION", "")),
        ))

        if len(batch) >= BATCH:
            con.executemany(
                "INSERT INTO dpoh (comlog_id,dpoh_last,dpoh_first,dpoh_title,branch,institution) VALUES (?,?,?,?,?,?)",
                batch,
            )
            con.commit()
            n_dpoh += len(batch)
            batch.clear()

    if batch:
        con.executemany(
            "INSERT INTO dpoh (comlog_id,dpoh_last,dpoh_first,dpoh_title,branch,institution) VALUES (?,?,?,?,?,?)",
            batch,
        )
        con.commit()
        n_dpoh += len(batch)
    f.close()

    log(f"  {n_dpoh:,} DPOH records inserted")

    # ── 3. Subject matters ────────────────────────────────────────────────────
    log("Reading Communication_SubjectMattersExport.csv ...")
    n_subj = 0
    batch = []

    f, reader = open_csv(zf, "Communication_SubjectMattersExport.csv")
    for row in reader:
        cid_raw = clean(row.get("COMLOG_ID", ""))
        code    = clean(row.get("SUBJECT_CODE_OBJET", ""))
        if not cid_raw or not code:
            continue
        cid = int(cid_raw)
        if cid not in valid_ids:
            continue

        batch.append((cid, code))

        if len(batch) >= BATCH:
            con.executemany("INSERT INTO subjects (comlog_id,subject_code) VALUES (?,?)", batch)
            con.commit()
            n_subj += len(batch)
            batch.clear()

    if batch:
        con.executemany("INSERT INTO subjects (comlog_id,subject_code) VALUES (?,?)", batch)
        con.commit()
        n_subj += len(batch)
    f.close()

    log(f"  {n_subj:,} subject records inserted")

    # ── 3b. Subject matter details (V6 registrations, post-Oct 2024) ─────────
    log("Reading Communication_SubjectMatterDetailsExport.csv ...")
    n_subj2 = 0
    batch = []
    detail_batch = []

    f, reader = open_csv(zf, "Communication_SubjectMatterDetailsExport.csv")
    # Detect which column holds the English detail description
    _det_col = None
    for candidate in ("EN_DESCRIPTION", "DESCRIPTION_EN", "DESCRIP_EN",
                      "DESCRIPTION", "EN_DESCRIP", "DETAIL_EN", "EN_DETAIL",
                      "SMT_EN_DESCRIPTION", "EN_SUBJECT_MATTER_DETAILS"):
        if candidate in (reader.fieldnames or []):
            _det_col = candidate
            break
    if _det_col:
        log(f"  Detail description column: {_det_col}")
    else:
        log(f"  No detail description column found (columns: {reader.fieldnames})")

    for row in reader:
        cid_raw  = clean(row.get("COMLOG_ID", ""))
        code_raw = clean(row.get("SUBJECT_CODE_OBJET", ""))
        if not cid_raw or not code_raw:
            continue
        cid = int(cid_raw)
        if cid not in valid_ids:
            continue

        # SUBJECT_CODE_OBJET can be a comma-separated list (e.g. "SMT-10, SMT-25")
        for code in [c.strip() for c in code_raw.split(",") if c.strip()]:
            batch.append((cid, code))

        if _det_col:
            detail = clean(row.get(_det_col, ""))
            if detail:
                detail_batch.append((cid, detail))

        if len(batch) >= BATCH:
            con.executemany("INSERT OR IGNORE INTO subjects (comlog_id,subject_code) VALUES (?,?)", batch)
            con.commit()
            n_subj2 += len(batch)
            batch.clear()

        if len(detail_batch) >= BATCH:
            con.executemany("INSERT INTO subject_details (comlog_id,detail_text) VALUES (?,?)", detail_batch)
            con.commit()
            detail_batch.clear()

    if batch:
        con.executemany("INSERT OR IGNORE INTO subjects (comlog_id,subject_code) VALUES (?,?)", batch)
        con.commit()
        n_subj2 += len(batch)
    if detail_batch:
        con.executemany("INSERT INTO subject_details (comlog_id,detail_text) VALUES (?,?)", detail_batch)
        con.commit()
    f.close()

    log(f"  {n_subj2:,} additional subject records inserted (V6)")

    # ── 4. Subject type codes (small file) ───────────────────────────────────
    log("Reading Codes_SubjectMatterTypesExport.csv ...")
    f, reader = open_csv(zf, "Codes_SubjectMatterTypesExport.csv")
    smt_rows = [
        (clean(row["SUBJECT_CODE_OBJET"]), clean(row["SMT_EN_DESC"]))
        for row in reader
        if clean(row.get("SUBJECT_CODE_OBJET", ""))
    ]
    f.close()
    con.executemany("INSERT INTO subject_types VALUES (?,?)", smt_rows)
    con.commit()
    log(f"  {len(smt_rows):,} subject type codes inserted")

    # ── 5. Meta ───────────────────────────────────────────────────────────────
    import datetime
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("source_last_modified", remote_last_modified))
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("built_at", datetime.datetime.utcnow().isoformat()))
    con.commit()

    # ── 6. Indexes ────────────────────────────────────────────────────────────
    log("Creating indexes ...")
    con.executescript("""
        CREATE INDEX idx_c_year    ON communications(comm_year);
        CREATE INDEX idx_c_month   ON communications(comm_month);
        CREATE INDEX idx_c_client  ON communications(client_name COLLATE NOCASE);
        CREATE INDEX idx_c_cnum    ON communications(client_num);
        CREATE INDEX idx_c_regtype ON communications(reg_type);
        CREATE INDEX idx_c_regnum  ON communications(reg_num);
        CREATE INDEX idx_d_comlog  ON dpoh(comlog_id);
        CREATE INDEX idx_d_inst    ON dpoh(institution);
        CREATE INDEX idx_d_name    ON dpoh(dpoh_last, dpoh_first);
        CREATE INDEX idx_s_comlog  ON subjects(comlog_id);
        CREATE INDEX idx_s_code    ON subjects(subject_code);
        CREATE INDEX idx_sd_comlog ON subject_details(comlog_id);
    """)
    con.close()

    size_mb = DB_PATH.stat().st_size / 1e6
    log(f"Done. lobby.db = {size_mb:.1f} MB")


if __name__ == "__main__":
    build()
