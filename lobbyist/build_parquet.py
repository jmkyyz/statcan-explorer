#!/usr/bin/env python3
"""
build_parquet.py — export lobby.db to the Parquet files behind the static
(DuckDB-WASM) frontend, replacing the Flask query endpoints.

Three files:
  registrations.parquet  — one denormalized row per registration (subjects /
                           institutions / detail texts pipe-joined, the same
                           shape app.py's _decorate_regs returns)
  communications.parquet — one denormalized row per communication report
                           (DPOH names / institutions / subjects pipe-joined,
                           matching _decorate_comms)
  dpoh.parquet           — one row per official per communication, for the
                           official-level aggregations the wide file can't
                           answer (top DPOHs with title+institution, unique-
                           DPOH counts)

DuckDB unnests the pipe-joined lists at query time for the aggregation charts.

Env overrides (match build_db.py conventions):
  LOBBY_DB_PATH    source SQLite DB   (default: ./lobby.db)
  PARQUET_OUT_DIR  output directory   (default: ./parquet)
"""

import datetime
import json
import os
from pathlib import Path

import duckdb

HERE    = Path(__file__).parent
DB_PATH = Path(os.environ.get("LOBBY_DB_PATH", HERE / "lobby.db"))
OUT_DIR = Path(os.environ.get("PARQUET_OUT_DIR", HERE / "parquet"))


def log(msg):
    print(f"[build_parquet] {msg}", flush=True)


def build():
    if not DB_PATH.exists():
        raise SystemExit(f"source DB not found: {DB_PATH}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "registrations.parquet"

    con = duckdb.connect()
    con.execute(f"ATTACH '{DB_PATH}' AS ldb (TYPE sqlite, READ_ONLY)")

    log("Denormalizing registrations ...")
    con.execute("""
        CREATE TEMP TABLE regs AS
        SELECT r.reg_id,
               r.reg_num,
               r.posted_date,
               r.posted_month,
               CAST(r.reg_type AS TINYINT)    AS reg_type,
               CAST(r.is_original AS TINYINT) AS is_original,
               CAST(CASE WHEN r.norm_name != '' AND o.first_date = r.posted_date
                    THEN 1 ELSE 0 END AS TINYINT) AS first_time_org,
               r.client_name,
               r.client_num,
               r.firm_name,
               trim(COALESCE(r.reg_first,'') || ' ' || COALESCE(r.reg_last,'')) AS lobbyist,
               r.effective_date,
               r.end_date,
               r.norm_name,
               COALESCE(cc.n, 0) AS comm_count,
               COALESCE(subj.s, '') AS subjects,
               COALESCE(inst.i, '') AS institutions,
               COALESCE(det.d, '') AS subject_details
        FROM ldb.registrations r
        LEFT JOIN ldb.org_first_seen o ON o.norm_name = r.norm_name
        LEFT JOIN (
            SELECT norm_name, COUNT(*) AS n
            FROM ldb.communications WHERE norm_name != '' GROUP BY norm_name
        ) cc ON cc.norm_name = r.norm_name
        LEFT JOIN (
            SELECT rs.reg_id,
                   array_to_string(list_distinct(list(st.description)), '|') AS s
            FROM ldb.reg_subjects rs
            JOIN ldb.subject_types st ON st.subject_code = rs.subject_code
            GROUP BY rs.reg_id
        ) subj ON subj.reg_id = r.reg_id
        LEFT JOIN (
            SELECT ri.reg_id,
                   array_to_string(list_distinct(list(rir.institution)), '|') AS i
            FROM ldb.reg_institutions ri
            JOIN ldb.reg_inst_ref rir ON rir.inst_id = ri.inst_id
            GROUP BY ri.reg_id
        ) inst ON inst.reg_id = r.reg_id
        LEFT JOIN (
            SELECT sd.reg_id,
                   array_to_string(list_distinct(list(dt.detail_text)), ' || ') AS d
            FROM ldb.reg_subject_details sd
            JOIN ldb.reg_detail_text dt ON dt.detail_id = sd.detail_id
            GROUP BY sd.reg_id
        ) det ON det.reg_id = r.reg_id
    """)

    log("Writing parquet ...")
    # Sorted newest-first: the default table view reads only the first row
    # groups. ZSTD for size (this file ships to every browser once).
    con.execute(f"""
        COPY (SELECT * FROM regs ORDER BY posted_date DESC)
        TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 32768)
    """)

    n, lo, hi = con.execute(
        "SELECT COUNT(*), MIN(posted_date), MAX(posted_date) FROM regs"
    ).fetchone()
    log(f"{out.name} = {out.stat().st_size/1e6:.1f} MB, {n:,} rows, {lo} → {hi}")

    # ── Communications ───────────────────────────────────────────────────────
    comms_out = OUT_DIR / "communications.parquet"
    log("Denormalizing communications ...")
    con.execute("""
        CREATE TEMP TABLE comms AS
        SELECT c.comlog_id,
               c.comm_date,
               c.comm_month,
               CAST(c.reg_type AS TINYINT)     AS reg_type,
               CAST(c.is_amendment AS TINYINT) AS is_amendment,
               c.client_name,
               c.client_num,
               c.reg_num,
               trim(COALESCE(c.reg_first,'') || ' ' || COALESCE(c.reg_last,'')) AS lobbyist,
               c.norm_name,
               COALESCE(d.names, '') AS dpoh_names,
               COALESCE(d.insts, '') AS institutions,
               COALESCE(s.subj, '')  AS subjects,
               COALESCE(sd.det, '')  AS subject_details
        FROM ldb.communications c
        LEFT JOIN (
            SELECT comlog_id,
                   array_to_string(list_distinct(list(trim(COALESCE(dpoh_first,'') || ' ' || COALESCE(dpoh_last,'')))
                                   FILTER (WHERE trim(COALESCE(dpoh_first,'') || ' ' || COALESCE(dpoh_last,'')) != '')), '|') AS names,
                   array_to_string(list_distinct(list(institution) FILTER (WHERE institution != '')), '|') AS insts
            FROM ldb.dpoh GROUP BY comlog_id
        ) d ON d.comlog_id = c.comlog_id
        LEFT JOIN (
            SELECT su.comlog_id,
                   array_to_string(list_distinct(list(st.description)), '|') AS subj
            FROM ldb.subjects su
            JOIN ldb.subject_types st ON st.subject_code = su.subject_code
            GROUP BY su.comlog_id
        ) s ON s.comlog_id = c.comlog_id
        LEFT JOIN (
            SELECT comlog_id,
                   array_to_string(list_distinct(list(detail_text)), ' || ') AS det
            FROM ldb.subject_details GROUP BY comlog_id
        ) sd ON sd.comlog_id = c.comlog_id
    """)
    con.execute(f"""
        COPY (SELECT * FROM comms ORDER BY comm_date DESC)
        TO '{comms_out}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 32768)
    """)
    cn, clo, chi = con.execute(
        "SELECT COUNT(*), MIN(comm_date), MAX(comm_date) FROM comms"
    ).fetchone()
    log(f"{comms_out.name} = {comms_out.stat().st_size/1e6:.1f} MB, {cn:,} rows, {clo} → {chi}")

    # ── DPOH (official-level rows) ────────────────────────────────────────────
    dpoh_out = OUT_DIR / "dpoh.parquet"
    log("Exporting dpoh ...")
    # name_key mirrors app.py's distinct-DPOH key (last,first) exactly so
    # unique-official counts match the server; name is for display only.
    con.execute(f"""
        COPY (
            SELECT comlog_id,
                   COALESCE(dpoh_last,'') || ',' || COALESCE(dpoh_first,'') AS name_key,
                   trim(COALESCE(dpoh_first,'') || ' ' || COALESCE(dpoh_last,'')) AS name,
                   COALESCE(dpoh_title, '') AS title,
                   COALESCE(institution, '') AS institution
            FROM ldb.dpoh
            WHERE COALESCE(dpoh_last,'') != ''
            ORDER BY comlog_id DESC
        ) TO '{dpoh_out}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)
    """)
    dn = con.execute(f"SELECT COUNT(*) FROM '{dpoh_out}'").fetchone()[0]
    log(f"{dpoh_out.name} = {dpoh_out.stat().st_size/1e6:.1f} MB, {dn:,} rows")

    meta = {
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reg_rows": n,
        "posted_date_range": [lo, hi],
        "comm_rows": cn,
        "comm_date_range": [clo, chi],
        "source_db": str(DB_PATH),
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    con.close()

    total_mb = sum(f.stat().st_size for f in OUT_DIR.glob("*.parquet")) / 1e6
    log(f"Done. Total parquet payload = {total_mb:.1f} MB")


if __name__ == "__main__":
    build()
