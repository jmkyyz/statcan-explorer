#!/usr/bin/env python3
"""
Build fred_catalog.json — the U.S. (FRED) series catalog served to the frontend.

Four categories appear in the Category dropdown, each flagged 🇺🇸:
  • GDP        — 5 flat series (dims:0)
  • Employment — 4 FRED release tables opened as dim1 sub-series
  • Prices     — 2 FRED release tables opened as dim1 sub-series
  • U.S. yields— 8 flat daily series (displayed monthly-average; proxy aggregates)

Release-table rows are pulled live from the FRED API and flattened into a
dim1 breakdown, preserving the FRED hierarchy via per-row `level` (the frontend
indents the dropdown by level, exactly like StatCan commodity trees).

Regenerate whenever you want to refresh table membership:
    python build_fred_catalog.py
Requires FRED_API_KEY in .env (same key the proxy uses).
"""
import json, os, sys, urllib.parse
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

def _api_key() -> str:
    for line in open(os.path.join(HERE, ".env")):
        if line.startswith("FRED_API_KEY="):
            return line.strip().split("=", 1)[1]
    sys.exit("FRED_API_KEY not found in .env")

KEY = _api_key()

# ── Flat single-series categories ────────────────────────────────────────────
# (id, FRED series id, display name, short chip label, freq)
# GDP levels/components all live in the expenditure drill-down below (mirroring
# StatCan 36-10-0104-01: Prices → Estimates); only per-capita stays flat since
# it has no row in the NIPA expenditure tables.
GDP_SERIES = [
    ("us_gdp_percap",  "A939RX0Q048SBEA", "Real GDP per capita",  "Real GDP per capita (US)","quarterly"),
]

# Treasury constant-maturity yields — daily source, aggregated to monthly avg.
YIELD_SERIES = [
    ("us_y_1mo", "DGS1MO", "1-month Treasury yield",  "US 1mo yield"),
    ("us_y_3mo", "DGS3MO", "3-month Treasury yield",  "US 3mo yield"),
    ("us_y_6mo", "DGS6MO", "6-month Treasury yield",  "US 6mo yield"),
    ("us_y_1y",  "DGS1",   "1-year Treasury yield",   "US 1y yield"),
    ("us_y_2y",  "DGS2",   "2-year Treasury yield",   "US 2y yield"),
    ("us_y_5y",  "DGS5",   "5-year Treasury yield",   "US 5y yield"),
    ("us_y_10y", "DGS10",  "10-year Treasury yield",  "US 10y yield"),
    ("us_y_30y", "DGS30",  "30-year Treasury yield",  "US 30y yield"),
]

# ── FRED release tables opened as dim1 sub-series ────────────────────────────
# (series entry id, release_id, element_id, display name, short-chip base, freq)
EMPLOYMENT_TABLES = [
    ("us_emp_ind_sa",    50, 4881, "Employment by industry (SA)",        "Emp by industry SA (US)",  "monthly"),
    ("us_emp_ind_nsa",   50, 5645, "Employment by industry (NSA)",       "Emp by industry NSA (US)", "monthly"),
    ("us_emp_stat_sa",   50, 463,  "Employment status of population (SA)","Emp status SA (US)",       "monthly"),
    ("us_emp_stat_nsa",  50, 2346, "Employment status of population (NSA)","Emp status NSA (US)",     "monthly"),
]
PRICES_TABLES = [
    ("us_cpi_sa",  10, 34483, "CPI components (SA)",  "CPI SA (US)",  "monthly"),
    ("us_cpi_nsa", 10, 34561, "CPI components (NSA)", "CPI NSA (US)", "monthly"),
]

# BEA NIPA GDP-by-expenditure tables (release 53) — the U.S. equivalent of
# StatCan 36-10-0104-01. Quarterly child tables of 1.1.5 (current $) and
# 1.1.6 (real chained $). Combined into ONE dims:2 series mirroring the
# Canadian GDP drill-down: dim1 Prices → dim2 Estimates, so every expenditure
# component (nonresidential/business fixed investment, etc.) is selectable.
# (dim1 value, release_id, element_id)
GDP_PRICE_TABLES = [
    ("Current dollars",        53, 12998),   # NIPA 1.1.5 quarterly
    ("Chained (2017) dollars", 53, 13026),   # NIPA 1.1.6 quarterly
]


def gdp_expenditure_series():
    rows = []
    for dim1, rid, eid in GDP_PRICE_TABLES:
        table_rows = fetch_table_rows(rid, eid)
        print(f"  GDP expenditure — {dim1}: {len(table_rows)} rows")
        rows += [{**r, "dim1": dim1} for r in table_rows]
    return {
        "id": "us_gdp_exp", "name": "Gross domestic product (expenditure-based)",
        "chipShort": "US GDP", "tableId": "FRED", "freq": "quarterly", "dims": 2,
        "dim1Name": "Prices", "dim2Name": "Estimates", "rows": rows,
    }


def fetch_table_rows(release_id: int, element_id: int) -> list[dict]:
    """Return ordered [{value, fredId, level, short, full}] for the series rows
    of a FRED release table. Dedupes duplicate display names within the table so
    each row is a unique dim1 key."""
    url = "https://api.stlouisfed.org/fred/release/tables?" + urllib.parse.urlencode({
        "release_id": release_id, "element_id": element_id,
        "api_key": KEY, "file_type": "json",
    })
    data = requests.get(url, timeout=30).json()
    rows, seen = [], {}
    for el in data.get("elements", {}).values():
        if el.get("type") != "series":
            continue
        fred_id = (el.get("series_id") or "").strip()
        name    = (el.get("name") or "").strip()
        if not fred_id or not name:
            continue
        value = name
        if value in seen:                      # keep dim1 keys unique
            seen[value] += 1
            value = f"{name} ({fred_id})"
        else:
            seen[value] = 1
        rows.append({
            "value": value,
            "fredId": fred_id,
            "level": int(el.get("level") or 1),
            "short": name,
            "full": name,
        })
    if not rows:
        # BEA renumbers release/element ids in comprehensive revisions; an
        # empty table would silently ship an empty dropdown. Fail the build.
        sys.exit(
            f"FATAL: release {release_id} element {element_id} returned 0 series — "
            "BEA may have renumbered this table. Re-check the id on "
            "fred.stlouisfed.org/release/tables and update the constant."
        )
    return rows


def flat_category(cat_id, label, freq, entries, is_yield=False):
    series = []
    for row in entries:
        if is_yield:
            sid, fred, name, short = row
            f = "monthly"
        else:
            sid, fred, name, short, f = row
        series.append({
            "id": sid, "name": name, "chipShort": short,
            "tableId": "FRED", "freq": f, "dims": 0, "fredId": fred,
        })
    return {"id": cat_id, "label": label, "sourceFreq": freq, "series": series}


def table_series(sid, rid, eid, name, short, f, dim1_name="Series"):
    rows = fetch_table_rows(rid, eid)
    print(f"  {name}: {len(rows)} rows")
    return {
        "id": sid, "name": name, "chipShort": short,
        "tableId": "FRED", "freq": f, "dims": 1,
        "dim1Name": dim1_name, "rows": rows,
    }


def table_category(cat_id, label, freq, tables):
    series = [table_series(*t) for t in tables]
    return {"id": cat_id, "label": label, "sourceFreq": freq, "series": series}


def main():
    print("Building FRED catalog…")
    gdp_cat = flat_category("us_gdp", "🇺🇸 GDP", "quarterly", GDP_SERIES)
    gdp_cat["series"].insert(0, gdp_expenditure_series())
    catalog = {"categories": [
        gdp_cat,
        table_category("us_emp",   "🇺🇸 Employment",  "monthly",   EMPLOYMENT_TABLES),
        table_category("us_prices","🇺🇸 Prices",      "monthly",   PRICES_TABLES),
        flat_category("us_yields", "🇺🇸 U.S. yields", "monthly",   YIELD_SERIES, is_yield=True),
    ]}
    out = os.path.join(HERE, "fred_catalog.json")
    with open(out, "w") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=1)
    total = sum(
        len(s.get("rows", [1])) if s["dims"] else 1
        for c in catalog["categories"] for s in c["series"]
    )
    print(f"Wrote {out} — {len(catalog['categories'])} categories, {total} FRED series")


if __name__ == "__main__":
    main()
