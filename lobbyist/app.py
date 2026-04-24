#!/usr/bin/env python3
"""
app.py — Lobbyist Registry Explorer
Flask server: serves the HTML frontend and query API backed by lobby.db.
"""

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import requests as http_requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH = Path(__file__).parent / "lobby.db"
PORT = int(os.environ.get("PORT", 5002))
COMMS_ZIP_URL = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
RENDER_DEPLOY_HOOK = os.environ.get("RENDER_DEPLOY_HOOK", "")


# ── DB connection ────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    if not DB_PATH.exists():
        raise RuntimeError("lobby.db not found — run build_db.py first")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ── Simple in-memory cache ───────────────────────────────────────────────────

_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL = 1800  # 30 minutes


def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() < entry["exp"]:
            return entry["val"]
    return None


def _cache_set(key: str, val):
    with _cache_lock:
        _cache[key] = {"val": val, "exp": time.time() + CACHE_TTL}


# ── Filter helpers ───────────────────────────────────────────────────────────

def build_filter_select(params: dict):
    """
    Returns (inner_sql, binds) — the SELECT DISTINCT comlog_id query
    matching all active filters.  Used both for CTE and temp-table approaches.
    """
    date_from   = (params.get("date_from") or "2014-01").strip()
    date_to     = (params.get("date_to")   or "2099-12").strip()
    client_q    = (params.get("client_q")  or "").strip()
    reg_type    = (params.get("reg_type")  or "").strip()
    institution = (params.get("institution") or "").strip()
    subject     = (params.get("subject")   or "").strip()
    dpoh_q      = (params.get("dpoh_q")    or "").strip()

    joins  = []
    wheres = ["c.comm_month BETWEEN ? AND ?"]
    binds  = [date_from, date_to]

    if client_q:
        wheres.append("c.client_name LIKE ? COLLATE NOCASE")
        binds.append(f"%{client_q}%")

    if reg_type:
        wheres.append("c.reg_type = ?")
        binds.append(int(reg_type))

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

    sql = (
        f"SELECT DISTINCT c.comlog_id "
        f"FROM communications c {' '.join(joins)} "
        f"WHERE {' AND '.join(wheres)}"
    )
    return sql, binds


def build_filtered_cte(params: dict):
    inner, binds = build_filter_select(params)
    return f"WITH filtered_ids AS ({inner})\n", binds


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
    cached = _cache_get("__subjects__")
    if cached is not None:
        return jsonify(cached)
    with get_db() as con:
        rows = con.execute(
            "SELECT subject_code, description FROM subject_types ORDER BY description"
        ).fetchall()
    result = rows_to_list(rows)
    _cache_set("__subjects__", result)
    return jsonify(result)


@app.route("/api/institutions")
def institutions():
    cached = _cache_get("__institutions__")
    if cached is not None:
        return jsonify(cached)
    with get_db() as con:
        rows = con.execute(
            """SELECT institution, COUNT(DISTINCT comlog_id) AS comm_count
               FROM dpoh WHERE institution != ''
               GROUP BY institution ORDER BY comm_count DESC"""
        ).fetchall()
    result = rows_to_list(rows)
    _cache_set("__institutions__", result)
    return jsonify(result)


@app.route("/api/clients")
def clients():
    q = (request.args.get("q") or "").strip()
    with get_db() as con:
        if q:
            rows = con.execute(
                """SELECT DISTINCT client_name, client_num FROM communications
                   WHERE client_name LIKE ? COLLATE NOCASE
                   ORDER BY client_name LIMIT 50""",
                (f"%{q}%",),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT DISTINCT client_name, client_num FROM communications
                   ORDER BY client_name LIMIT 200"""
            ).fetchall()
    return jsonify(rows_to_list(rows))


# ── Stats ─────────────────────────────────────────────────────────────────────

def _compute_stats(params: dict) -> dict:
    """
    Run all analytics queries for the given filter params.
    Uses a temp table so the expensive filter join runs only once,
    then all 7 aggregations scan the small materialised result.
    """
    inner_sql, binds = build_filter_select(params)

    with get_db() as con:
        # Materialise filtered IDs once — the only expensive operation
        con.execute(f"CREATE TEMP TABLE _fids AS {inner_sql}", binds)
        con.execute("CREATE INDEX _fids_idx ON _fids(comlog_id)")

        row = con.execute("""
            SELECT COUNT(*)                     AS total,
                   COUNT(DISTINCT c.client_num) AS unique_clients,
                   COUNT(DISTINCT c.reg_num)    AS unique_lobbyists
            FROM _fids fi
            JOIN communications c ON c.comlog_id = fi.comlog_id
        """).fetchone()
        totals = dict(row)

        totals["unique_dpoh"] = con.execute("""
            SELECT COUNT(DISTINCT d.dpoh_last || ',' || d.dpoh_first)
            FROM _fids fi
            JOIN dpoh d ON d.comlog_id = fi.comlog_id
            WHERE d.dpoh_last != ''
        """).fetchone()[0]

        by_month = con.execute("""
            SELECT c.comm_month AS month, COUNT(*) AS count
            FROM _fids fi
            JOIN communications c ON c.comlog_id = fi.comlog_id
            GROUP BY c.comm_month ORDER BY c.comm_month
        """).fetchall()

        top_clients = con.execute("""
            SELECT c.client_name, COUNT(*) AS count
            FROM _fids fi
            JOIN communications c ON c.comlog_id = fi.comlog_id
            WHERE c.client_name != ''
            GROUP BY c.client_name ORDER BY count DESC LIMIT 20
        """).fetchall()

        top_institutions = con.execute("""
            SELECT d.institution, COUNT(DISTINCT fi.comlog_id) AS count
            FROM _fids fi
            JOIN dpoh d ON d.comlog_id = fi.comlog_id
            WHERE d.institution != ''
            GROUP BY d.institution ORDER BY count DESC LIMIT 20
        """).fetchall()

        top_subjects = con.execute("""
            SELECT s.subject_code, st.description, COUNT(DISTINCT fi.comlog_id) AS count
            FROM _fids fi
            JOIN subjects s ON s.comlog_id = fi.comlog_id
            JOIN subject_types st ON st.subject_code = s.subject_code
            WHERE s.subject_code != ''
            GROUP BY s.subject_code ORDER BY count DESC
        """).fetchall()

        top_dpoh = con.execute("""
            SELECT d.dpoh_first || ' ' || d.dpoh_last AS name,
                   d.dpoh_title AS title,
                   d.institution,
                   COUNT(DISTINCT fi.comlog_id) AS count
            FROM _fids fi
            JOIN dpoh d ON d.comlog_id = fi.comlog_id
            WHERE d.dpoh_last != ''
            GROUP BY d.dpoh_last, d.dpoh_first, d.institution
            ORDER BY count DESC LIMIT 20
        """).fetchall()

    return {
        **totals,
        "by_month":         rows_to_list(by_month),
        "top_clients":      rows_to_list(top_clients),
        "top_institutions": rows_to_list(top_institutions),
        "top_subjects":     rows_to_list(top_subjects),
        "top_dpoh":         rows_to_list(top_dpoh),
    }


@app.route("/api/stats")
def stats():
    params = {k: v for k, v in request.args.items() if v}
    key = str(sorted(params.items()))

    cached = _cache_get(key)
    if cached is not None:
        return jsonify(cached)

    result = _compute_stats(params)
    _cache_set(key, result)
    return jsonify(result)


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
                GROUP_CONCAT(DISTINCT st.description)    AS subjects,
                GROUP_CONCAT(sd.detail_text, ' || ')           AS subject_details
            FROM filtered_ids fi
            JOIN communications c  ON c.comlog_id  = fi.comlog_id
            LEFT JOIN dpoh d       ON d.comlog_id  = fi.comlog_id
            LEFT JOIN subjects s   ON s.comlog_id  = fi.comlog_id
            LEFT JOIN subject_types st ON st.subject_code = s.subject_code
            LEFT JOIN subject_details sd ON sd.comlog_id = fi.comlog_id
            GROUP BY fi.comlog_id
            ORDER BY c.comm_date DESC
            LIMIT ? OFFSET ?
            """,
            binds + [limit, offset],
        ).fetchall()

    return jsonify({"total": total, "rows": rows_to_list(rows)})


# ── Update check ─────────────────────────────────────────────────────────────

@app.route("/api/check-update")
def check_update():
    try:
        r = http_requests.head(COMMS_ZIP_URL, timeout=15)
        remote_lm = r.headers.get("Last-Modified", "")
    except Exception as e:
        return jsonify({"error": f"HEAD request failed: {e}"}), 502

    with get_db() as con:
        row = con.execute(
            "SELECT value FROM meta WHERE key = 'source_last_modified'"
        ).fetchone()
        local_lm = row[0] if row else ""

        built_row = con.execute(
            "SELECT value FROM meta WHERE key = 'built_at'"
        ).fetchone()
        built_at = built_row[0] if built_row else ""

    update_available = bool(remote_lm and remote_lm != local_lm)
    return jsonify({
        "update_available": update_available,
        "remote_last_modified": remote_lm,
        "local_last_modified": local_lm,
        "built_at": built_at,
    })


@app.route("/api/trigger-update", methods=["POST"])
def trigger_update():
    if not RENDER_DEPLOY_HOOK:
        return jsonify({"error": "RENDER_DEPLOY_HOOK not configured"}), 503
    try:
        r = http_requests.post(RENDER_DEPLOY_HOOK, timeout=15)
        r.raise_for_status()
        return jsonify({"status": "deploy triggered"})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── Pre-warm cache on startup ─────────────────────────────────────────────────

def _prewarm():
    """Pre-warm subjects, institutions, and default stats so first page load is fast."""
    time.sleep(3)  # let Flask finish starting
    try:
        import datetime
        print("Pre-warming cache...", flush=True)

        # Subjects and institutions (static within a deployment)
        with get_db() as con:
            subj = rows_to_list(con.execute(
                "SELECT subject_code, description FROM subject_types ORDER BY description"
            ).fetchall())
            inst = rows_to_list(con.execute(
                """SELECT institution, COUNT(DISTINCT comlog_id) AS comm_count
                   FROM dpoh WHERE institution != ''
                   GROUP BY institution ORDER BY comm_count DESC"""
            ).fetchall())
        _cache_set("__subjects__", subj)
        _cache_set("__institutions__", inst)

        # Stats with the default params the frontend sends on load
        now = datetime.datetime.utcnow()
        default_params = {
            "date_from": "2014-01",
            "date_to": f"{now.year}-{now.month:02d}",
        }
        result = _compute_stats(default_params)
        _cache_set(str(sorted(default_params.items())), result)

        print("Cache ready.", flush=True)
    except Exception as e:
        print(f"Pre-warm failed: {e}", flush=True)


threading.Thread(target=_prewarm, daemon=True).start()


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
