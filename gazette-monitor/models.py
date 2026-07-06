"""Database setup for the Canada Gazette Regulatory Monitor.

Raw sqlite3 — single file, no server. init_db() is idempotent: it creates
tables if missing and seeds the default watchlist rules only when the
rules table is empty.
"""

import json
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS gazette_issues (
    id INTEGER PRIMARY KEY,
    part TEXT NOT NULL,              -- 'I', 'II', or 'III'
    volume INTEGER,
    number TEXT,                     -- text because extras use formats like "extra 5"
    issue_date DATE,
    index_url TEXT UNIQUE,
    fetched_at DATETIME
);

CREATE TABLE IF NOT EXISTS gazette_items (
    id INTEGER PRIMARY KEY,
    issue_id INTEGER REFERENCES gazette_issues(id),
    section TEXT,
    department TEXT,
    act TEXT,
    title TEXT,
    item_url TEXT UNIQUE,
    comment_deadline DATE,           -- nullable; Part I proposed regs only
    rias_summary TEXT,               -- nullable; extracted RIAS text for keyword matching
    full_text_fetched_at DATETIME
);

CREATE TABLE IF NOT EXISTS watchlist_rules (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    keywords TEXT NOT NULL,          -- JSON array of keyword strings
    departments TEXT,                -- JSON array of department name substrings (optional filter)
    match_mode TEXT DEFAULT 'any',   -- 'any' or 'all'
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    item_id INTEGER REFERENCES gazette_items(id),
    rule_id INTEGER REFERENCES watchlist_rules(id),
    matched_on TEXT,
    created_at DATETIME,
    seen INTEGER DEFAULT 0,
    UNIQUE (item_id, rule_id)
);

CREATE TABLE IF NOT EXISTS ingest_state (
    feed TEXT PRIMARY KEY,           -- 'I', 'II', 'III'
    last_guid TEXT,
    checked_at DATETIME
);
"""

SEED_RULES = [
    ("Housing",
     ["housing", "mortgage", "rent", "landlord", "tenant", "CMHC", "zoning", "residential"]),
    ("Immigration",
     ["immigration", "refugee", "permanent resident", "temporary resident", "visa",
      "citizenship", "asylum"]),
    ("Trade & tariffs",
     ["tariff", "customs", "import", "export", "trade", "surtax", "countervailing",
      "anti-dumping", "CUSMA"]),
    ("Environment",
     ["environment", "emissions", "greenhouse gas", "carbon", "pollution", "pesticide",
      "species at risk"]),
    ("Labour mobility",
     ["labour mobility", "credentials", "occupational", "professional regulation",
      "interprovincial"]),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM watchlist_rules").fetchone()[0] == 0:
        for label, keywords in SEED_RULES:
            conn.execute(
                "INSERT INTO watchlist_rules (label, keywords, departments, match_mode, active)"
                " VALUES (?, ?, ?, 'any', 1)",
                (label, json.dumps(keywords), json.dumps([])),
            )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
