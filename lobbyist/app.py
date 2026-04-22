#!/usr/bin/env python3
"""
app.py — Lobbyist Registry Explorer
Flask server: serves the HTML frontend and query API backed by lobby.db.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = Path(__file__).parent / "lobby.db"
PORT = int(os.environ.get("PORT", 5002))


# ── DB connection helpers ────────────────────────────────────────────────────

@contextmanager
def get_db():
    if not DB_PATH.exists():
        raise RuntimeError("lobby.db not found — run build_db.py first")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    try:
        yield con
    finally:
        con.close()


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ── Filter helpers ───────────────────────────────────────────────────────────

def build_filtered_cte(params: dict):
    """
    Returns (cte_sql, bind_params) that produces a CTE called filtered_ids
    containing the comlog_ids matching all active filters.
    """
    date_from  = (params.get("date_from") or "2014-01").strip()
    date_to    = (params.get("date_to")   or "2099-12").strip()
    client_q   = (params.get("client_q") or "").strip()
    reg_type   = (params.get("reg_type") or "").strip()
    institution = (params.get("institution") or "").strip()
    subject    = (params.get("subject") or "").strip()
    dpoh_q     = (params.get("dpoh_q") or "").strip()

    joins  = []
    wheres = ["c.comm_month BETWEEN ? AND ?"]
    binds  = [date_from, date_to]

    if client_q:
        wheres.append("c.client_name LIKE ? COLLATE NOCASE")
        binds.append(f"%{client_q}%")

    if reg_type:
        wheres.append("c.reg_type = ?")
        binds.append(int(reg_type))

    # Institution and DPOH filters both need the dpoh table joined once
    if institution or dpoh_q:
        joins.append("JOIN dpoh d ON c.comlog_id = d.comlog_id")

    if institution:
        wheres.append("d.institution = ?")
        binds.append(institution)

    if dpoh_q:
        wheres.append("(d.dpoh_last LIKE ? COLLATE NOCASE OR d.dpoh_first LIKE ? COLLATE NOCASE)")
        binds += [f"%{dpoh_q}%", f"%{dpoh_q}%"]

    if subject:
        joins.append("JOIN subjects s ON c.comlog_id = s.comlog_id")
        wheres.append("s.subject_code = ?")
        binds.append(subject)

    join_sql  = " ".join(joins)
    where_sql = " AND ".join(wheres)

    cte = f"""
        WITH filtered_ids AS (
            SELECT DISTINCT c.comlog_id
            FROM communications c
            {join_sql}
            WHERE {where_sql}
        )
    """
    return cte, binds


# ── Static frontend ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(Path(__file__).parent, "lobby-explorer.html")


# ── Health ───────────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    try:
        with get_db() as con:
            total = con.execute("SELECT COUNT(*) FROM communications").fetchone()[0]
            min_d = con.execute("SELECT MIN(comm_date) FROM communications").fetchone()[0]
            max_d = con.execute("SELECT MAX(comm_date) FROM communications").fetchone()[0]
        return jsonify({"status": "ok", "total_comms": total, "date_range": [min_d, max_d]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Filter-option endpoints ───────────────────────────────────────────────────

@app.route("/api/subjects")
def subjects():
    with get_db() as con:
        rows = con.execute(
            "SELECT subject_code, description FROM subject_types ORDER BY description"
        ).fetchall()
    return jsonify(rows_to_list(rows))


@app.route("/api/institutions")
def institutions():
    with get_db() as con:
        rows = con.execute(
            """SELECT institution, COUNT(DISTINCT comlog_id) AS comm_count
               FROM dpoh
               WHERE institution != ''
               GROUP BY institution
               ORDER BY comm_count DESC"""
        ).fetchall()
    return jsonify(rows_to_list(rows))


@app.route("/api/clients")
def clients():
    """Autocomplete: return up to 50 matching client names."""
    q = (request.args.get("q") or "").strip()
    with get_db() as con:
        if q:
            rows = con.execute(
                """SELECT DISTINCT client_name, client_num
                   FROM communications
                   WHERE client_name LIKE ? COLLATE NOCASE
                   ORDER BY client_name
                   LIMIT 50""",
                (f"%{q}%",),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT DISTINCT client_name, client_num
                   FROM communications
                   ORDER BY client_name
                   LIMIT 200"""
            ).fetchall()
    return jsonify(rows_to_list(rows))


# ── Stats (main analytics endpoint) ─────────────────────────────────────────

@app.route("/api/stats")
def stats():
    """
    Returns aggregated analytics for the current filter set:
      - totals (comms, unique clients, unique lobbyists, unique DPOHs)
      - by_month time series
      - top_clients, top_institutions, top_subjects, top_dpoh
    """
    cte, binds = build_filtered_cte(request.args)

    with get_db() as con:
        # Totals
        row = con.execute(
            cte + """
            SELECT
                COUNT(*)                            AS total,
                COUNT(DISTINCT c.client_num)        AS unique_clients,
                COUNT(DISTINCT c.reg_num)           AS unique_lobbyists
            FROM filtered_ids fi
            JOIN communications c ON c.comlog_id = fi.comlog_id
            """,
            binds,
        ).fetchone()
        totals = dict(row)

        # Unique DPOHs (separate query to keep things readable)
        dpoh_count = con.execute(
            cte + """
            SELECT COUNT(DISTINCT d.dpoh_last || ',' || d.dpoh_first) AS unique_dpoh
            FROM filtered_ids fi
            JOIN dpoh d ON d.comlog_id = fi.comlog_id
            WHERE d.dpoh_last != ''
            """,
            binds,
        ).fetchone()[0]
        totals["unique_dpoh"] = dpoh_count

        # By month
        by_month = con.execute(
            cte + """
            SELECT c.comm_month AS month, COUNT(*) AS count
            FROM filtered_ids fi
            JOIN communications c ON c.comlog_id = fi.comlog_id
            GROUP BY c.comm_month
            ORDER BY c.comm_month
            """,
            binds,
        ).fetchall()

        # Top clients (up to 20)
        top_clients = con.execute(
            cte + """
            SELECT c.client_name, COUNT(*) AS count
            FROM filtered_ids fi
            JOIN communications c ON c.comlog_id = fi.comlog_id
            WHERE c.client_name != ''
            GROUP BY c.client_name
            ORDER BY count DESC
            LIMIT 20
            """,
            binds,
        ).fetchall()

        # Top institutions (up to 20)
        top_institutions = con.execute(
            cte + """
            SELECT d.institution, COUNT(DISTINCT fi.comlog_id) AS count
            FROM filtered_ids fi
            JOIN dpoh d ON d.comlog_id = fi.comlog_id
            WHERE d.institution != ''
            GROUP BY d.institution
            ORDER BY count DESC
            LIMIT 20
            """,
            binds,
        ).fetchall()

        # Top subjects (all)
        top_subjects = con.execute(
            cte + """
            SELECT s.subject_code, st.description, COUNT(DISTINCT fi.comlog_id) AS count
            FROM filtered_ids fi
            JOIN subjects s ON s.comlog_id = fi.comlog_id
            JOIN subject_types st ON st.subject_code = s.subject_code
            WHERE s.subject_code != ''
            GROUP BY s.subject_code
            ORDER BY count DESC
            """,
            binds,
        ).fetchall()

        # Top DPOHs (up to 20)
        top_dpoh = con.execute(
            cte + """
            SELECT
                d.dpoh_first || ' ' || d.dpoh_last AS name,
                d.dpoh_title AS title,
                d.institution,
                COUNT(DISTINCT fi.comlog_id) AS count
            FROM filtered_ids fi
            JOIN dpoh d ON d.comlog_id = fi.comlog_id
            WHERE d.dpoh_last != ''
            GROUP BY d.dpoh_last, d.dpoh_first, d.institution
            ORDER BY count DESC
            LIMIT 20
            """,
            binds,
        ).fetchall()

    return jsonify({
        **totals,
        "by_month":         rows_to_list(by_month),
        "top_clients":      rows_to_list(top_clients),
        "top_institutions": rows_to_list(top_institutions),
        "top_subjects":     rows_to_list(top_subjects),
        "top_dpoh":         rows_to_list(top_dpoh),
    })


# ── Communications table (paginated) ─────────────────────────────────────────

@app.route("/api/communications")
def communications():
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    cte, binds = build_filtered_cte(request.args)

    with get_db() as con:
        total = con.execute(
            cte + "SELECT COUNT(*) FROM filtered_ids", binds
        ).fetchone()[0]

        rows = con.execute(
            cte + """
            SELECT
                c.comlog_id,
                c.comm_date,
                c.client_name,
                c.reg_first || ' ' || c.reg_last        AS lobbyist,
                c.reg_type,
                c.is_amendment,
                GROUP_CONCAT(DISTINCT
                    CASE WHEN d.dpoh_first != '' THEN d.dpoh_first || ' ' || d.dpoh_last
                         ELSE d.dpoh_last END
                )                                        AS dpoh_names,
                GROUP_CONCAT(DISTINCT d.institution)     AS institutions,
                GROUP_CONCAT(DISTINCT st.description)    AS subjects
            FROM filtered_ids fi
            JOIN communications c  ON c.comlog_id  = fi.comlog_id
            LEFT JOIN dpoh d       ON d.comlog_id  = fi.comlog_id
            LEFT JOIN subjects s   ON s.comlog_id  = fi.comlog_id
            LEFT JOIN subject_types st ON st.subject_code = s.subject_code
            GROUP BY fi.comlog_id
            ORDER BY c.comm_date DESC
            LIMIT ? OFFSET ?
            """,
            binds + [limit, offset],
        ).fetchall()

    return jsonify({"total": total, "rows": rows_to_list(rows)})


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
