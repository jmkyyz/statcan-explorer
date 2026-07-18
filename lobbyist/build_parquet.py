#!/usr/bin/env python3
"""
build_parquet.py — export the Registrations slice of lobby.db to Parquet.

First step of the static (Parquet + DuckDB-WASM) architecture: one
denormalized file the browser can query directly, replacing the
/api/reg-stats and /api/registrations server endpoints.

Subjects / institutions / detail texts are pipe-joined per registration —
the same shape app.py's _decorate_regs returns — so the whole Registrations
view runs off a single file. DuckDB unnests the pipe lists at query time for
the aggregation charts.

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
    meta = {
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": n,
        "posted_date_range": [lo, hi],
        "source_db": str(DB_PATH),
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    con.close()

    log(f"Done. {out.name} = {out.stat().st_size/1e6:.1f} MB, {n:,} rows, {lo} → {hi}")


if __name__ == "__main__":
    build()
