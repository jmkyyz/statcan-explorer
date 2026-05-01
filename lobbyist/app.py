#!/usr/bin/env python3
"""
app.py — Lobbyist Registry Explorer
Flask server: serves the HTML frontend and query API backed by lobby.db.
"""

import datetime
import json
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

try:
    from curl_cffi import requests as cffi_requests
    _HAVE_CFFI = True
except ImportError:
    _HAVE_CFFI = False


# ── DB connection ────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    if not DB_PATH.exists():
        raise RuntimeError("lobby.db not found — run build_db.py first")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA cache_size = -4096")   # 4 MB page cache (results cached in Python)
    try:
        yield con
    finally:
        con.close()


def _ensure_indexes():
    """Add performance indexes that may be missing from older DB builds."""
    try:
        with get_db() as con:
            existing = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()}
            if "idx_c_date" not in existing:
                print("Adding idx_c_date index...", flush=True)
                con.execute("CREATE INDEX idx_c_date ON communications(comm_date DESC)")
                con.commit()
            if "idx_d_inst_comlog" not in existing:
                print("Adding idx_d_inst_comlog index...", flush=True)
                con.execute("CREATE INDEX idx_d_inst_comlog ON dpoh(institution, comlog_id)")
                con.commit()
    except Exception as e:
        print(f"Index migration failed: {e}", flush=True)


def rows_to_list(rows):
    return [dict(r) for r in rows]


# ── Simple in-memory cache ───────────────────────────────────────────────────

_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_TTL = 1800   # 30 minutes
CACHE_MAX = 100    # evict oldest entries beyond this limit


def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() < entry["exp"]:
            return entry["val"]
    return None


def _cache_set(key: str, val):
    with _cache_lock:
        _cache[key] = {"val": val, "exp": time.time() + CACHE_TTL}
        if len(_cache) > CACHE_MAX:
            # Evict the entry with the earliest expiry
            oldest = min(_cache, key=lambda k: _cache[k]["exp"])
            del _cache[oldest]


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
            patched = con.execute(
                "SELECT value FROM meta WHERE key='patched_at'"
            ).fetchone()
            patch_count = con.execute(
                "SELECT value FROM meta WHERE key='patch_new_count'"
            ).fetchone()
        return jsonify({
            "status": "ok",
            "total_comms": total,
            "date_range": [min_d, max_d],
            "patched_at": patched[0] if patched else None,
            "patch_new_count": int(patch_count[0]) if patch_count else 0,
        })
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


def _is_default_params(params: dict) -> bool:
    """True when params represent an unfiltered 'all data' request."""
    extra = {k for k in params if k not in ("date_from", "date_to")}
    if extra:
        return False
    now = datetime.datetime.utcnow()
    current_month = f"{now.year}-{now.month:02d}"
    return (
        params.get("date_from", "2014-01") <= "2014-01"
        and params.get("date_to", "2099-12") >= current_month
    )


@app.route("/api/stats")
def stats():
    params = {k: v for k, v in request.args.items() if v}
    key = str(sorted(params.items()))

    cached = _cache_get(key)
    if cached is not None:
        return jsonify(cached)

    # Serve pre-computed stats from the DB for unfiltered requests
    if _is_default_params(params):
        with get_db() as con:
            row = con.execute(
                "SELECT value FROM meta WHERE key = 'default_stats'"
            ).fetchone()
        if row:
            result = json.loads(row[0])
            _cache_set(key, result)
            return jsonify(result)

    result = _compute_stats(params)
    _cache_set(key, result)
    return jsonify(result)


# ── Communications table (paginated) ─────────────────────────────────────────

@app.route("/api/communications")
def communications():
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    # Serve pre-warmed result for the default unfiltered first page
    filter_params = {k: v for k, v in request.args.items()
                     if k not in ("limit", "offset") and v}
    if offset == 0 and limit == 50 and _is_default_params(filter_params):
        cached = _cache_get("__default_comms__")
        if cached is not None:
            return jsonify(cached)

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
        # lobbycanada.gc.ca uses JA3 TLS fingerprint blocking — only curl_cffi
        # (Chrome impersonation) gets through. If not installed, skip check.
        if not _HAVE_CFFI:
            return jsonify({"update_available": False, "note": "curl_cffi not available"})
        r = cffi_requests.get(COMMS_ZIP_URL, impersonate="chrome", stream=True, timeout=15)
        r.raise_for_status()
        remote_lm = r.headers.get("Last-Modified", "")
        remote_cl = r.headers.get("Content-Length", "")
        r.close()
    except Exception as e:
        return jsonify({"error": f"Request failed: {e}"}), 502

    with get_db() as con:
        row = con.execute(
            "SELECT value FROM meta WHERE key = 'source_last_modified'"
        ).fetchone()
        local_lm = row[0] if row else ""

        size_row = con.execute(
            "SELECT value FROM meta WHERE key = 'source_file_size'"
        ).fetchone()
        local_size = size_row[0] if size_row else ""

        built_row = con.execute(
            "SELECT value FROM meta WHERE key = 'built_at'"
        ).fetchone()
        built_at = built_row[0] if built_row else ""

    # Primary signal: Last-Modified header; fallback: Content-Length vs stored size
    if remote_lm and local_lm:
        update_available = remote_lm != local_lm
    elif remote_cl and local_size:
        update_available = remote_cl != local_size
    else:
        update_available = False

    with get_db() as con:
        patched_row = con.execute(
            "SELECT value FROM meta WHERE key='patched_at'"
        ).fetchone()
        patch_count_row = con.execute(
            "SELECT value FROM meta WHERE key='patch_new_count'"
        ).fetchone()
    patched_at = patched_row[0] if patched_row else ""
    patch_new_count = int(patch_count_row[0]) if patch_count_row else 0

    return jsonify({
        "update_available": update_available,
        "remote_last_modified": remote_lm,
        "local_last_modified": local_lm,
        "remote_content_length": remote_cl,
        "local_file_size": local_size,
        "built_at": built_at,
        "patched_at": patched_at,
        "patch_new_count": patch_new_count,
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
    """Pre-compute all expensive queries so the first page load is instant."""
    try:
        print("Pre-warming cache...", flush=True)
        now = datetime.datetime.utcnow()

        with get_db() as con:
            subj = rows_to_list(con.execute(
                "SELECT subject_code, description FROM subject_types ORDER BY description"
            ).fetchall())

            inst = rows_to_list(con.execute(
                """SELECT institution, COUNT(DISTINCT comlog_id) AS comm_count
                   FROM dpoh WHERE institution != ''
                   GROUP BY institution ORDER BY comm_count DESC"""
            ).fetchall())

            stats_row = con.execute(
                "SELECT value FROM meta WHERE key = 'default_stats'"
            ).fetchone()

            # Pre-warm the default communications page — the slowest query on first load
            default_comms = rows_to_list(con.execute("""
                SELECT
                    c.comlog_id, c.comm_date, c.client_name,
                    c.reg_first || ' ' || c.reg_last AS lobbyist,
                    c.reg_type, c.is_amendment,
                    GROUP_CONCAT(DISTINCT
                        CASE WHEN d.dpoh_first != '' THEN d.dpoh_first || ' ' || d.dpoh_last
                             ELSE d.dpoh_last END
                    ) AS dpoh_names,
                    GROUP_CONCAT(DISTINCT d.institution) AS institutions,
                    GROUP_CONCAT(DISTINCT st.description) AS subjects,
                    GROUP_CONCAT(sd.detail_text, ' || ') AS subject_details
                FROM communications c
                LEFT JOIN dpoh d ON d.comlog_id = c.comlog_id
                LEFT JOIN subjects s ON s.comlog_id = c.comlog_id
                LEFT JOIN subject_types st ON st.subject_code = s.subject_code
                LEFT JOIN subject_details sd ON sd.comlog_id = c.comlog_id
                GROUP BY c.comlog_id
                ORDER BY c.comm_date DESC
                LIMIT 50 OFFSET 0
            """).fetchall())
            total_comms = con.execute("SELECT COUNT(*) FROM communications").fetchone()[0]

        _cache_set("__subjects__", subj)
        _cache_set("__institutions__", inst)
        _cache_set("__default_comms__", {"total": total_comms, "rows": default_comms})

        if stats_row:
            default_stats = json.loads(stats_row[0])
            default_params = {
                "date_from": "2014-01",
                "date_to": f"{now.year}-{now.month:02d}",
            }
            _cache_set(str(sorted(default_params.items())), default_stats)

        print("Cache ready.", flush=True)
    except Exception as e:
        print(f"Pre-warm failed: {e}", flush=True)


_ensure_indexes()
threading.Thread(target=_prewarm, daemon=True).start()


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
