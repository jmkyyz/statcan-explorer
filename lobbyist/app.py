#!/usr/bin/env python3
"""
app.py — Lobbyist Registry Explorer
Flask server: serves the HTML frontend and query API backed by lobby.db.
"""

import datetime
import json
import mimetypes
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

try:
    from flask_compress import Compress
    Compress(app)   # gzip/brotli on JSON + HTML responses
except ImportError:
    pass

# DB path is overridable so a scratch DB can be served during local verification
# without touching the live lobby.db.
DB_PATH = Path(os.environ.get("LOBBY_DB_PATH", Path(__file__).parent / "lobby.db"))
PORT = int(os.environ.get("PORT", 5002))
COMMS_ZIP_URL = "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip"
REGS_ZIP_URL  = "https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip"
RENDER_DEPLOY_HOOK = os.environ.get("RENDER_DEPLOY_HOOK", "")
# Version stamp the pipeline publishes beside lobby.db (see update_lobby_db.sh)
META_ASSET_URL = "https://github.com/jmkyyz/statcan-explorer/releases/download/db-latest/lobby-meta.json"

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
    con.execute("PRAGMA cache_size = -16384")    # 16 MB page cache
    con.execute("PRAGMA temp_store = MEMORY")    # temp tables (stats) stay in RAM
    con.execute("PRAGMA mmap_size = 268435456")  # 256 MB — reads served from shared OS page cache
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


_reg_table_flag: dict = {}


def _has_reg_tables(con) -> bool:
    """True if the registrations tables exist. Lets the app serve the
    communications view unharmed against an older DB that predates the
    registration schema (e.g. a deploy that grabbed a stale release DB)."""
    if "exists" not in _reg_table_flag:
        row = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='registrations'"
        ).fetchone()
        _reg_table_flag["exists"] = row[0] > 0
    return _reg_table_flag["exists"]


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


def _cache_set(key: str, val, ttl: int = CACHE_TTL):
    with _cache_lock:
        _cache[key] = {"val": val, "exp": time.time() + ttl}
        if len(_cache) > CACHE_MAX:
            # Evict the entry with the earliest expiry
            oldest = min(_cache, key=lambda k: _cache[k]["exp"])
            del _cache[oldest]


def _cached_json(payload, max_age: int):
    """jsonify + a browser/CDN Cache-Control header, for endpoints whose data
    only changes when the DB is rebuilt (i.e. at most daily)."""
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = f"public, max-age={max_age}"
    return resp


# ── Filter helpers ───────────────────────────────────────────────────────────

def _month_bounds(date_from: str, date_to: str):
    """Convert YYYY-MM bounds to a [start, end) comm_date range so queries
    filter and sort on the same indexed column (idx_c_date)."""
    try:
        y, m = int(date_to[:4]), int(date_to[5:7])
        end = f"{y + m // 12}-{m % 12 + 1:02d}-01"
    except (ValueError, IndexError):
        end = "2100-01-01"
    return f"{date_from}-01", end


def build_filter_parts(params: dict):
    """Returns (joins, wheres, binds) for the active filters."""
    date_from   = (params.get("date_from") or "2014-01").strip()
    date_to     = (params.get("date_to")   or "2099-12").strip()
    client_q    = (params.get("client_q")  or "").strip()
    client_exact = (params.get("client_exact") or "").strip()
    client_norm = (params.get("client_norm") or "").strip()
    reg_type    = (params.get("reg_type")  or "").strip()
    institution = (params.get("institution") or "").strip()
    subject     = (params.get("subject")   or "").strip()
    dpoh_q      = (params.get("dpoh_q")    or "").strip()

    start, end = _month_bounds(date_from, date_to)
    joins  = []
    wheres = ["c.comm_date >= ?", "c.comm_date < ?"]
    binds  = [start, end]

    if client_norm:
        # Normalised-name match — used by the "view this client's communications"
        # cross-link from the Registrations tab. Catches all of an organization's
        # communications regardless of which client_num/name variant they used.
        wheres.append("c.norm_name = ?")
        binds.append(client_norm)
    elif client_exact:
        # Exact match — reproduces the Top-Clients ranking (which groups by the
        # full name string) and avoids LIKE over-matching short names.
        # COLLATE NOCASE so idx_c_client (a NOCASE index) is usable; a binary =
        # would full-scan communications on every drill-down click.
        wheres.append("c.client_name = ? COLLATE NOCASE")
        binds.append(client_exact)
    elif client_q:
        wheres.append("c.client_name LIKE ? COLLATE NOCASE")
        binds.append(f"%{client_q}%")

    if reg_type:
        # Comma-separated list, e.g. "1,3" when two of the three boxes are checked
        types = [int(t) for t in reg_type.split(",") if t.strip()]
        wheres.append(f"c.reg_type IN ({','.join('?' * len(types))})")
        binds += types

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

    return joins, wheres, binds


def build_filter_select(params: dict):
    """The SELECT DISTINCT comlog_id query matching all active filters."""
    joins, wheres, binds = build_filter_parts(params)
    sql = (
        f"SELECT DISTINCT c.comlog_id "
        f"FROM communications c {' '.join(joins)} "
        f"WHERE {' AND '.join(wheres)}"
    )
    return sql, binds


# ── Registration filter helpers (parallel to communications above) ───────────

def build_reg_filter_parts(params: dict):
    """Returns (joins, wheres, binds) for the active registration filters.
    Filters and sorts on posted_date (the publication date)."""
    date_from    = (params.get("date_from") or "2014-01").strip()
    date_to      = (params.get("date_to")   or "2099-12").strip()
    client_q     = (params.get("client_q")  or "").strip()
    client_exact = (params.get("client_exact") or "").strip()
    firm_q       = (params.get("firm_q")    or "").strip()
    reg_type     = (params.get("reg_type")  or "").strip()
    institution  = (params.get("institution") or "").strip()
    subject      = (params.get("subject")   or "").strip()
    new_only     = (params.get("new_only")  or "").strip()
    first_time   = (params.get("first_time_only") or "").strip()

    start, end = _month_bounds(date_from, date_to)
    joins  = []
    wheres = ["r.posted_date >= ?", "r.posted_date < ?"]
    binds  = [start, end]

    if new_only in ("1", "true", "on", "yes"):
        wheres.append("r.is_original = 1")

    if first_time in ("1", "true", "on", "yes"):
        # Rows that are an organization's first-ever appearance in the registry
        joins.append("JOIN org_first_seen o ON o.norm_name = r.norm_name")
        wheres.append("r.norm_name != ''")
        wheres.append("o.first_date = r.posted_date")

    if client_exact:
        # NOCASE so idx_r_client (a NOCASE index) is usable — see the
        # communications counterpart above.
        wheres.append("r.client_name = ? COLLATE NOCASE")
        binds.append(client_exact)
    elif client_q:
        wheres.append("r.client_name LIKE ? COLLATE NOCASE")
        binds.append(f"%{client_q}%")

    if firm_q:
        wheres.append("r.firm_name LIKE ? COLLATE NOCASE")
        binds.append(f"%{firm_q}%")

    if reg_type:
        types = [int(t) for t in reg_type.split(",") if t.strip()]
        wheres.append(f"r.reg_type IN ({','.join('?' * len(types))})")
        binds += types

    if institution:
        joins.append("JOIN reg_institutions ri ON r.reg_id = ri.reg_id")
        wheres.append("ri.inst_id = (SELECT inst_id FROM reg_inst_ref WHERE institution = ?)")
        binds.append(institution)

    if subject:
        joins.append("JOIN reg_subjects rs ON r.reg_id = rs.reg_id")
        wheres.append("rs.subject_code = ?")
        binds.append(subject)

    return joins, wheres, binds


def build_reg_filter_select(params: dict):
    """The SELECT DISTINCT reg_id query matching all active registration filters."""
    joins, wheres, binds = build_reg_filter_parts(params)
    sql = (
        f"SELECT DISTINCT r.reg_id "
        f"FROM registrations r {' '.join(joins)} "
        f"WHERE {' AND '.join(wheres)}"
    )
    return sql, binds


# ── Static frontend ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    resp = send_from_directory(Path(__file__).parent, "lobby-explorer.html")
    # Always revalidate (cheap 304 via the ETag Flask sets) so a redeploy's
    # frontend changes reach browsers immediately.
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ── /beta: static DuckDB-WASM frontend (candidate replacement for /) ─────────

_VENDOR_TYPES = {".wasm": "application/wasm", ".mjs": "text/javascript",
                 ".js": "text/javascript"}


@app.route("/beta/")
def beta_index():
    resp = send_from_directory(Path(__file__).parent, "wasm-prototype.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/beta/static/<path:filename>")
def beta_static(filename):
    """Vendored, version-pinned libraries (the HTML references them with ?v=
    cache-busters). Serve the pre-gzipped sibling when the client accepts it —
    gzipping the 35MB duckdb wasm per-request would pin the CPU."""
    static_dir = Path(__file__).parent / "static"
    ctype = (_VENDOR_TYPES.get(Path(filename).suffix)
             or mimetypes.guess_type(filename)[0]
             or "application/octet-stream")
    gz_ok = "gzip" in request.headers.get("Accept-Encoding", "").lower()
    if gz_ok and (static_dir / (filename + ".gz")).is_file():
        resp = send_from_directory(static_dir, filename + ".gz", mimetype=ctype)
        resp.headers["Content-Encoding"] = "gzip"
    else:
        resp = send_from_directory(static_dir, filename, mimetype=ctype)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    resp.headers["Vary"] = "Accept-Encoding"
    return resp


@app.route("/beta/parquet/<path:filename>")
def beta_parquet(filename):
    """Data files — replaced by the daily pipeline, so always revalidate
    (cheap 304 + browser cache while unchanged)."""
    resp = send_from_directory(Path(__file__).parent / "parquet", filename)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ── Health ───────────────────────────────────────────────────────────────────

def _health_aggregates(con) -> dict:
    """The full-table aggregates behind /api/health. Cached — they only change
    when the DB is rebuilt, and every worker restarts on redeploy."""
    agg = _cache_get("__health_agg__")
    if agg is None:
        total = con.execute("SELECT COUNT(*) FROM communications").fetchone()[0]
        min_d, max_d = con.execute(
            "SELECT MIN(comm_date), MAX(comm_date) FROM communications"
        ).fetchone()
        if _has_reg_tables(con):
            reg_row = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(is_original),0), MIN(posted_date), MAX(posted_date) "
                "FROM registrations"
            ).fetchone()
        else:
            reg_row = (0, 0, None, None)
        agg = {
            "total_comms": total,
            "date_range": [min_d, max_d],
            "total_regs": reg_row[0],
            "new_regs": reg_row[1],
            "reg_date_range": [reg_row[2], reg_row[3]],
        }
        _cache_set("__health_agg__", agg)
    return agg


@app.route("/api/health")
def health():
    try:
        with get_db() as con:
            agg = _health_aggregates(con)
            patched = con.execute(
                "SELECT value FROM meta WHERE key='patched_at'"
            ).fetchone()
            patch_count = con.execute(
                "SELECT value FROM meta WHERE key='patch_new_count'"
            ).fetchone()
        return _cached_json({
            "status": "ok",
            **agg,
            "patched_at": patched[0] if patched else None,
            "patch_new_count": int(patch_count[0]) if patch_count else 0,
        }, max_age=300)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Filter-option endpoints ───────────────────────────────────────────────────

@app.route("/api/subjects")
def subjects():
    cached = _cache_get("__subjects__")
    if cached is not None:
        return _cached_json(cached, max_age=3600)
    with get_db() as con:
        rows = con.execute(
            "SELECT subject_code, description FROM subject_types ORDER BY description"
        ).fetchall()
    result = rows_to_list(rows)
    _cache_set("__subjects__", result)
    return _cached_json(result, max_age=3600)


@app.route("/api/institutions")
def institutions():
    cached = _cache_get("__institutions__")
    if cached is not None:
        return _cached_json(cached, max_age=3600)
    with get_db() as con:
        rows = con.execute(
            """SELECT institution, COUNT(DISTINCT comlog_id) AS comm_count
               FROM dpoh WHERE institution != ''
               GROUP BY institution ORDER BY comm_count DESC"""
        ).fetchall()
    result = rows_to_list(rows)
    _cache_set("__institutions__", result)
    return _cached_json(result, max_age=3600)


_clients_cache: dict = {}
_clients_lock = threading.Lock()


def _client_list():
    """All distinct (client_name, client_num) pairs (~16k), loaded once per
    worker so the typeahead is an in-memory substring filter instead of a
    leading-wildcard LIKE full scan per keystroke."""
    with _clients_lock:
        if "rows" not in _clients_cache:
            with get_db() as con:
                rows = con.execute(
                    """SELECT DISTINCT client_name, client_num FROM communications
                       WHERE client_name != '' ORDER BY client_name"""
                ).fetchall()
            _clients_cache["rows"] = [
                (r["client_name"].lower(), r["client_name"], r["client_num"]) for r in rows
            ]
        return _clients_cache["rows"]


@app.route("/api/clients")
def clients():
    q = (request.args.get("q") or "").strip().lower()
    rows = _client_list()
    if q:
        hits = [r for r in rows if q in r[0]][:50]
    else:
        hits = rows[:200]
    return jsonify([{"client_name": n, "client_num": c} for (_, n, c) in hits])


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


# ── Registration stats (parallel to communications stats above) ──────────────

def _compute_reg_stats(params: dict) -> dict:
    """Run all registration analytics for the given filter params, using a temp
    table so the filter join runs once and each aggregation scans the small result."""
    inner_sql, binds = build_reg_filter_select(params)

    with get_db() as con:
        con.execute(f"CREATE TEMP TABLE _rfids AS {inner_sql}", binds)
        con.execute("CREATE INDEX _rfids_idx ON _rfids(reg_id)")

        row = con.execute("""
            SELECT COUNT(*)                       AS total,
                   COALESCE(SUM(r.is_original),0) AS new_regs,
                   COUNT(DISTINCT r.client_num)   AS unique_clients,
                   COUNT(DISTINCT r.reg_num_dclrnt) AS unique_lobbyists
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
        """).fetchone()
        totals = dict(row)
        totals["renewals"] = totals["total"] - totals["new_regs"]
        totals["unique_firms"] = con.execute("""
            SELECT COUNT(DISTINCT r.firm_name)
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
            WHERE r.firm_name != ''
        """).fetchone()[0]
        # First-time organizations: distinct orgs whose earliest-ever appearance
        # (across registrations + communications) is a registration in this set.
        totals["first_time_orgs"] = con.execute("""
            SELECT COUNT(DISTINCT r.norm_name)
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
            JOIN org_first_seen o ON o.norm_name = r.norm_name
            WHERE r.norm_name != '' AND o.first_date = r.posted_date
        """).fetchone()[0]
        totals["unique_orgs"] = con.execute("""
            SELECT COUNT(DISTINCT r.norm_name)
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
            WHERE r.norm_name != ''
        """).fetchone()[0]

        by_month = con.execute("""
            SELECT r.posted_month AS month, COUNT(*) AS count,
                   COALESCE(SUM(r.is_original),0) AS new,
                   COUNT(DISTINCT CASE WHEN o.first_date = r.posted_date THEN r.norm_name END) AS first_time
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
            LEFT JOIN org_first_seen o ON o.norm_name = r.norm_name
            GROUP BY r.posted_month ORDER BY r.posted_month
        """).fetchall()

        top_firms = con.execute("""
            SELECT r.firm_name, COUNT(*) AS count
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
            WHERE r.firm_name != ''
            GROUP BY r.firm_name ORDER BY count DESC LIMIT 20
        """).fetchall()

        top_clients = con.execute("""
            SELECT r.client_name, COUNT(*) AS count
            FROM _rfids fi JOIN registrations r ON r.reg_id = fi.reg_id
            WHERE r.client_name != ''
            GROUP BY r.client_name ORDER BY count DESC LIMIT 20
        """).fetchall()

        top_subjects = con.execute("""
            SELECT rs.subject_code, st.description, COUNT(DISTINCT fi.reg_id) AS count
            FROM _rfids fi
            JOIN reg_subjects rs ON rs.reg_id = fi.reg_id
            JOIN subject_types st ON st.subject_code = rs.subject_code
            WHERE rs.subject_code != ''
            GROUP BY rs.subject_code ORDER BY count DESC
        """).fetchall()

        top_institutions = con.execute("""
            SELECT rir.institution, COUNT(DISTINCT fi.reg_id) AS count
            FROM _rfids fi
            JOIN reg_institutions ri ON ri.reg_id = fi.reg_id
            JOIN reg_inst_ref rir ON rir.inst_id = ri.inst_id
            GROUP BY rir.institution ORDER BY count DESC LIMIT 20
        """).fetchall()

    return {
        **totals,
        "by_month":         rows_to_list(by_month),
        "top_firms":        rows_to_list(top_firms),
        "top_clients":      rows_to_list(top_clients),
        "top_subjects":     rows_to_list(top_subjects),
        "top_institutions": rows_to_list(top_institutions),
    }


def _is_default_reg_params(params: dict) -> bool:
    """True when params represent an unfiltered 'all registrations' request."""
    extra = {k for k in params if k not in ("date_from", "date_to")}
    if extra:
        return False
    now = datetime.datetime.utcnow()
    current_month = f"{now.year}-{now.month:02d}"
    return (
        params.get("date_from", "2014-01") <= "2014-01"
        and params.get("date_to", "2099-12") >= current_month
    )


_EMPTY_REG_STATS = {
    "total": 0, "new_regs": 0, "renewals": 0, "unique_clients": 0,
    "unique_lobbyists": 0, "unique_firms": 0, "first_time_orgs": 0, "unique_orgs": 0, "by_month": [],
    "top_firms": [], "top_clients": [], "top_subjects": [], "top_institutions": [],
}


@app.route("/api/reg-stats")
def reg_stats():
    params = {k: v for k, v in request.args.items() if v}
    key = "reg::" + str(sorted(params.items()))

    cached = _cache_get(key)
    if cached is not None:
        return jsonify(cached)

    with get_db() as con:
        if not _has_reg_tables(con):
            return jsonify(_EMPTY_REG_STATS)

    if _is_default_reg_params(params):
        with get_db() as con:
            row = con.execute(
                "SELECT value FROM meta WHERE key = 'default_reg_stats'"
            ).fetchone()
        if row:
            result = json.loads(row[0])
            _cache_set(key, result)
            return jsonify(result)

    result = _compute_reg_stats(params)
    _cache_set(key, result)
    return jsonify(result)


# ── Communications table (paginated) ─────────────────────────────────────────

def _decorate_comms(con, ids):
    """
    Fetch display fields for a small page of comlog_ids, preserving order.
    Each child table is queried separately — joining dpoh × subjects × details
    in one query multiplies rows before aggregation and duplicates text.
    """
    if not ids:
        return []
    ph = ",".join("?" * len(ids))

    comms = {}
    for r in con.execute(f"""
        SELECT comlog_id, comm_date, client_name, client_num,
               reg_first || ' ' || reg_last AS lobbyist,
               reg_type, is_amendment
        FROM communications WHERE comlog_id IN ({ph})""", ids):
        comms[r["comlog_id"]] = {
            **dict(r),
            "dpoh_names": [], "institutions": [],
            "subjects": [], "subject_details": [],
        }

    for r in con.execute(f"""
        SELECT comlog_id, dpoh_first, dpoh_last, institution
        FROM dpoh WHERE comlog_id IN ({ph})""", ids):
        c = comms[r["comlog_id"]]
        name = f"{r['dpoh_first']} {r['dpoh_last']}".strip()
        if name:
            c["dpoh_names"].append(name)
        if r["institution"]:
            c["institutions"].append(r["institution"])

    for r in con.execute(f"""
        SELECT s.comlog_id, st.description
        FROM subjects s JOIN subject_types st ON st.subject_code = s.subject_code
        WHERE s.comlog_id IN ({ph})""", ids):
        comms[r["comlog_id"]]["subjects"].append(r["description"])

    for r in con.execute(f"""
        SELECT comlog_id, detail_text FROM subject_details
        WHERE comlog_id IN ({ph})""", ids):
        comms[r["comlog_id"]]["subject_details"].append(r["detail_text"])

    out = []
    for cid in ids:
        c = comms[cid]
        # De-dupe preserving order; '|' separator because institution and
        # DPOH names can themselves contain commas
        c["dpoh_names"]      = "|".join(dict.fromkeys(c["dpoh_names"]))
        c["institutions"]    = "|".join(dict.fromkeys(c["institutions"]))
        c["subjects"]        = "|".join(dict.fromkeys(c["subjects"]))
        c["subject_details"] = " || ".join(dict.fromkeys(c["subject_details"]))
        out.append(c)
    return out


@app.route("/api/communications")
def communications():
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    joins, wheres, binds = build_filter_parts(request.args)
    base = f"FROM communications c {' '.join(joins)} WHERE {' AND '.join(wheres)}"
    # DISTINCT is only needed when a join can duplicate comlog_ids; without it
    # the page query terminates early off idx_c_date instead of sorting everything
    count_expr = "COUNT(DISTINCT c.comlog_id)" if joins else "COUNT(*)"
    distinct   = "DISTINCT " if joins else ""

    with get_db() as con:
        total = con.execute(f"SELECT {count_expr} {base}", binds).fetchone()[0]

        ids = [r[0] for r in con.execute(
            f"SELECT {distinct}c.comlog_id, c.comm_date {base} "
            f"ORDER BY c.comm_date DESC LIMIT ? OFFSET ?",
            binds + [limit, offset],
        ).fetchall()]

        rows = _decorate_comms(con, ids)

    return jsonify({"total": total, "rows": rows})


# ── Registrations table (paginated) ──────────────────────────────────────────

def _decorate_regs(con, ids):
    """Fetch display fields for a page of reg_ids, preserving order. Subjects and
    target institutions are queried separately to avoid join row-multiplication."""
    if not ids:
        return []
    ph = ",".join("?" * len(ids))

    regs = {}
    norms = {}   # reg_id -> norm_name, for the communications-count lookup
    for r in con.execute(f"""
        SELECT r.reg_id, r.reg_num, r.posted_date, r.effective_date, r.end_date,
               r.firm_name, r.reg_first || ' ' || r.reg_last AS lobbyist,
               r.client_name, r.client_num, r.reg_type, r.is_original, r.norm_name,
               CASE WHEN o.first_date = r.posted_date THEN 1 ELSE 0 END AS first_time_org
        FROM registrations r
        LEFT JOIN org_first_seen o ON o.norm_name = r.norm_name
        WHERE r.reg_id IN ({ph})""", ids):
        d = dict(r)
        norms[r["reg_id"]] = d.pop("norm_name") or ""
        regs[r["reg_id"]] = {**d, "subjects": [], "institutions": [],
                             "subject_details": [], "comm_count": 0}

    for r in con.execute(f"""
        SELECT rs.reg_id, st.description
        FROM reg_subjects rs JOIN subject_types st ON st.subject_code = rs.subject_code
        WHERE rs.reg_id IN ({ph})""", ids):
        regs[r["reg_id"]]["subjects"].append(r["description"])

    for r in con.execute(f"""
        SELECT ri.reg_id, rir.institution
        FROM reg_institutions ri JOIN reg_inst_ref rir ON rir.inst_id = ri.inst_id
        WHERE ri.reg_id IN ({ph})""", ids):
        regs[r["reg_id"]]["institutions"].append(r["institution"])

    for r in con.execute(f"""
        SELECT sd.reg_id, dt.detail_text
        FROM reg_subject_details sd JOIN reg_detail_text dt ON dt.detail_id = sd.detail_id
        WHERE sd.reg_id IN ({ph})""", ids):
        regs[r["reg_id"]]["subject_details"].append(r["detail_text"])

    # Communications count per organization (by normalised name), one query for
    # the whole page — powers the "has this client filed communications?" link.
    page_norms = [n for n in {v for v in norms.values()} if n]
    comm_counts = {}
    if page_norms:
        nph = ",".join("?" * len(page_norms))
        for r in con.execute(
            f"SELECT norm_name, COUNT(*) AS c FROM communications "
            f"WHERE norm_name IN ({nph}) GROUP BY norm_name", page_norms):
            comm_counts[r["norm_name"]] = r["c"]

    out = []
    for rid in ids:
        r = regs[rid]
        r["subjects"]        = "|".join(dict.fromkeys(r["subjects"]))
        r["institutions"]    = "|".join(dict.fromkeys(r["institutions"]))
        r["subject_details"] = " || ".join(dict.fromkeys(r["subject_details"]))
        r["norm_name"]       = norms[rid]
        r["comm_count"]      = comm_counts.get(norms[rid], 0)
        out.append(r)
    return out


@app.route("/api/registrations")
def registrations():
    limit  = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    first_time = (request.args.get("first_time_only") or "").strip() in ("1", "true", "on", "yes")

    joins, wheres, binds = build_reg_filter_parts(request.args)
    base = f"FROM registrations r {' '.join(joins)} WHERE {' AND '.join(wheres)}"

    with get_db() as con:
        if not _has_reg_tables(con):
            return jsonify({"total": 0, "rows": []})

        if first_time:
            # One row per organization (its debut registration), newest first —
            # a clean "first-time organizations" list. All of an org's debut-day
            # rows share the same posted_date (= its first_date), so MIN(reg_id)
            # picks a stable representative.
            total = con.execute(
                f"SELECT COUNT(DISTINCT r.norm_name) {base}", binds).fetchone()[0]
            ids = [r[0] for r in con.execute(
                f"SELECT MIN(r.reg_id) {base} "
                f"GROUP BY r.norm_name ORDER BY MIN(r.posted_date) DESC, r.norm_name "
                f"LIMIT ? OFFSET ?",
                binds + [limit, offset],
            ).fetchall()]
        else:
            count_expr = "COUNT(DISTINCT r.reg_id)" if joins else "COUNT(*)"
            distinct   = "DISTINCT " if joins else ""
            total = con.execute(f"SELECT {count_expr} {base}", binds).fetchone()[0]
            ids = [r[0] for r in con.execute(
                f"SELECT {distinct}r.reg_id, r.posted_date {base} "
                f"ORDER BY r.posted_date DESC LIMIT ? OFFSET ?",
                binds + [limit, offset],
            ).fetchall()]

        rows = _decorate_regs(con, ids)

    return jsonify({"total": total, "rows": rows})


@app.route("/api/reg-institutions")
def reg_institutions():
    """Distinct target government institutions across registrations (for the
    registrations filter dropdown). Kept separate from /api/institutions, which
    ranks DPOH institutions from communications."""
    cached = _cache_get("__reg_institutions__")
    if cached is not None:
        return _cached_json(cached, max_age=3600)
    with get_db() as con:
        if not _has_reg_tables(con):
            return jsonify([])
        rows = con.execute(
            """SELECT rir.institution, COUNT(DISTINCT ri.reg_id) AS reg_count
               FROM reg_institutions ri JOIN reg_inst_ref rir ON rir.inst_id = ri.inst_id
               GROUP BY rir.institution ORDER BY reg_count DESC"""
        ).fetchall()
    result = rows_to_list(rows)
    _cache_set("__reg_institutions__", result)
    return _cached_json(result, max_age=3600)


# ── Update check ─────────────────────────────────────────────────────────────

CHECK_UPDATE_TTL = 900   # seconds; one pair of registry header checks per window


@app.route("/api/check-update")
def check_update():
    # Server-side cache: without it every page load fires two synchronous
    # header requests at lobbycanada.gc.ca (up to 15s each, holding a worker
    # thread). One check per 15 min across all visitors is plenty — the
    # source files change at most daily.
    cached = _cache_get("__check_update__")
    if cached is not None:
        return jsonify(cached)
    try:
        # lobbycanada.gc.ca uses JA3 TLS fingerprint blocking — only curl_cffi
        # (Chrome impersonation) gets through. If not installed, skip check.
        if not _HAVE_CFFI:
            return jsonify({"update_available": False, "note": "curl_cffi not available"})

        def _head(url):
            rr = cffi_requests.get(url, impersonate="chrome", stream=True, timeout=15)
            rr.raise_for_status()
            lm = rr.headers.get("Last-Modified", "")
            cl = rr.headers.get("Content-Length", "")
            rr.close()
            return lm, cl

        remote_lm, remote_cl = _head(COMMS_ZIP_URL)
        reg_remote_lm, reg_remote_cl = _head(REGS_ZIP_URL)
    except Exception as e:
        return jsonify({"error": f"Request failed: {e}"}), 502

    def _meta(con, key):
        row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else ""

    with get_db() as con:
        local_lm      = _meta(con, "source_last_modified")
        local_size    = _meta(con, "source_file_size")
        built_at      = _meta(con, "built_at")
        reg_local_lm  = _meta(con, "reg_source_last_modified")
        reg_local_size = _meta(con, "reg_source_file_size")

    def _changed(rlm, llm, rcl, lcl):
        # Primary signal: Last-Modified header; fallback: Content-Length vs stored size
        if rlm and llm:
            return rlm != llm
        if rcl and lcl:
            return rcl != lcl
        return False

    comms_changed = _changed(remote_lm, local_lm, remote_cl, local_size)
    regs_changed  = _changed(reg_remote_lm, reg_local_lm, reg_remote_cl, reg_local_size)
    # A change in either open-data file means a rebuild is warranted
    update_available = comms_changed or regs_changed

    with get_db() as con:
        patched_row = con.execute(
            "SELECT value FROM meta WHERE key='patched_at'"
        ).fetchone()
        patch_count_row = con.execute(
            "SELECT value FROM meta WHERE key='patch_new_count'"
        ).fetchone()
    patched_at = patched_row[0] if patched_row else ""
    patch_new_count = int(patch_count_row[0]) if patch_count_row else 0

    # A redeploy can only ever install a DB that is already *published* — it
    # cannot create new data. So the rebuild button is offered only when the
    # published version stamp is newer than what this server is running
    # (e.g. the pipeline published but the redeploy hook failed). New data at
    # the registry without a newer published DB is informational only.
    deployable_update = False
    remote_built_at = ""
    try:
        mr = http_requests.get(META_ASSET_URL, timeout=10)
        if mr.ok:
            remote_meta = mr.json()
            remote_built_at = remote_meta.get("built_at", "")
            remote_stamp = max(remote_built_at, remote_meta.get("patched_at", ""))
            local_stamp = max(built_at or "", patched_at or "")
            deployable_update = bool(remote_stamp) and remote_stamp > local_stamp
    except Exception:
        pass   # no stamp published yet, or GitHub unreachable — button stays hidden

    payload = {
        "update_available": update_available,
        "deployable_update": deployable_update,
        "remote_built_at": remote_built_at,
        "comms_changed": comms_changed,
        "regs_changed": regs_changed,
        "remote_last_modified": remote_lm,
        "local_last_modified": local_lm,
        "remote_content_length": remote_cl,
        "local_file_size": local_size,
        "reg_remote_last_modified": reg_remote_lm,
        "reg_local_last_modified": reg_local_lm,
        "built_at": built_at,
        "patched_at": patched_at,
        "patch_new_count": patch_new_count,
    }
    _cache_set("__check_update__", payload, ttl=CHECK_UPDATE_TTL)
    return jsonify(payload)


TRIGGER_COOLDOWN_S = 600
_trigger_state = {"last": 0.0}


@app.route("/api/trigger-update", methods=["POST"])
def trigger_update():
    """Redeploy trigger for the on-page update banner. Guarded: only fires when
    the server's own update check saw newer source data, and at most once per
    cooldown window per worker — an unauthenticated visitor can no longer spam
    Render redeploys."""
    if not RENDER_DEPLOY_HOOK:
        return jsonify({"error": "RENDER_DEPLOY_HOOK not configured"}), 503
    chk = _cache_get("__check_update__")
    if not (chk and chk.get("deployable_update")):
        return jsonify({"error": "No newer published database to deploy."}), 409
    now = time.time()
    if now - _trigger_state["last"] < TRIGGER_COOLDOWN_S:
        return jsonify({"error": "An update was already triggered recently — "
                                 "it takes a few minutes to go live."}), 429
    _trigger_state["last"] = now
    try:
        r = http_requests.post(RENDER_DEPLOY_HOOK, timeout=15)
        r.raise_for_status()
        return jsonify({"status": "deploy triggered"})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── AI chatbot (/api/ask) ────────────────────────────────────────────────────

ASK_MODEL           = "claude-opus-4-8"
ASK_DAILY_LIMIT     = 50      # questions per UTC day, across all visitors
ASK_MAX_TOOL_CALLS  = 8       # max SQL queries Claude may run per question
ASK_MAX_ROWS        = 200     # rows returned to Claude per query
ASK_MAX_CELL_CHARS  = 400     # truncate long text cells in query results
ASK_QUERY_TIMEOUT_S = 15      # abort any single SQL query after this long
ASK_USAGE_DB        = Path(__file__).parent / "ask_usage.db"

_anthropic_client = None
_anthropic_lock = threading.Lock()


def _get_anthropic():
    global _anthropic_client
    with _anthropic_lock:
        if _anthropic_client is None:
            import anthropic
            _anthropic_client = anthropic.Anthropic()
        return _anthropic_client


def _ask_increment() -> int:
    """Increment today's question count and return it. Uses a separate SQLite
    file so the counter is atomic across gunicorn worker processes and
    survives lobby.db being replaced by the daily rebuild."""
    con = sqlite3.connect(ASK_USAGE_DB)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, count INTEGER NOT NULL)")
        day = datetime.datetime.utcnow().date().isoformat()
        row = con.execute(
            "INSERT INTO usage (day, count) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET count = count + 1 RETURNING count",
            (day,),
        ).fetchone()
        con.commit()
        return row[0]
    finally:
        con.close()


def _run_readonly_query(sql: str) -> dict:
    """Execute one SELECT against lobby.db on a read-only connection.
    Returns {"text": <compact result for the model>, "is_error": bool}."""
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {"text": f"Could not open database: {e}", "is_error": True}
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + ASK_QUERY_TIMEOUT_S
        con.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, 100_000
        )
        cur = con.execute(sql)
        raw = cur.fetchmany(ASK_MAX_ROWS + 1)
        truncated = len(raw) > ASK_MAX_ROWS
        raw = raw[:ASK_MAX_ROWS]
        cols = [d[0] for d in cur.description] if cur.description else []

        def cell(v):
            if isinstance(v, str) and len(v) > ASK_MAX_CELL_CHARS:
                return v[:ASK_MAX_CELL_CHARS] + "…"
            return v

        result = {
            "columns": cols,
            "rows": [[cell(v) for v in r] for r in raw],
            "row_count": len(raw),
        }
        if truncated:
            result["note"] = f"Output truncated to {ASK_MAX_ROWS} rows — use aggregation or LIMIT."
        return {"text": json.dumps(result, ensure_ascii=False, default=str), "is_error": False}
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            return {"text": f"Query aborted after {ASK_QUERY_TIMEOUT_S}s — rewrite it to scan less data "
                            "(filter on indexed columns, aggregate, or add LIMIT).", "is_error": True}
        return {"text": f"SQL error: {e}", "is_error": True}
    except sqlite3.Error as e:
        return {"text": f"SQL error: {e}", "is_error": True}
    finally:
        con.close()


_ask_system_cache: dict = {}


def _ask_system_prompt() -> str:
    """Build the system prompt (schema + data notes). Cached; the date range
    only changes when the DB is rebuilt, and workers restart on redeploy."""
    if "prompt" in _ask_system_cache:
        return _ask_system_cache["prompt"]
    with get_db() as con:
        lo, hi = con.execute("SELECT MIN(comm_date), MAX(comm_date) FROM communications").fetchone()
        total = con.execute("SELECT COUNT(*) FROM communications").fetchone()[0]
        subjects = con.execute(
            "SELECT subject_code, description FROM subject_types ORDER BY subject_code"
        ).fetchall()
        if _has_reg_tables(con):
            reg_total, reg_new, reg_lo, reg_hi = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(is_original),0), MIN(posted_date), MAX(posted_date) "
                "FROM registrations"
            ).fetchone()
        else:
            reg_total, reg_new, reg_lo, reg_hi = 0, 0, "n/a", "n/a"
    subject_list = "\n".join(f"  {r[0]} = {r[1]}" for r in subjects)
    prompt = f"""You are the research assistant for the Canadian Lobbyist Registry Explorer, a public website. You answer questions about federal lobbying communication reports filed with the Office of the Commissioner of Lobbying of Canada, by querying a SQLite database with the query_db tool.

DATABASE ({total:,} communications, {lo} to {hi}):

CREATE TABLE communications (
    comlog_id    INTEGER PRIMARY KEY,  -- one row per filed communication report
    client_num   TEXT,     -- stable client identifier (groups name variants)
    client_name  TEXT,     -- organization that lobbied (e.g. 'TELUS Corporation')
    reg_num      TEXT,     -- registrant (lobbyist) registration number
    reg_last     TEXT,     -- registrant surname
    reg_first    TEXT,     -- registrant first name
    comm_date    TEXT,     -- 'YYYY-MM-DD' (indexed; filter and sort on this)
    comm_year    INTEGER,
    comm_month   TEXT,     -- 'YYYY-MM'
    reg_type     INTEGER,  -- 1 = Consultant, 2 = In-house Corporation, 3 = In-house Organization
    is_amendment INTEGER,  -- 1 if the report is an amendment to an earlier filing
    norm_name    TEXT      -- normalised client_name; join to registrations.norm_name to link a client across both datasets
);
CREATE TABLE dpoh (        -- Designated Public Office Holders present; one row PER OFFICIAL per communication
    comlog_id    INTEGER,  -- joins to communications
    dpoh_last    TEXT,
    dpoh_first   TEXT,
    dpoh_title   TEXT,     -- e.g. 'Member of Parliament', 'Chief of Staff'
    branch       TEXT,
    institution  TEXT      -- e.g. 'House of Commons', 'Finance Canada (FIN)'
);
CREATE TABLE subjects (    -- subject matter codes; one row per code per communication
    comlog_id    INTEGER,
    subject_code TEXT      -- joins to subject_types
);
CREATE TABLE subject_types (subject_code TEXT PRIMARY KEY, description TEXT);
CREATE TABLE subject_details (comlog_id INTEGER, detail_text TEXT);  -- free-text detail; only present for a minority of records

REGISTRATIONS ({reg_total:,} registration filings, {reg_new:,} of them brand-new, {reg_lo} to {reg_hi} by posted date). A registration is a lobbyist declaring they will lobby for a client, filed BEFORE any communication. This is distinct from communications above (which log meetings that actually happened).

CREATE TABLE registrations (
    reg_id         INTEGER PRIMARY KEY,  -- one row per registration version
    reg_num        TEXT,     -- '{{registrant}}-{{client}}-{{version}}'
    reg_type       INTEGER,  -- 1 = Consultant, 2 = In-house Corporation, 3 = In-house Organization
    version_code   TEXT,
    firm_name      TEXT,     -- consultant lobbying firm ('' for in-house registrations)
    reg_num_dclrnt TEXT,     -- registrant (lobbyist) id
    reg_last       TEXT, reg_first TEXT,   -- registrant (lobbyist) name
    client_num     TEXT, client_name TEXT, -- client the lobbyist registered to represent
    effective_date TEXT,     -- 'YYYY-MM-DD' when the registration took effect
    end_date       TEXT,     -- '' if the registration is still active
    posted_date    TEXT,     -- 'YYYY-MM-DD' when it was published (indexed; filter/sort on this)
    posted_year    INTEGER, posted_month TEXT,  -- 'YYYY-MM'
    is_original    INTEGER,  -- 1 = a newly-filed registration (no predecessor); 0 = a renewal/amendment of an earlier filing
    norm_name      TEXT,     -- normalised client_name (joins to org_first_seen)
    govt_fund_ind  TEXT, contg_fee_ind TEXT, coalition_ind TEXT  -- 'Y'/'N' flags
);
CREATE TABLE reg_subjects (reg_id INTEGER, subject_code TEXT);       -- subject matters per registration; joins to subject_types
CREATE TABLE reg_inst_ref (inst_id INTEGER PRIMARY KEY, institution TEXT);  -- lookup of the ~222 government institutions
CREATE TABLE reg_institutions (reg_id INTEGER, inst_id INTEGER);     -- institutions a registration intends to lobby; join reg_inst_ref for the name
CREATE TABLE reg_detail_text (detail_id INTEGER PRIMARY KEY, detail_text TEXT);   -- deduplicated free-text subject-matter descriptions
CREATE TABLE reg_subject_details (reg_id INTEGER, detail_id INTEGER);  -- free-text descriptions per registration; join reg_detail_text for the text
CREATE TABLE org_first_seen (norm_name TEXT PRIMARY KEY, first_date TEXT, display_name TEXT);  -- earliest appearance of each org (by normalised name) across registrations + communications

SUBJECT CODES (shared by both subjects and reg_subjects):
{subject_list}

RULES AND GOTCHAS:
- Two separate datasets: `communications` = meetings that happened; `registrations` = intent-to-lobby filings. Pick the right one for the question. "New registrations", "who registered to lobby", "new lobbying files" → registrations. "Meetings", "who was lobbied", "contacts with officials" → communications.
- `is_original = 1` means a NEWLY-FILED registration, NOT a first-time organization. client_num is minted per consultant engagement, so a long-established org (e.g. a big association) gets a new is_original=1 registration every time it retains a new consultant. Do not equate is_original with "first-time client/organization".
- To find FIRST-TIME organizations (never in the registry before), use org_first_seen: an org debuts when a registration's posted_date equals its org_first_seen.first_date (join on norm_name). Count distinct organizations with COUNT(DISTINCT r.norm_name). This is name-deduplicated (a heuristic) and only covers 2014-onward data.
- Filter and sort registrations on posted_date.
- Joining reg_subjects or reg_institutions multiplies rows: count registrations with COUNT(DISTINCT r.reg_id) after a join.
- reg_institutions holds the institutions a lobbyist INTENDS to lobby (declared at registration); dpoh.institution holds officials actually met. Both use the same abbreviated names ('Finance Canada (FIN)').
- Registrations refresh from the weekly bulk file only (communications also get a daily live top-up), so registrations may lag the last few days.
- Joining dpoh or subjects multiplies rows: count communications with COUNT(DISTINCT c.comlog_id), never COUNT(*), after a join.
- Name matching: use LIKE '%term%' COLLATE NOCASE — client and institution names vary in casing and form. If a first query returns nothing, try a broader pattern before concluding there are no records.
- Institutions are stored with abbreviations, e.g. 'Finance Canada (FIN)', 'Transport Canada (TC)' — match with LIKE.
- MPs and Senators appear as dpoh rows under 'House of Commons' / 'Senate of Canada'.
- One communication = one meeting/call/email report. Several officials may attend (several dpoh rows).
- Registrants (reg_last/reg_first) are the lobbyists; clients are who they lobby for. For reg_type 2 and 3 (in-house), the registrant works for the client organization itself.
- subject_details exists only for a minority of records (a limitation of the source bulk file) — never treat its absence as meaningful.
- client_name is an empty string on a few hundred records per year (all reg_types). Exclude them (client_name != '') when ranking or listing clients.
- Data covers {lo} to {hi} and is refreshed daily from the public registry. If a question asks about anything after {hi}, say the data doesn't cover it yet.

ANSWERING:
- Today's date is {{today}}.
- Run the queries you need (up to {ASK_MAX_TOOL_CALLS}), then answer concisely in plain prose. Short hyphen lists are fine; no markdown tables or headers.
- Give exact figures from your queries and mention the period they cover. Round nothing silently.
- If the question can't be answered from this database (e.g. lobbying spending, provincial lobbying, opinions), say so briefly rather than guessing.
- Answer only questions about this lobbying data. Politely decline anything else."""
    _ask_system_cache["prompt"] = prompt
    return prompt


ASK_TOOL = {
    "name": "query_db",
    "description": (
        "Run one read-only SQL SELECT statement against the lobbying database. "
        f"Returns at most {ASK_MAX_ROWS} rows as JSON. Prefer aggregation over "
        "fetching raw rows. One statement per call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single SQLite SELECT statement."}
        },
        "required": ["sql"],
    },
}


@app.route("/api/ask", methods=["POST"])
def ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Missing question"}), 400
    if len(question) > 500:
        return jsonify({"error": "Question too long (500 characters max)"}), 400

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return jsonify({"error": "AI assistant not configured (ANTHROPIC_API_KEY not set)"}), 503

    try:
        client = _get_anthropic()
    except Exception as e:
        return jsonify({"error": f"AI assistant not configured: {e}"}), 503

    try:
        used = _ask_increment()
    except sqlite3.Error as e:
        return jsonify({"error": f"Usage tracking failed: {e}"}), 500
    if used > ASK_DAILY_LIMIT:
        return jsonify({"error": "The assistant has reached its daily question limit. "
                                 "Please try again tomorrow — the filters above work without limits."}), 429

    import anthropic

    today = datetime.datetime.utcnow().date().isoformat()
    system = [{
        "type": "text",
        "text": _ask_system_prompt().replace("{today}", today),
        "cache_control": {"type": "ephemeral"},
    }]
    messages = [{"role": "user", "content": question}]
    queries = []

    try:
        for _ in range(ASK_MAX_TOOL_CALLS + 1):
            response = client.messages.create(
                model=ASK_MODEL,
                max_tokens=8000,
                thinking={"type": "adaptive"},
                system=system,
                tools=[ASK_TOOL],
                messages=messages,
            )
            if response.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    sql = (block.input or {}).get("sql", "")
                    out = _run_readonly_query(sql)
                    queries.append(sql)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": out["text"],
                        "is_error": out["is_error"],
                    })
            messages.append({"role": "user", "content": results})
    except anthropic.APIStatusError as e:
        return jsonify({"error": f"AI service error ({e.status_code}). Please try again."}), 502
    except anthropic.APIConnectionError:
        return jsonify({"error": "Could not reach the AI service. Please try again."}), 502

    if response.stop_reason == "refusal":
        return jsonify({"error": "The assistant declined to answer that question."}), 200

    answer = "".join(b.text for b in response.content if b.type == "text").strip()
    if not answer:
        answer = "Sorry — I couldn't produce an answer for that question. Try rephrasing it."

    return jsonify({
        "answer": answer,
        "queries": queries,
        "questions_remaining": max(0, ASK_DAILY_LIMIT - used),
    })


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

            have_regs = _has_reg_tables(con)
            reg_inst = rows_to_list(con.execute(
                """SELECT rir.institution, COUNT(DISTINCT ri.reg_id) AS reg_count
                   FROM reg_institutions ri JOIN reg_inst_ref rir ON rir.inst_id = ri.inst_id
                   GROUP BY rir.institution ORDER BY reg_count DESC"""
            ).fetchall()) if have_regs else []

            stats_row = con.execute(
                "SELECT value FROM meta WHERE key = 'default_stats'"
            ).fetchone()
            reg_stats_row = con.execute(
                "SELECT value FROM meta WHERE key = 'default_reg_stats'"
            ).fetchone() if have_regs else None

            # Touch idx_c_date so the first page-of-records query after a
            # fresh deploy reads a warm index instead of cold disk
            con.execute(
                "SELECT COUNT(*) FROM communications "
                "WHERE comm_date >= '2014-01-01' AND comm_date < '2100-01-01'"
            ).fetchone()
            # Same for the registrations posted-date index
            if have_regs:
                con.execute(
                    "SELECT COUNT(*) FROM registrations "
                    "WHERE posted_date >= '2014-01-01' AND posted_date < '2100-01-01'"
                ).fetchone()

            # Health aggregates (full-table counts) so /api/health never
            # scans on a live request
            _health_aggregates(con)

        # Typeahead list (in-memory distinct clients)
        _client_list()

        _cache_set("__subjects__", subj)
        _cache_set("__institutions__", inst)
        _cache_set("__reg_institutions__", reg_inst)

        default_params = {
            "date_from": "2014-01",
            "date_to": f"{now.year}-{now.month:02d}",
        }
        if stats_row:
            _cache_set(str(sorted(default_params.items())), json.loads(stats_row[0]))
        if reg_stats_row:
            _cache_set("reg::" + str(sorted(default_params.items())), json.loads(reg_stats_row[0]))

        print("Cache ready.", flush=True)
    except Exception as e:
        print(f"Pre-warm failed: {e}", flush=True)


_ensure_indexes()
threading.Thread(target=_prewarm, daemon=True).start()


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
