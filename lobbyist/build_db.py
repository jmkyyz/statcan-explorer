#!/usr/bin/env python3
"""
build_db.py
-----------
Downloads the Office of the Commissioner of Lobbying open data,
filters communications to 2014-onwards, and builds lobby.db (SQLite).

Run during Render's build step, or locally to refresh the database:
    python build_db.py
"""

import io
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import requests

COMMS_URL = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
DB_PATH = Path(__file__).parent / "lobby.db"
MIN_DATE = "2014-01-01"

CHUNKSIZE = 50_000


def download_zip(url: str) -> zipfile.ZipFile:
    print(f"Downloading {url} ...")
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    print(f"  {len(r.content) / 1e6:.1f} MB downloaded")
    return zipfile.ZipFile(io.BytesIO(r.content))


def read_csv(zf: zipfile.ZipFile, name: str, **kwargs) -> pd.DataFrame:
    with zf.open(name) as f:
        df = pd.read_csv(f, dtype=str, encoding="utf-8-sig", na_filter=False, **kwargs)
    df.columns = [c.strip() for c in df.columns]
    df.replace("null", "", inplace=True)
    return df


def build():
    zf = download_zip(COMMS_URL)

    # ── Primary export ──────────────────────────────────────────────────────
    print("Reading Communication_PrimaryExport.csv ...")
    primary = read_csv(
        zf,
        "Communication_PrimaryExport.csv",
        usecols=[
            "COMLOG_ID", "CLIENT_ORG_CORP_NUM", "EN_CLIENT_ORG_CORP_NM_AN",
            "REGISTRANT_NUM_DECLARANT", "RGSTRNT_LAST_NM_DCLRNT",
            "RGSTRNT_1ST_NM_PRENOM_DCLRNT", "COMM_DATE", "REG_TYPE_ENR",
            "PREV_COMLOG_ID_PRECEDNT",
        ],
    )
    primary = primary[primary["COMM_DATE"] >= MIN_DATE].copy()
    primary["comm_year"]  = primary["COMM_DATE"].str[:4].astype(int)
    primary["comm_month"] = primary["COMM_DATE"].str[:7]
    primary["is_amendment"] = (primary["PREV_COMLOG_ID_PRECEDNT"] != "").astype(int)
    print(f"  {len(primary):,} rows (2014+)")

    valid_ids = set(primary["COMLOG_ID"])

    # ── DPOH export ─────────────────────────────────────────────────────────
    print("Reading Communication_DpohExport.csv ...")
    dpoh_chunks = []
    with zf.open("Communication_DpohExport.csv") as f:
        for chunk in pd.read_csv(
            f, dtype=str, encoding="utf-8-sig", na_filter=False, chunksize=CHUNKSIZE
        ):
            chunk.columns = [c.strip() for c in chunk.columns]
            chunk.replace("null", "", inplace=True)
            dpoh_chunks.append(chunk[chunk["COMLOG_ID"].isin(valid_ids)])
    dpoh = pd.concat(dpoh_chunks, ignore_index=True)
    print(f"  {len(dpoh):,} rows")

    # ── Subject matters export ───────────────────────────────────────────────
    print("Reading Communication_SubjectMattersExport.csv ...")
    subj_chunks = []
    with zf.open("Communication_SubjectMattersExport.csv") as f:
        for chunk in pd.read_csv(
            f, dtype=str, encoding="utf-8-sig", na_filter=False, chunksize=CHUNKSIZE
        ):
            chunk.columns = [c.strip() for c in chunk.columns]
            chunk.replace("null", "", inplace=True)
            subj_chunks.append(chunk[chunk["COMLOG_ID"].isin(valid_ids)])
    subjects = pd.concat(subj_chunks, ignore_index=True)
    subjects = subjects[subjects["SUBJECT_CODE_OBJET"] != ""]
    print(f"  {len(subjects):,} rows")

    # ── Subject matter type codes ────────────────────────────────────────────
    print("Reading Codes_SubjectMatterTypesExport.csv ...")
    smt = read_csv(zf, "Codes_SubjectMatterTypesExport.csv")
    print(f"  {len(smt):,} codes")

    # ── Build SQLite ─────────────────────────────────────────────────────────
    print(f"Building {DB_PATH} ...")
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.executescript("""
        PRAGMA journal_mode=WAL;

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
    """)

    # Insert in batches for speed
    con.executemany(
        "INSERT INTO communications VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                int(r.COMLOG_ID),
                r.CLIENT_ORG_CORP_NUM,
                r.EN_CLIENT_ORG_CORP_NM_AN,
                r.REGISTRANT_NUM_DECLARANT,
                r.RGSTRNT_LAST_NM_DCLRNT,
                r.RGSTRNT_1ST_NM_PRENOM_DCLRNT,
                r.COMM_DATE,
                int(r.comm_year),
                r.comm_month,
                int(r.REG_TYPE_ENR) if r.REG_TYPE_ENR else 0,
                int(r.is_amendment),
            )
            for r in primary.itertuples(index=False)
        ],
    )
    print(f"  {len(primary):,} communications inserted")

    con.executemany(
        "INSERT INTO dpoh (comlog_id,dpoh_last,dpoh_first,dpoh_title,branch,institution) VALUES (?,?,?,?,?,?)",
        [
            (
                int(r.COMLOG_ID),
                r.DPOH_LAST_NM_TCPD,
                r.DPOH_FIRST_NM_PRENOM_TCPD,
                r.DPOH_TITLE_TITRE_TCPD,
                r.BRANCH_UNIT_DIRECTION_SERVICE,
                r.INSTITUTION,
            )
            for r in dpoh.itertuples(index=False)
        ],
    )
    print(f"  {len(dpoh):,} DPOH records inserted")

    con.executemany(
        "INSERT INTO subjects (comlog_id,subject_code) VALUES (?,?)",
        [
            (int(r.COMLOG_ID), r.SUBJECT_CODE_OBJET)
            for r in subjects.itertuples(index=False)
        ],
    )
    print(f"  {len(subjects):,} subject records inserted")

    con.executemany(
        "INSERT INTO subject_types VALUES (?,?)",
        [(r.SUBJECT_CODE_OBJET, r.SMT_EN_DESC) for r in smt.itertuples(index=False)],
    )

    # ── Indexes ──────────────────────────────────────────────────────────────
    cur.executescript("""
        CREATE INDEX idx_c_year     ON communications(comm_year);
        CREATE INDEX idx_c_month    ON communications(comm_month);
        CREATE INDEX idx_c_client   ON communications(client_name COLLATE NOCASE);
        CREATE INDEX idx_c_cnum     ON communications(client_num);
        CREATE INDEX idx_c_regtype  ON communications(reg_type);
        CREATE INDEX idx_c_regnum   ON communications(reg_num);
        CREATE INDEX idx_d_comlog   ON dpoh(comlog_id);
        CREATE INDEX idx_d_inst     ON dpoh(institution);
        CREATE INDEX idx_d_name     ON dpoh(dpoh_last, dpoh_first);
        CREATE INDEX idx_s_comlog   ON subjects(comlog_id);
        CREATE INDEX idx_s_code     ON subjects(subject_code);
    """)

    con.commit()
    con.close()

    size_mb = DB_PATH.stat().st_size / 1e6
    print(f"Done. lobby.db = {size_mb:.1f} MB")


if __name__ == "__main__":
    build()
