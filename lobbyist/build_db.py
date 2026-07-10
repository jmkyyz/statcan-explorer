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
import json
import os
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

from curl_cffi import requests

COMMS_URL = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
REGS_URL  = "https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip"
# DB path is overridable so the build can target a scratch DB during local
# verification without touching the live lobby.db.
DB_PATH = Path(os.environ.get("LOBBY_DB_PATH", Path(__file__).parent / "lobby.db"))
MIN_DATE = "2014-01-01"
BATCH = 5_000
# When set, zips are read from / written to this directory instead of being
# re-downloaded — speeds up repeated local builds. Never set in production.
ZIP_CACHE_DIR = os.environ.get("LOBBY_ZIP_CACHE", "")


def log(msg):
    print(msg, flush=True)


def download_zip(url: str, cache_name: str = "") -> tuple:
    """Download the zip and return (ZipFile, file_size_bytes, last_modified_header).

    Uses curl_cffi to impersonate Chrome's TLS fingerprint —
    lobbycanada.gc.ca blocks all standard HTTP clients via JA3 fingerprinting.

    If ZIP_CACHE_DIR is set and a cached copy exists, it is used instead of
    downloading (local dev only). The Last-Modified header is cached alongside
    it in a .lm sidecar so update-check meta stays populated.
    """
    cache = Path(ZIP_CACHE_DIR) / cache_name if (ZIP_CACHE_DIR and cache_name) else None
    if cache and cache.exists():
        data = cache.read_bytes()
        lm_file = cache.with_suffix(cache.suffix + ".lm")
        lm = lm_file.read_text().strip() if lm_file.exists() else ""
        log(f"  Using cached {cache_name} ({len(data) / 1e6:.1f} MB)")
        return zipfile.ZipFile(io.BytesIO(data)), len(data), lm

    log(f"Downloading {url} ...")
    r = requests.get(url, impersonate="chrome", timeout=300)
    r.raise_for_status()
    data = r.content
    log(f"  {len(data) / 1e6:.1f} MB downloaded")
    lm = r.headers.get("Last-Modified", "")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        cache.with_suffix(cache.suffix + ".lm").write_text(lm)
    return zipfile.ZipFile(io.BytesIO(data)), len(data), lm


def open_csv(zf: zipfile.ZipFile, name: str):
    """Return a csv.DictReader for a file inside the zip."""
    f = zf.open(name)
    # utf-8-sig strips the BOM if present
    return f, csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"))


def clean(val):
    v = (val or "").strip()
    return "" if v.lower() == "null" else v


_NORM_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_NORM_PUNCT = re.compile(r"[^a-z0-9 ]")
_NORM_WS    = re.compile(r"\s+")


def norm_name(s: str) -> str:
    """Canonicalise a client/organization name so the SAME organization
    registering under different client_num profiles (each consultant engagement
    gets a fresh one) collapses to one key. Light-touch by design — lowercase,
    drop a trailing parenthetical (e.g. '(CDA)'), strip punctuation, collapse
    whitespace. Deliberately does NOT strip Inc/Ltd/Corp (would merge distinct
    entities). It is a heuristic: genuine name variants can still slip through."""
    if not s:
        return ""
    s = s.lower().strip()
    s = _NORM_PAREN.sub("", s)
    s = _NORM_PUNCT.sub(" ", s)
    return _NORM_WS.sub(" ", s).strip()


def compute_default_stats(con):
    """Compute unfiltered stats and store as JSON in the meta table."""
    log("Computing default stats for cache...")

    row = con.execute("""
        SELECT COUNT(*)                   AS total,
               COUNT(DISTINCT client_num) AS unique_clients,
               COUNT(DISTINCT reg_num)    AS unique_lobbyists
        FROM communications
    """).fetchone()
    result = {"total": row[0], "unique_clients": row[1], "unique_lobbyists": row[2]}

    result["unique_dpoh"] = con.execute("""
        SELECT COUNT(DISTINCT dpoh_last || ',' || dpoh_first)
        FROM dpoh WHERE dpoh_last != ''
    """).fetchone()[0]

    by_month = con.execute("""
        SELECT comm_month, COUNT(*) FROM communications
        GROUP BY comm_month ORDER BY comm_month
    """).fetchall()
    result["by_month"] = [{"month": r[0], "count": r[1]} for r in by_month]

    top_clients = con.execute("""
        SELECT client_name, COUNT(*) AS cnt FROM communications
        WHERE client_name != ''
        GROUP BY client_name ORDER BY cnt DESC LIMIT 20
    """).fetchall()
    result["top_clients"] = [{"client_name": r[0], "count": r[1]} for r in top_clients]

    top_inst = con.execute("""
        SELECT institution, COUNT(DISTINCT comlog_id) AS cnt
        FROM dpoh WHERE institution != ''
        GROUP BY institution ORDER BY cnt DESC LIMIT 20
    """).fetchall()
    result["top_institutions"] = [{"institution": r[0], "count": r[1]} for r in top_inst]

    top_subj = con.execute("""
        SELECT s.subject_code, st.description, COUNT(DISTINCT s.comlog_id) AS cnt
        FROM subjects s
        JOIN subject_types st ON st.subject_code = s.subject_code
        WHERE s.subject_code != ''
        GROUP BY s.subject_code ORDER BY cnt DESC
    """).fetchall()
    result["top_subjects"] = [
        {"subject_code": r[0], "description": r[1], "count": r[2]} for r in top_subj
    ]

    top_dpoh = con.execute("""
        SELECT dpoh_first || ' ' || dpoh_last AS name,
               dpoh_title, institution,
               COUNT(DISTINCT comlog_id) AS cnt
        FROM dpoh WHERE dpoh_last != ''
        GROUP BY dpoh_last, dpoh_first, institution
        ORDER BY cnt DESC LIMIT 20
    """).fetchall()
    result["top_dpoh"] = [
        {"name": r[0], "title": r[1], "institution": r[2], "count": r[3]}
        for r in top_dpoh
    ]

    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("default_stats", json.dumps(result)))
    con.commit()
    log(f"  Done ({result['total']:,} communications)")


# ── Registrations ingestion ───────────────────────────────────────────────────

def build_registrations(con) -> tuple:
    """Ingest the registrations open-data ZIP into registrations / reg_subjects /
    reg_institutions, filtered to POSTED_DATE_PUBLICATION >= MIN_DATE. Streams in
    BATCH-sized commits so build memory stays flat. Returns (file_size, last_modified)."""
    zf, file_size, remote_last_modified = download_zip(
        REGS_URL, "registrations_enregistrements_ocl_cal.zip"
    )
    log(f"Registrations ZIP: {file_size:,} bytes, Last-Modified: {remote_last_modified or '(unknown)'}")

    # ── Primary: one row per registration version ────────────────────────────
    log("Reading Registration_PrimaryExport.csv ...")
    keep_ids = set()
    n_reg = 0
    batch = []

    f, reader = open_csv(zf, "Registration_PrimaryExport.csv")
    for row in reader:
        posted = clean(row.get("POSTED_DATE_PUBLICATION", ""))
        if posted < MIN_DATE or len(posted) < 7:
            continue

        rid_raw = clean(row.get("REG_ID_ENR", ""))
        if not rid_raw.isdigit():
            continue
        rid = int(rid_raw)
        keep_ids.add(rid)

        reg_type_raw = clean(row.get("REG_TYPE_ENR", ""))
        prev = clean(row.get("PREV_REG_ID_ENR_PRECEDNT", ""))
        client_name = clean(row.get("EN_CLIENT_ORG_CORP_NM_AN", ""))

        batch.append((
            rid,
            clean(row.get("REG_NUM_ENR", "")),
            int(reg_type_raw) if reg_type_raw.isdigit() else 0,
            clean(row.get("VERSION_CODE", "")),
            clean(row.get("EN_FIRM_NM_FIRME_AN", "")),
            clean(row.get("RGSTRNT_NUM_DECLARANT", "")),
            clean(row.get("RGSTRNT_LAST_NM_DCLRNT", "")),
            clean(row.get("RGSTRNT_1ST_NM_PRENOM_DCLRNT", "")),
            clean(row.get("CLIENT_ORG_CORP_NUM", "")),
            client_name,
            clean(row.get("EFFECTIVE_DATE_VIGUEUR", "")),
            clean(row.get("END_DATE_FIN", "")),
            posted,
            int(posted[:4]),
            posted[:7],
            0 if prev else 1,   # is_original: 1 when there is no predecessor
            clean(row.get("GOVT_FUND_IND_FIN_GOUV", "")),
            clean(row.get("CONTG_FEE_IND_HON_COND", "")),
            clean(row.get("COALITION_IND", "")),
            norm_name(client_name),
        ))

        if len(batch) >= BATCH:
            con.executemany(
                "INSERT INTO registrations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            con.commit()
            n_reg += len(batch)
            batch.clear()

    if batch:
        con.executemany(
            "INSERT INTO registrations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        con.commit()
        n_reg += len(batch)
    f.close()
    log(f"  {n_reg:,} registrations inserted ({len(keep_ids):,} unique IDs kept)")

    # ── Subject matters ──────────────────────────────────────────────────────
    log("Reading Registration_SubjectMattersExport.csv ...")
    n_rs = 0
    batch = []
    f, reader = open_csv(zf, "Registration_SubjectMattersExport.csv")
    for row in reader:
        rid_raw = clean(row.get("REG_ID_ENR", ""))
        code    = clean(row.get("SUBJECT_CODE_OBJET", ""))
        if not rid_raw.isdigit() or not code:
            continue
        rid = int(rid_raw)
        if rid not in keep_ids:
            continue
        batch.append((rid, code))
        if len(batch) >= BATCH:
            con.executemany("INSERT OR IGNORE INTO reg_subjects (reg_id,subject_code) VALUES (?,?)", batch)
            con.commit()
            n_rs += len(batch)
            batch.clear()
    if batch:
        con.executemany("INSERT OR IGNORE INTO reg_subjects (reg_id,subject_code) VALUES (?,?)", batch)
        con.commit()
        n_rs += len(batch)
    f.close()
    log(f"  {n_rs:,} registration subject records inserted")

    # ── Subject matters — V6 details (post-Oct 2024 registrations put their
    #    subject codes here instead, in a comma-separated column) ─────────────
    log("Reading Registration_SubjectMatterDetailsExport.csv ...")
    n_rs2 = 0
    n_rsd = 0
    batch = []
    detail_batch = []
    detail_ids: dict[str, int] = {}   # detail_text -> detail_id (dedupes ~10:1)
    ref_batch = []
    f, reader = open_csv(zf, "Registration_SubjectMatterDetailsExport.csv")
    for row in reader:
        rid_raw   = clean(row.get("REG_ID_ENR", ""))
        codes_raw = clean(row.get("ASSOC_SUBJECT_CODES_OBJET", ""))
        if not rid_raw.isdigit():
            continue
        rid = int(rid_raw)
        if rid not in keep_ids:
            continue
        for code in [c.strip() for c in codes_raw.split(",") if c.strip()]:
            batch.append((rid, code))
        detail = clean(row.get("DESCRIPTION", ""))
        if detail:
            did = detail_ids.get(detail)
            if did is None:
                did = len(detail_ids) + 1
                detail_ids[detail] = did
                ref_batch.append((did, detail))
            detail_batch.append((rid, did))
        if len(batch) >= BATCH:
            con.executemany("INSERT OR IGNORE INTO reg_subjects (reg_id,subject_code) VALUES (?,?)", batch)
            con.commit()
            n_rs2 += len(batch)
            batch.clear()
        if len(detail_batch) >= BATCH:
            con.executemany("INSERT INTO reg_detail_text (detail_id,detail_text) VALUES (?,?)", ref_batch)
            con.executemany("INSERT INTO reg_subject_details (reg_id,detail_id) VALUES (?,?)", detail_batch)
            con.commit()
            n_rsd += len(detail_batch)
            detail_batch.clear()
            ref_batch.clear()
    if batch:
        con.executemany("INSERT OR IGNORE INTO reg_subjects (reg_id,subject_code) VALUES (?,?)", batch)
        con.commit()
        n_rs2 += len(batch)
    if detail_batch:
        con.executemany("INSERT INTO reg_detail_text (detail_id,detail_text) VALUES (?,?)", ref_batch)
        con.executemany("INSERT INTO reg_subject_details (reg_id,detail_id) VALUES (?,?)", detail_batch)
        con.commit()
        n_rsd += len(detail_batch)
    f.close()
    log(f"  {n_rs2:,} additional subject records inserted (V6 details), "
        f"{n_rsd:,} detail links over {len(detail_ids):,} distinct texts")

    # ── Target government institutions (normalised via reg_inst_ref) ─────────
    log("Reading Registration_GovernmentInstExport.csv ...")
    n_ri = 0
    batch = []
    inst_ids: dict[str, int] = {}   # institution -> inst_id (only ~222 distinct)
    f, reader = open_csv(zf, "Registration_GovernmentInstExport.csv")
    for row in reader:
        rid_raw = clean(row.get("REG_ID_ENR", ""))
        inst    = clean(row.get("INSTITUTION", ""))
        if not rid_raw.isdigit() or not inst:
            continue
        rid = int(rid_raw)
        if rid not in keep_ids:
            continue
        iid = inst_ids.get(inst)
        if iid is None:
            iid = len(inst_ids) + 1
            inst_ids[inst] = iid
        batch.append((rid, iid))
        if len(batch) >= BATCH:
            con.executemany("INSERT INTO reg_institutions (reg_id,inst_id) VALUES (?,?)", batch)
            con.commit()
            n_ri += len(batch)
            batch.clear()
    if batch:
        con.executemany("INSERT INTO reg_institutions (reg_id,inst_id) VALUES (?,?)", batch)
        con.commit()
        n_ri += len(batch)
    con.executemany("INSERT INTO reg_inst_ref (inst_id,institution) VALUES (?,?)",
                    [(v, k) for k, v in inst_ids.items()])
    con.commit()
    f.close()
    log(f"  {n_ri:,} registration institution records inserted ({len(inst_ids):,} distinct institutions)")

    return file_size, remote_last_modified


def build_org_first_seen(con):
    """Populate org_first_seen: the earliest appearance of each normalised org
    name across BOTH registrations (posted_date) and communications (comm_date).

    client_num is minted per consultant engagement, so it cannot tell whether an
    organization is genuinely new to the registry. Deduplicating by normalised
    name — and folding in communications so an org that only ever *met* officials
    still counts as previously-seen — lets us flag first-time organizations."""
    log("Building org_first_seen (first appearance per organization) ...")
    con.create_function("norm_name", 1, norm_name, deterministic=True)
    con.execute("""
        INSERT INTO org_first_seen (norm_name, first_date, display_name)
        SELECT norm, MIN(d), display_name FROM (
            SELECT norm_name AS norm, posted_date AS d, client_name AS display_name
            FROM registrations WHERE norm_name != '' AND posted_date != ''
            UNION ALL
            SELECT norm_name(client_name) AS norm, comm_date AS d, client_name AS display_name
            FROM communications WHERE client_name != '' AND comm_date != ''
        )
        GROUP BY norm
    """)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM org_first_seen").fetchone()[0]
    log(f"  {n:,} distinct organizations")


def compute_default_reg_stats(con):
    """Compute unfiltered registration stats and cache as JSON under 'default_reg_stats'.
    Mirrors compute_default_stats so the dashboard's default view is instant."""
    log("Computing default registration stats for cache...")

    row = con.execute("""
        SELECT COUNT(*)                            AS total,
               SUM(is_original)                    AS new_regs,
               COUNT(DISTINCT client_num)          AS unique_clients,
               COUNT(DISTINCT reg_num_dclrnt)      AS unique_lobbyists
        FROM registrations
    """).fetchone()
    result = {
        "total": row[0], "new_regs": row[1] or 0,
        "renewals": row[0] - (row[1] or 0),
        "unique_clients": row[2], "unique_lobbyists": row[3],
    }
    result["unique_firms"] = con.execute(
        "SELECT COUNT(DISTINCT firm_name) FROM registrations WHERE firm_name != ''"
    ).fetchone()[0]
    result["unique_orgs"] = con.execute(
        "SELECT COUNT(DISTINCT norm_name) FROM registrations WHERE norm_name != ''"
    ).fetchone()[0]

    # First-time organizations: a registration is an org's debut when it is the
    # org's earliest appearance anywhere (o.first_date == this reg's posted_date).
    result["first_time_orgs"] = con.execute("""
        SELECT COUNT(DISTINCT r.norm_name)
        FROM registrations r JOIN org_first_seen o ON o.norm_name = r.norm_name
        WHERE r.norm_name != '' AND o.first_date = r.posted_date
    """).fetchone()[0]

    by_month = con.execute("""
        SELECT r.posted_month, COUNT(*), SUM(r.is_original),
               COUNT(DISTINCT CASE WHEN o.first_date = r.posted_date THEN r.norm_name END)
        FROM registrations r LEFT JOIN org_first_seen o ON o.norm_name = r.norm_name
        GROUP BY r.posted_month ORDER BY r.posted_month
    """).fetchall()
    result["by_month"] = [
        {"month": r[0], "count": r[1], "new": r[2] or 0, "first_time": r[3] or 0}
        for r in by_month
    ]

    result["top_firms"] = [
        {"firm_name": r[0], "count": r[1]} for r in con.execute("""
            SELECT firm_name, COUNT(*) AS cnt FROM registrations
            WHERE firm_name != '' GROUP BY firm_name ORDER BY cnt DESC LIMIT 20
        """).fetchall()
    ]
    result["top_clients"] = [
        {"client_name": r[0], "count": r[1]} for r in con.execute("""
            SELECT client_name, COUNT(*) AS cnt FROM registrations
            WHERE client_name != '' GROUP BY client_name ORDER BY cnt DESC LIMIT 20
        """).fetchall()
    ]
    result["top_subjects"] = [
        {"subject_code": r[0], "description": r[1], "count": r[2]} for r in con.execute("""
            SELECT rs.subject_code, st.description, COUNT(DISTINCT rs.reg_id) AS cnt
            FROM reg_subjects rs JOIN subject_types st ON st.subject_code = rs.subject_code
            WHERE rs.subject_code != ''
            GROUP BY rs.subject_code ORDER BY cnt DESC
        """).fetchall()
    ]
    result["top_institutions"] = [
        {"institution": r[0], "count": r[1]} for r in con.execute("""
            SELECT rir.institution, COUNT(DISTINCT ri.reg_id) AS cnt
            FROM reg_institutions ri JOIN reg_inst_ref rir ON rir.inst_id = ri.inst_id
            GROUP BY rir.institution ORDER BY cnt DESC LIMIT 20
        """).fetchall()
    ]

    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("default_reg_stats", json.dumps(result)))
    con.commit()
    log(f"  Done ({result['total']:,} registrations, {result['new_regs']:,} new)")


def build():
    zf, file_size, remote_last_modified = download_zip(COMMS_URL, "communications_ocl_cal.zip")
    log(f"Remote Last-Modified: {remote_last_modified or '(unknown)'}")
    log(f"File size: {file_size:,} bytes")

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
            is_amendment INTEGER,
            norm_name    TEXT      -- normalised client_name (cross-links to registrations)
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
        CREATE TABLE registrations (
            reg_id         INTEGER PRIMARY KEY,  -- one row per registration version
            reg_num        TEXT,     -- '{registrant}-{client}-{version}'
            reg_type       INTEGER,  -- 1 Consultant, 2 In-house Corp, 3 In-house Org
            version_code   TEXT,
            firm_name      TEXT,     -- consultant firm ('' for in-house)
            reg_num_dclrnt TEXT,     -- registrant (lobbyist) id
            reg_last       TEXT,
            reg_first      TEXT,
            client_num     TEXT,
            client_name    TEXT,
            effective_date TEXT,
            end_date       TEXT,
            posted_date    TEXT,     -- publication date (indexed; primary sort/filter)
            posted_year    INTEGER,
            posted_month   TEXT,
            is_original    INTEGER,  -- 1 when no predecessor (a newly-filed registration)
            govt_fund_ind  TEXT,
            contg_fee_ind  TEXT,
            coalition_ind  TEXT,
            norm_name      TEXT      -- normalised client_name (see org_first_seen)
        );
        CREATE TABLE org_first_seen (
            norm_name    TEXT PRIMARY KEY,  -- normalised organization name
            first_date   TEXT,   -- earliest appearance across registrations + communications
            display_name TEXT    -- a representative original client_name
        );
        CREATE TABLE reg_subjects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            reg_id       INTEGER,
            subject_code TEXT,
            UNIQUE(reg_id, subject_code)
        );
        -- Target institutions are normalised: only ~222 distinct values, so an
        -- integer FK to reg_inst_ref replaces a repeated long string across ~1.25M rows.
        CREATE TABLE reg_inst_ref (
            inst_id      INTEGER PRIMARY KEY,
            institution  TEXT UNIQUE
        );
        CREATE TABLE reg_institutions (
            reg_id       INTEGER,
            inst_id      INTEGER
        );
        -- Subject-matter free-text is normalised too: ~56k distinct texts are
        -- restated across ~563k registration versions, so store each text once.
        CREATE TABLE reg_detail_text (
            detail_id    INTEGER PRIMARY KEY,
            detail_text  TEXT UNIQUE
        );
        CREATE TABLE reg_subject_details (
            reg_id       INTEGER,
            detail_id    INTEGER
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
        client_name = clean(row.get("EN_CLIENT_ORG_CORP_NM_AN", ""))

        batch.append((
            cid,
            clean(row.get("CLIENT_ORG_CORP_NUM", "")),
            client_name,
            clean(row.get("REGISTRANT_NUM_DECLARANT", "")),
            clean(row.get("RGSTRNT_LAST_NM_DCLRNT", "")),
            clean(row.get("RGSTRNT_1ST_NM_PRENOM_DCLRNT", "")),
            comm_date,
            int(comm_date[:4]),
            comm_date[:7],
            int(reg_type_raw) if reg_type_raw else 0,
            1 if prev else 0,
            norm_name(client_name),
        ))

        if len(batch) >= BATCH:
            con.executemany("INSERT INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            con.commit()
            n_primary += len(batch)
            batch.clear()

    if batch:
        con.executemany("INSERT INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
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

    # ── 4b. Registrations (separate open-data ZIP) ────────────────────────────
    reg_file_size, reg_last_modified = build_registrations(con)

    # ── 4c. First-appearance-per-organization (name-deduplicated) ─────────────
    build_org_first_seen(con)

    # ── 5. Meta ───────────────────────────────────────────────────────────────
    import datetime
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("source_last_modified", remote_last_modified))
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("source_file_size", str(file_size)))
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("built_at", datetime.datetime.utcnow().isoformat()))
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("reg_source_last_modified", reg_last_modified))
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                ("reg_source_file_size", str(reg_file_size)))
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
        CREATE INDEX idx_c_date    ON communications(comm_date DESC);
        CREATE INDEX idx_d_comlog  ON dpoh(comlog_id);
        CREATE INDEX idx_d_inst    ON dpoh(institution);
        CREATE INDEX idx_d_inst_comlog ON dpoh(institution, comlog_id);
        CREATE INDEX idx_d_name    ON dpoh(dpoh_last, dpoh_first);
        CREATE INDEX idx_s_comlog  ON subjects(comlog_id);
        CREATE INDEX idx_s_code    ON subjects(subject_code);
        CREATE INDEX idx_sd_comlog ON subject_details(comlog_id);
        CREATE INDEX idx_r_posted  ON registrations(posted_date DESC);
        CREATE INDEX idx_r_orig    ON registrations(is_original);
        CREATE INDEX idx_r_regtype ON registrations(reg_type);
        CREATE INDEX idx_r_client  ON registrations(client_name COLLATE NOCASE);
        CREATE INDEX idx_r_firm    ON registrations(firm_name COLLATE NOCASE);
        CREATE INDEX idx_rs_regid  ON reg_subjects(reg_id);
        CREATE INDEX idx_rs_code   ON reg_subjects(subject_code);
        CREATE INDEX idx_ri_regid  ON reg_institutions(reg_id);
        CREATE INDEX idx_ri_instid ON reg_institutions(inst_id);
        CREATE INDEX idx_r_norm    ON registrations(norm_name);
        CREATE INDEX idx_ofs_first ON org_first_seen(first_date);
        CREATE INDEX idx_c_norm    ON communications(norm_name);
        CREATE INDEX idx_rsd_regid ON reg_subject_details(reg_id);
    """)
    compute_default_stats(con)
    compute_default_reg_stats(con)
    con.close()

    size_mb = DB_PATH.stat().st_size / 1e6
    log(f"Done. lobby.db = {size_mb:.1f} MB")


if __name__ == "__main__":
    build()
