#!/usr/bin/env python3
"""
Lobbyist Registry — Weekly Pattern Alert
========================================
Scans lobby.db for clusters of business/industry lobbying activity and emails a
weekly briefing with an AI-written analysis. Modelled on send_statcan_daily.py.

The signal we look for (per the chatbot's tariff-signature research): NEW
organizations debuting in the registry and immediately lobbying on a live
policy file — trade remedies, interprovincial trade, AI/data centres, real
estate, metals, etc. — often targeting the departments that make the decision.

Runs entirely on this machine against the local lobby.db (read-only), so it
needs NO changes to app.py. Schedule it AFTER the nightly lobby.db rebuild.

  Credentials (env preferred so a launchd job from ~/statcan-explorer doesn't
  trip macOS TCC by reading ~/Desktop):
    ANTHROPIC_API_KEY          — already in ~/.zshenv for the app
    LOBBY_GMAIL_APP_PASSWORD   — 16-char Gmail app password (add to ~/.zshenv)
  Both fall back to the same RTF files send_statcan_daily.py uses.

  Env overrides:
    LOBBY_DB_PATH        — path to lobby.db (default: alongside this script)
    LOBBY_WEEKLY_STATE   — dedup state JSON (default: alongside this script)
    LOBBY_ALERT_TO       — recipient (default: jasonkirby@gmail.com)

  Flags:
    --dry-run     build the email and print it; do NOT send or update state
    --days N      look-back window in days (default 14)
    --model ID    Anthropic model (default claude-opus-4-8)
"""

import argparse
import datetime
import json
import os
import re
import smtplib
import sqlite3
import ssl
import sys
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

HERE             = Path(__file__).resolve().parent
FROM_EMAIL       = "jmk.yyz.data@gmail.com"
TO_EMAIL         = os.environ.get("LOBBY_ALERT_TO", "jasonkirby@gmail.com")
DB_PATH          = Path(os.environ.get("LOBBY_DB_PATH", HERE / "lobby.db"))
STATE_PATH       = Path(os.environ.get("LOBBY_WEEKLY_STATE", HERE / "lobby_weekly_state.json"))
DEFAULT_MODEL    = "claude-opus-4-8"

# Fallback credential files (same ones send_statcan_daily.py reads)
DESKTOP          = Path.home() / "Desktop" / "StatCanApp"
APP_PASSWORD_RTF = DESKTOP / "gmail_app_password.txt.rtf"
API_KEY_RTF      = DESKTOP / "anthropic_api_key.txt.rtf"

# How much lobbying a NEW org must show before it's worth flagging.
MIN_MEETINGS_TO_FLAG = 3     # a debut org with >= this many communications
# A same-week debut cohort of this many sector orgs is itself a headline.
COHORT_SIZE          = 3
# Cross-week memory: give the AI a trailing sector roster this many weeks back so
# a pattern that builds over a month isn't fragmented across isolated emails.
CONTEXT_WEEKS        = 8
CONTEXT_MAX_ORGS     = 12    # cap prior-context orgs per sector fed to the model
# Re-surface a previously-reported org when its activity has materially grown:
ESCALATION_MEETING_JUMP = 5   # meetings up by >= this since last seen, OR …
# … it reached a key department it hadn't when first reported (see key_insts_hit).
ESCALATION_WATCH_WEEKS  = 12  # stop re-checking an org for escalation after this
# Generic (uncurated) trend scan across ALL subject areas — so a gathering cluster
# in any industry (pharma, autos, agriculture, energy, telecom…) is caught, not
# just the curated files. A subject is a candidate when this many new debut orgs
# cluster on it; it's ranked by how elevated that is vs. its own 8-week baseline.
EMERGING_MIN_ORGS     = 4
EMERGING_MAX_CLUSTERS = 5
EMERGING_MAX_ORGS     = 8
EMERGING_SURGE_RATIO  = 1.5   # only flag a subject running >= this × its normal rate

# ── Sector watchlist ──────────────────────────────────────────────────────────
# An org matches a sector if its free-text mentions one of `keywords`, OR (only
# when `code_sufficient` is True) it carries one of `subject_codes`. Broad codes
# like International Trade (SMT-25) pull in every exporter, so for the sharp
# tariff/metals signals the KEYWORD is the tell and code_sufficient=False; for
# narrowly-scoped codes (Internal Trade) the code alone is enough.
# `institutions` are the decision-making bodies whose involvement strengthens the
# signal. Order matters: an org is reported in the FIRST sector it matches, so
# put the most specific/pointed files first.
SECTORS = [
    {
        "name": "Trade remedies & tariffs",
        "emoji": "🛡️",
        "subject_codes": ["SMT-25"],                         # International Trade (broad)
        "code_sufficient": False,
        "institutions": ["Finance Canada", "Global Affairs", "Canada Border Services"],
        "keywords": ["dumping", "safeguard", "surtax", "tariff", "sima",
                     "special import measures", "section 55", "remission",
                     "anti-dumping", "countervail", "trade remed", "duties"],
    },
    {
        "name": "Steel, aluminum & metals",
        "emoji": "⚙️",
        "subject_codes": ["SMT-28"],                         # Mining (broad)
        "code_sufficient": False,
        "institutions": ["Finance Canada", "Global Affairs", "Innovation, Science"],
        "keywords": ["steel", "aluminum", "aluminium", "extrusion", "fastener",
                     "rebar", "pipe and steel", "metal fabricat", "smelter"],
    },
    {
        "name": "Interprovincial / internal trade",
        "emoji": "🍁",
        "subject_codes": ["SMT-23"],                         # Internal Trade (specific)
        "code_sufficient": True,
        "institutions": ["Internal Trade", "Intergovernmental", "Finance Canada"],
        "keywords": ["interprovincial", "internal trade", "cfta", "labour mobility",
                     "trade barrier", "free trade within canada", "mutual recognition"],
    },
    {
        "name": "AI & data centres",
        "emoji": "🤖",
        "subject_codes": [],                                 # keyword-driven; codes too broad
        "code_sufficient": False,
        "institutions": ["Innovation, Science", "Industry", "Natural Resources", "Finance Canada"],
        "keywords": ["artificial intelligence", "data centre", "data center",
                     "sovereign compute", "compute capacity", "machine learning",
                     "gpu", "cloud infrastructure", "generative ai"],
    },
    {
        "name": "Real estate & housing",
        "emoji": "🏠",
        "subject_codes": ["SMT-44"],                         # Housing
        "code_sufficient": False,
        "institutions": ["Housing", "Canada Mortgage", "Finance Canada", "Infrastructure"],
        "keywords": ["housing supply", "purpose-built rental", "development charge",
                     "zoning", "real estate investment", "reit", "home builder",
                     "mortgage", "affordable housing"],
    },
    {
        "name": "Energy & natural resources",
        "emoji": "🛢️",
        "subject_codes": ["SMT-11", "SMT-53"],               # Energy, Natural Resources
        "code_sufficient": False,
        "institutions": ["Natural Resources", "Environment", "Finance Canada"],
        "keywords": ["oil and gas", "pipeline", "lng", "liquefied natural gas",
                     "electricity", "power grid", "nuclear", "small modular reactor",
                     "hydrogen", "refinery", "oil sands", "carbon capture"],
    },
    {
        "name": "Agriculture & food",
        "emoji": "🌾",
        "subject_codes": ["SMT-3"],                          # Agriculture
        "code_sufficient": True,
        "institutions": ["Agriculture", "Finance Canada", "Health", "Global Affairs"],
        "keywords": ["supply management", "dairy", "poultry", "grain", "canola",
                     "food processing", "agri-food", "fertilizer", "livestock",
                     "meat processing", "crop"],
    },
    {
        "name": "Pharma & health products",
        "emoji": "💊",
        "subject_codes": [],                                 # SMT-18 Health too broad
        "code_sufficient": False,
        "institutions": ["Health", "Public Health", "Finance Canada"],
        "keywords": ["pharmaceutical", "patented medicine", "pmprb", "biologic",
                     "generic drug", "vaccine", "medical device", "drug shortage",
                     "natural health product", "clinical trial", "pharmacare"],
    },
    {
        "name": "Autos & EV supply chain",
        "emoji": "🚗",
        "subject_codes": [],                                 # keyword-driven
        "code_sufficient": False,
        "institutions": ["Innovation, Science", "Finance Canada", "Transport"],
        "keywords": ["automotive", "auto parts", "electric vehicle", "ev battery",
                     "zev mandate", "battery plant", "cathode", "powertrain",
                     "vehicle manufactur"],
    },
    {
        "name": "Mining & critical minerals",
        "emoji": "⛏️",
        "subject_codes": ["SMT-28"],                         # Mining
        "code_sufficient": False,
        "institutions": ["Natural Resources", "Innovation, Science", "Finance Canada"],
        "keywords": ["critical mineral", "lithium", "nickel", "cobalt", "rare earth",
                     "copper", "potash", "uranium", "graphite", "mineral exploration",
                     "flow-through share"],
    },
    {
        "name": "Financial services",
        "emoji": "🏦",
        "subject_codes": ["SMT-14"],                         # Financial Institutions
        "code_sufficient": True,
        "institutions": ["Finance Canada", "OSFI", "Bank of Canada"],
        "keywords": ["bank", "insurance", "payments", "open banking", "fintech",
                     "credit union", "capital markets", "pension fund", "securities",
                     "consumer-driven banking"],
    },
    {
        "name": "Telecom, broadcasting & digital",
        "emoji": "📡",
        "subject_codes": ["SMT-1", "SMT-5"],                 # Telecom, Broadcasting
        "code_sufficient": True,
        "institutions": ["Innovation, Science", "Canadian Radio", "Canadian Heritage"],
        "keywords": ["spectrum", "wireless", "broadband", "5g", "streaming",
                     "online streaming act", "net neutrality", "telecom competition",
                     "roaming"],
    },
    {
        "name": "Defence & procurement",
        "emoji": "🛡",
        "subject_codes": ["SMT-8"],                          # Defence (procurement broad)
        "code_sufficient": True,
        "institutions": ["National Defence", "Public Services and Procurement", "PSPC"],
        "keywords": ["defence procurement", "shipbuilding", "fighter", "munitions",
                     "norad", "military", "dual-use", "nato", "naval"],
    },
    {
        "name": "Transportation & supply chain",
        "emoji": "🚚",
        "subject_codes": ["SMT-35"],                         # Transportation
        "code_sufficient": True,
        "institutions": ["Transport", "Finance Canada", "Infrastructure"],
        "keywords": ["railway", "port", "marine", "aviation", "airline", "trucking",
                     "supply chain", "freight", "border crossing"],
    },
]

SECTOR_BY_NAME = {s["name"]: s for s in SECTORS}


# ── Credential readers (env first, RTF fallback) ──────────────────────────────

def _read_rtf_lines(filepath):
    with open(filepath, "r") as f:
        return f.read().split("\n")


def get_app_password():
    """16-char Gmail app password: env LOBBY_GMAIL_APP_PASSWORD, else RTF."""
    env = (os.environ.get("LOBBY_GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()
    if len(env) == 16 and env.isalpha():
        return env
    for line in reversed(_read_rtf_lines(APP_PASSWORD_RTF)):
        clean = re.sub(r"\\[a-z]+\d*\s?", "", line)
        clean = re.sub(r"[{}]", "", clean).strip().replace(" ", "")
        if len(clean) == 16 and clean.isalpha():
            return clean
    raise ValueError("Could not find a 16-char Gmail app password (env or RTF).")


def get_api_key():
    """Anthropic key: env ANTHROPIC_API_KEY, else RTF. Returns None if absent."""
    env = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if env.startswith("sk-ant-"):
        return env
    try:
        for line in reversed(_read_rtf_lines(API_KEY_RTF)):
            m = re.search(r"sk-ant-[A-Za-z0-9\-_]+", line)
            if m:
                return m.group(0)
    except OSError:
        pass
    return None


# ── Database ──────────────────────────────────────────────────────────────────

def open_db():
    if not DB_PATH.exists():
        print(f"ERROR: lobby.db not found at {DB_PATH}")
        sys.exit(1)
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    # Confirm the registrations tables exist (they can lag a deploy).
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"registrations", "org_first_seen", "reg_subjects"} <= have:
        print("ERROR: registrations tables missing from lobby.db — cannot run.")
        sys.exit(1)
    return con


def _keyword_clause(keywords, columns):
    """Build (sql_fragment, params) OR-ing every keyword LIKE across columns."""
    frags, params = [], []
    for kw in keywords:
        for col in columns:
            frags.append(f"{col} LIKE ? COLLATE NOCASE")
            params.append(f"%{kw}%")
    return "(" + " OR ".join(frags) + ")", params


def org_footprint(con, norm_name, keywords=()):
    """Meeting count, top institutions met, and a free-text snippet for an org.
    The snippet prefers text that mentions one of the sector's keywords (the
    pointed, on-file intent) over merely the longest description."""
    meetings = con.execute(
        "SELECT COUNT(DISTINCT comlog_id) FROM communications WHERE norm_name = ?",
        (norm_name,),
    ).fetchone()[0]
    insts = con.execute(
        """SELECT d.institution, COUNT(DISTINCT c.comlog_id) n
           FROM communications c JOIN dpoh d ON d.comlog_id = c.comlog_id
           WHERE c.norm_name = ? AND d.institution != ''
           GROUP BY d.institution ORDER BY n DESC LIMIT 4""",
        (norm_name,),
    ).fetchall()
    if keywords:
        hit_sql, hit_params = _keyword_clause(keywords, ["dt.detail_text"])
        order = f"({hit_sql}) DESC, LENGTH(dt.detail_text) DESC"
    else:
        hit_params, order = [], "LENGTH(dt.detail_text) DESC"
    snippet = con.execute(
        f"""SELECT dt.detail_text
           FROM registrations r
           JOIN reg_subject_details rsd ON rsd.reg_id = r.reg_id
           JOIN reg_detail_text dt ON dt.detail_id = rsd.detail_id
           WHERE r.norm_name = ? AND LENGTH(dt.detail_text) > 30
           ORDER BY {order} LIMIT 1""",
        (norm_name, *hit_params),
    ).fetchone()
    return {
        "meetings": meetings,
        "institutions": [(r[0], r[1]) for r in insts],
        "snippet": (snippet[0][:400] if snippet else ""),
    }


def key_insts_hit(con, norm_name, institutions):
    """Which of a sector's key departments this org has actually met (any count).
    Used to detect escalation — reaching Finance/PMO/etc. for the first time."""
    if not institutions:
        return []
    frag, params = _keyword_clause(institutions, ["d.institution"])
    rows = con.execute(
        f"""SELECT DISTINCT d.institution
            FROM communications c JOIN dpoh d ON d.comlog_id = c.comlog_id
            WHERE c.norm_name = ? AND {frag}""",
        (norm_name, *params),
    ).fetchall()
    hit = set()
    for (inst,) in rows:
        for pat in institutions:
            if pat.lower() in (inst or "").lower():
                hit.add(pat)
    return sorted(hit)


def find_new_entrants(con, sector, since):
    """New debut orgs (org_first_seen == this registration's posted_date) inside
    the window that match the sector by subject code or free-text keyword."""
    conds, params = [], []
    if sector["subject_codes"] and sector.get("code_sufficient"):
        placeholders = ",".join("?" * len(sector["subject_codes"]))
        conds.append(f"""EXISTS (SELECT 1 FROM reg_subjects rs
                                 WHERE rs.reg_id = r.reg_id
                                 AND rs.subject_code IN ({placeholders}))""")
        params += sector["subject_codes"]
    if sector["keywords"]:
        kw_sql, kw_params = _keyword_clause(sector["keywords"], ["dt.detail_text"])
        conds.append(f"""EXISTS (SELECT 1 FROM reg_subject_details rsd
                                 JOIN reg_detail_text dt ON dt.detail_id = rsd.detail_id
                                 WHERE rsd.reg_id = r.reg_id AND {kw_sql})""")
        params += kw_params
    match = "(" + " OR ".join(conds) + ")" if conds else "1=1"

    sql = f"""
        SELECT r.norm_name, MAX(r.client_name) AS name, MIN(r.posted_date) AS debut
        FROM registrations r
        JOIN org_first_seen o
          ON o.norm_name = r.norm_name AND o.first_date = r.posted_date
        WHERE r.posted_date >= ? AND r.client_name != '' AND {match}
        GROUP BY r.norm_name
        ORDER BY debut DESC
    """
    rows = con.execute(sql, [since] + params).fetchall()
    entrants = []
    for r in rows:
        fp = org_footprint(con, r["norm_name"], sector["keywords"])
        entrants.append({
            "norm_name": r["norm_name"],
            "name": r["name"],
            "debut": r["debut"],
            **fp,
        })
    return entrants


def _is_notable(e, cohort_names):
    """A new entrant is worth flagging if it shows a signal beyond merely
    existing: pointed free-text intent, meetings already logged, or membership
    in a same-week debut cohort."""
    return bool(e["snippet"]) or e["meetings"] >= MIN_MEETINGS_TO_FLAG \
        or e["name"] in cohort_names


def check_escalations(con, watch):
    """Refresh every actively-watched (previously-reported) org and flag those
    whose activity has materially grown. Returns (escalations_by_sector,
    snapshot) — snapshot carries the refreshed metrics to persist."""
    esc_by_sector, snapshot = {}, {}
    for nn, rec in watch.items():
        sector = SECTOR_BY_NAME.get(rec.get("sector"))
        if not sector:
            continue
        fp = org_footprint(con, nn, sector["keywords"])
        khits = key_insts_hit(con, nn, sector["institutions"])
        prev_m = rec.get("last_meetings", 0)
        new_depts = [k for k in khits if k not in set(rec.get("key_insts", []))]
        gained = fp["meetings"] - prev_m
        snapshot[nn] = {"sector": rec["sector"], "name": rec.get("name", nn),
                        "reported_date": rec.get("reported_date"),
                        "last_meetings": fp["meetings"], "key_insts": khits}
        if gained >= ESCALATION_MEETING_JUMP or new_depts:
            esc_by_sector.setdefault(rec["sector"], []).append({
                "name": rec.get("name", nn),
                "reported_date": rec.get("reported_date"),
                "prev_meetings": prev_m,
                "meetings": fp["meetings"],
                "gained": gained,
                "new_departments": new_depts,
                "institutions": fp["institutions"],
                "snippet": fp["snippet"],
            })
    return esc_by_sector, snapshot


def analyze(con, new_since, context_since, state):
    """Per sector, this run's flagged content and the recent picture:
      - new_entrants: notable debuts inside the new-entrant window not seen before
      - escalations:  previously-reported orgs whose activity materially grew
      - context:      the trailing CONTEXT_WEEKS roster (incl. reported orgs, with
                      their CURRENT footprint) so the model can connect the weeks
    Also returns a snapshot of refreshed watch metrics to persist."""
    seen = set(state.get("seen", []))
    watch = state.get("watch", {})
    esc_by_sector, snapshot = check_escalations(con, watch)

    findings, claimed = [], set()
    for sector in SECTORS:
        roster = find_new_entrants(con, sector, context_since)  # 8-week debuts
        new_entrants, context = [], []
        for e in roster:
            if e["debut"] >= new_since and e["norm_name"] not in seen \
                    and e["norm_name"] not in claimed:
                claimed.add(e["norm_name"])
                new_entrants.append(e)
            elif e["snippet"] or e["meetings"] >= 1:   # prior weeks = background
                context.append(e)

        dates = {}
        for e in new_entrants:
            dates.setdefault(e["debut"], []).append(e["name"])
        cohorts = {d: names for d, names in dates.items() if len(names) >= COHORT_SIZE}
        cohort_names = {n for names in cohorts.values() for n in names}
        notable_new = [e for e in new_entrants if _is_notable(e, cohort_names)]
        escalations = esc_by_sector.get(sector["name"], [])

        if notable_new or escalations:
            context = sorted(context, key=lambda x: (-x["meetings"], x["debut"]))[:CONTEXT_MAX_ORGS]
            findings.append({
                "sector": sector,
                "entrants": notable_new,
                "escalations": escalations,
                "context": context,
                "cohorts": cohorts,
            })

    seen = set(state.get("seen", []))
    emerging = find_emerging_clusters(con, new_since, context_since, claimed | seen)
    return findings, emerging, snapshot


def find_emerging_clusters(con, new_since, context_since, exclude):
    """Uncurated breadth: group NEW debut orgs by declared subject across ALL
    subject areas, and surface any subject where a cluster is forming (≥
    EMERGING_MIN_ORGS notable debuts), ranked by how elevated it is vs. that
    subject's own trailing baseline. The AI decides which are coherent trends.
    `exclude` = orgs already handled by the curated sectors (no double-listing)."""
    rows = con.execute(
        """SELECT rs.subject_code, r.norm_name,
                  MAX(r.client_name) AS name, MIN(r.posted_date) AS debut
           FROM registrations r
           JOIN org_first_seen o
             ON o.norm_name = r.norm_name AND o.first_date = r.posted_date
           JOIN reg_subjects rs ON rs.reg_id = r.reg_id
           WHERE r.posted_date >= ? AND r.client_name != ''
           GROUP BY rs.subject_code, r.norm_name""",
        (new_since,),
    ).fetchall()
    by_subject = {}
    for code, nn, name, debut in rows:
        if nn in exclude:
            continue
        by_subject.setdefault(code, {})[nn] = {"norm_name": nn, "name": name, "debut": debut}

    cands = {c: orgs for c, orgs in by_subject.items() if len(orgs) >= EMERGING_MIN_ORGS}
    if not cands:
        return []

    codes = list(cands)
    ph = ",".join("?" * len(codes))
    baseline = dict(con.execute(
        f"""SELECT rs.subject_code, COUNT(DISTINCT r.norm_name)
            FROM registrations r
            JOIN org_first_seen o
              ON o.norm_name = r.norm_name AND o.first_date = r.posted_date
            JOIN reg_subjects rs ON rs.reg_id = r.reg_id
            WHERE r.posted_date >= ? AND r.posted_date < ? AND rs.subject_code IN ({ph})
            GROUP BY rs.subject_code""",
        (context_since, new_since, *codes),
    ).fetchall())
    subj_desc = dict(con.execute(
        "SELECT subject_code, description FROM subject_types").fetchall())

    # Normalize the baseline to the current window's length so we compare rates,
    # not raw counts (the prior window is several times longer).
    today = datetime.date.today()
    new_days = max((today - datetime.date.fromisoformat(new_since)).days, 1)
    prior_days = max((datetime.date.fromisoformat(new_since)
                      - datetime.date.fromisoformat(context_since)).days, 1)

    clusters, fp_cache = [], {}
    for code, orgs in cands.items():
        notable = []
        for nn, meta in orgs.items():
            fp = fp_cache.get(nn) or org_footprint(con, nn, [])
            fp_cache[nn] = fp
            if fp["snippet"] or fp["meetings"] >= 1:
                notable.append({**meta, **fp})
        if len(notable) < EMERGING_MIN_ORGS:
            continue
        expected = baseline.get(code, 0) * new_days / prior_days
        elevation = len(notable) / max(expected, 1.0)
        if elevation < EMERGING_SURGE_RATIO:      # only genuine surges
            continue
        clusters.append({
            "subject_code": code,
            "subject": subj_desc.get(code, code),
            "count": len(notable),
            "expected": round(expected, 1),
            "elevation": round(elevation, 1),
            "orgs": sorted(notable, key=lambda x: -x["meetings"])[:EMERGING_MAX_ORGS],
        })
    clusters.sort(key=lambda c: (c["elevation"], c["count"]), reverse=True)
    return clusters[:EMERGING_MAX_CLUSTERS]


# ── State (dedup) ─────────────────────────────────────────────────────────────

def load_state():
    """State shape:
      seen  — every org ever reported, by norm_name (dedup: never re-list as new)
      watch — {norm_name: {sector, name, reported_date, last_meetings, key_insts}}
              orgs still young enough to check for escalation each week
    Legacy {"reported": {sector: [names]}} is migrated into `seen`."""
    default = {"seen": [], "watch": {}, "last_run": None}
    if not STATE_PATH.exists():
        return default
    try:
        st = json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return default
    st.setdefault("seen", [])
    st.setdefault("watch", {})
    if "reported" in st:  # migrate
        for names in st.pop("reported").values():
            st["seen"] = sorted(set(st["seen"]) | set(names))
    return st


def save_state(state, findings, snapshot, run_date):
    seen = set(state.get("seen", []))
    watch = state.get("watch", {})
    # Refresh metrics for orgs we re-checked this run.
    for nn, snap in snapshot.items():
        if nn in watch:
            watch[nn].update(last_meetings=snap["last_meetings"],
                             key_insts=snap["key_insts"])
    # Add this run's new entrants to seen + the escalation watch list.
    for f in findings:
        for e in f["entrants"]:
            seen.add(e["norm_name"])
            watch[e["norm_name"]] = {
                "sector": f["sector"]["name"],
                "name": e["name"],
                "reported_date": run_date,
                "last_meetings": e["meetings"],
                "key_insts": key_insts_hit_from(e, f["sector"]),
            }
    # Age out orgs too old to keep re-checking (they stay in `seen`).
    cutoff = (datetime.date.fromisoformat(run_date)
              - datetime.timedelta(weeks=ESCALATION_WATCH_WEEKS)).isoformat()
    watch = {nn: r for nn, r in watch.items()
             if (r.get("reported_date") or "9999") >= cutoff}
    state["seen"] = sorted(seen)
    state["watch"] = watch
    state["last_run"] = run_date
    STATE_PATH.write_text(json.dumps(state, indent=2))


def key_insts_hit_from(entrant, sector):
    """Best-effort key-department list for a just-reported entrant, derived from
    its already-fetched top institutions (avoids an extra query)."""
    hit = set()
    for name, _ in entrant.get("institutions", []):
        for pat in sector["institutions"]:
            if pat.lower() in (name or "").lower():
                hit.add(pat)
    return sorted(hit)


# ── Rendering ─────────────────────────────────────────────────────────────────

def _org_json(e):
    return {
        "org": e["name"],
        "debut_date": e["debut"],
        "meetings": e["meetings"],
        "top_institutions": [f"{n} ({c})" for n, c in e["institutions"]],
        "subject_text": e["snippet"],
    }


def findings_to_json(findings):
    """Compact structure handed to Claude for the narrative."""
    out = []
    for f in findings:
        s = f["sector"]
        out.append({
            "sector": s["name"],
            "key_departments": s["institutions"],
            "same_week_cohorts": [
                {"debut_date": d, "orgs": names} for d, names in f["cohorts"].items()
            ],
            "new_entrants_this_week": [_org_json(e) for e in f["entrants"]],
            "escalating_since_last_reported": [
                {
                    "org": x["name"],
                    "first_reported": x["reported_date"],
                    "meetings_then": x["prev_meetings"],
                    "meetings_now": x["meetings"],
                    "newly_reached_departments": x["new_departments"],
                    "top_institutions": [f"{n} ({c})" for n, c in x["institutions"]],
                    "subject_text": x["snippet"],
                }
                for x in f["escalations"]
            ],
            "recent_context_last_8_weeks": [_org_json(e) for e in f["context"]],
        })
    return out


def build_fallback_body(findings, emerging, since, today, active):
    divider = "─" * 52
    lines = [f"🏛️  Lobbyist Registry — Weekly Activity Alert",
             f"    New, escalating & emerging activity — week of {today}", "", divider, ""]
    if not active:
        lines += ["No new flagged clusters this week.",
                  "No previously-unseen organizations debuted on the watched files "
                  "with meaningful lobbying activity.", ""]
    for f in findings:
        s = f["sector"]
        lines.append(f"{s['emoji']}  {s['name'].upper()}")
        for d, names in f["cohorts"].items():
            lines.append(f"   ⚡ Same-day debut cohort ({d}): {', '.join(names)}")
        for e in sorted(f["entrants"], key=lambda x: -x["meetings"]):
            inst = "; ".join(f"{n} ({c})" for n, c in e["institutions"]) or "no meetings yet"
            lines.append(f"   • NEW: {e['name']} — debuted {e['debut']}, "
                         f"{e['meetings']} meeting(s); {inst}")
            if e["snippet"]:
                lines.append(f"       “{e['snippet'][:200]}”")
        for x in sorted(f["escalations"], key=lambda x: -x["gained"]):
            note = f"{x['prev_meetings']}→{x['meetings']} meetings"
            if x["new_departments"]:
                note += f"; now reaching {', '.join(x['new_departments'])}"
            lines.append(f"   ↑ ESCALATING: {x['name']} (first flagged "
                         f"{x['reported_date']}) — {note}")
        if f["context"]:
            others = ", ".join(e["name"] for e in f["context"][:5])
            lines.append(f"   … {len(f['context'])} other org(s) active on this file "
                         f"in the past {CONTEXT_WEEKS} weeks: {others}"
                         + ("…" if len(f["context"]) > 5 else ""))
        lines.append("")

    if emerging:
        lines.append("🌐  EMERGING TRENDS (any industry — uncurated surges)")
        for c in emerging:
            lines.append(f"   ◆ {c['subject']}: {c['count']} new debut org(s) this "
                         f"window — {c['elevation']}× the usual ~{c['expected']}")
            for e in c["orgs"][:5]:
                tag = f"{e['meetings']} mtg" if e["meetings"] else "0 mtg"
                lines.append(f"       • {e['name']} ({tag})"
                             + (f" — “{e['snippet'][:120]}”" if e["snippet"] else ""))
        lines.append("")

    lines += [divider,
              "Signal = new + escalating registry orgs lobbying a live policy file, "
              f"with {CONTEXT_WEEKS}-week context.",
              "These are inferences from lobbying patterns, not government decisions.",
              "Source: Office of the Commissioner of Lobbying of Canada",
              "https://lobbyist-explorer.onrender.com"]
    return "\n".join(lines)


# ── Claude narrative ──────────────────────────────────────────────────────────

def emerging_to_json(emerging):
    return [
        {
            "subject_area": c["subject"],
            "new_debut_orgs_this_window": c["count"],
            "normal_for_this_window": c["expected"],
            "elevation_vs_normal": f"{c['elevation']}x",
            "orgs": [_org_json(e) for e in c["orgs"]],
        }
        for c in emerging
    ]


def analyse_with_claude(findings, emerging, since, today, api_key, model):
    data = {
        "curated_watchlist_sectors": findings_to_json(findings),
        "emerging_trends_any_industry": emerging_to_json(emerging),
    }
    if not (any(f["new_entrants_this_week"] or f["escalating_since_last_reported"]
                for f in data["curated_watchlist_sectors"])
            or data["emerging_trends_any_industry"]):
        return None
    prompt = f"""You are writing a weekly intelligence briefing for a business journalist about the Canadian federal lobbyist registry. Your job is to flag ANY gathering business, industry, or economic trend — do not restrict yourself to the curated files. A known pattern to watch for: before a tariff or trade-remedy action, a whole sub-industry registers at once and lobbies Finance Canada about dumping/safeguards — but the same "sub-industry suddenly organizing" signature can appear in pharma, autos, agriculture, energy, telecom, mining, financial services, or anywhere.

The DATA has two parts:

1) "curated_watchlist_sectors" — files we track closely. Each has THREE lists, so reason ACROSS weeks, not just this one:
   - "new_entrants_this_week": orgs that debuted in the last several days.
   - "escalating_since_last_reported": orgs flagged in a PRIOR week whose activity has since materially grown (more meetings, or newly reaching a key department) — a campaign intensifying.
   - "recent_context_last_8_weeks": every org active on this file over the past {CONTEXT_WEEKS} weeks with CURRENT meeting counts — use it to judge whether this week's items are part of a larger, still-building cluster (e.g. "this week's 2 new aluminum filings bring the sector to 7 firms over two months, now 40+ meetings at Finance and accelerating"). Don't list every context org; use them to size the pattern.

2) "emerging_trends_any_industry" — UNCURATED breadth. New debut orgs grouped by declared subject area across the WHOLE economy, already filtered to subjects running ABOVE their normal rate ("elevation_vs_normal" = how many times the usual pace; "new_debut_orgs_this_window" vs "normal_for_this_window"). These are raw candidates for trends outside the curated files: read the subject_text and surface any that form a COHERENT business/industry/economic trend (one real sub-industry converging on one issue/department), name the industry plainly, and cite the elevation. IGNORE incoherent grab-bags where the orgs are unrelated even if the subject is elevated. This is how you catch a trend in an industry not on the watchlist.

DATA (JSON):
{json.dumps(data, ensure_ascii=False, indent=1)}

Write the email body with this structure:
- Header: "🏛️ Lobbyist Registry — Weekly Activity Alert" then a line "Week of {today} · new, escalating & emerging activity"
- A dashed divider
- Lead with the single strongest cluster from EITHER part — a fresh coordinated debut, a multi-week campaign now escalating, or a newly-emerging industry cluster. Name it, say why it stands out, cite the specific organizations and meeting counts (then→now for escalating ones), and quote a telling phrase from subject_text. Note if it's been building over several weeks.
- Then a short bullet (•) per other real cluster — curated or emerging — with the orgs, where they're lobbying, the file, and whether it's heating up or cooling. Include emerging industries here when coherent. Skip anything not notable; don't pad.
- If one cluster looks like a likely-next policy action, flag it at the top with 🔺 and say so plainly.
- End with: "These are inferences from lobbying-activity patterns, not government decisions." and "Source: Office of the Commissioner of Lobbying of Canada"

Use plain text with • bullets and *bold* for organization/sector names. No markdown tables or headers. Be specific and cite the numbers from the data. Don't invent anything not in the data."""

    payload = json.dumps({
        "model": model,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return "".join(b.get("text", "") for b in result.get("content", [])
                           if b.get("type") == "text").strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as e:
        print(f"  Claude API error: {e}")
        return None


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject, body, password):
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = FROM_EMAIL, TO_EMAIL, subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(FROM_EMAIL, password)
        server.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, don't send or save state")
    ap.add_argument("--days", type=int, default=14, help="new-entrant window (default 14)")
    ap.add_argument("--context-weeks", type=int, default=CONTEXT_WEEKS,
                    help=f"rolling sector-context horizon (default {CONTEXT_WEEKS})")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    today = datetime.date.today()
    new_since = (today - datetime.timedelta(days=args.days)).isoformat()
    context_since = (today - datetime.timedelta(weeks=args.context_weeks)).isoformat()
    print(f"Lobbyist weekly alert — new since {new_since}, context since "
          f"{context_since} (db: {DB_PATH})")

    con = open_db()
    state = load_state()   # dry-run reads real state for an honest preview; never saves
    findings, emerging, snapshot = analyze(con, new_since, context_since, state)

    n_new = sum(len(f["entrants"]) for f in findings)
    n_esc = sum(len(f["escalations"]) for f in findings)
    n_emg = len(emerging)
    have_content = bool(findings or emerging)
    print(f"Found {n_new} new + {n_esc} escalating across {len(findings)} curated "
          f"sector(s), plus {n_emg} emerging trend(s).")

    api_key = get_api_key()
    body = None
    if have_content and api_key:
        print("Requesting analysis from Claude…")
        body = analyse_with_claude(findings, emerging, new_since, today.isoformat(),
                                   api_key, args.model)
    if not body:
        if have_content and not api_key:
            print("No API key — using templated summary.")
        body = build_fallback_body(findings, emerging, new_since, today.isoformat(),
                                   have_content)

    date_label = today.strftime("%B %-d, %Y")
    if have_content:
        parts = []
        if n_new:
            parts.append(f"{n_new} new")
        if n_esc:
            parts.append(f"{n_esc} escalating")
        if n_emg:
            parts.append(f"{n_emg} emerging")
        subject = f"Lobbyist Alert — {' + '.join(parts)}, {date_label}"
    else:
        subject = f"Lobbyist Alert — quiet week, {date_label}"

    if args.dry_run:
        print("\n" + "=" * 60 + f"\nSUBJECT: {subject}\n" + "=" * 60)
        print(body)
        print("=" * 60 + "\n[dry-run] not sent; state unchanged.")
        return

    try:
        password = get_app_password()
    except (OSError, ValueError) as e:
        print(f"ERROR: could not read Gmail app password — {e}")
        sys.exit(1)
    print(f"Sending email to {TO_EMAIL}…")
    try:
        send_email(subject, body, password)
        print(f"✅ Sent: \"{subject}\"")
    except (smtplib.SMTPException, OSError) as e:
        print(f"❌ Failed to send — {e}")
        sys.exit(1)

    save_state(state, findings, snapshot, today.isoformat())
    print("State updated.")


if __name__ == "__main__":
    main()
