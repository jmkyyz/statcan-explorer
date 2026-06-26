# Canada Trade Explorer

A Canadian merchandise-trade explorer (USA-Trade-Online style) over the StatCan
**CIMT** bulk annual CSVs, using a local **DuckDB + Hive-partitioned Parquet**
store so aggregations are sub-second — no per-vector WDS round-trips. (Internal
dir/code name remains `cimt`.)

Status: **Phases 1–3 complete** — ingest pipeline + rollups + dimension lookups
(Phase 1), the Flask query API on port 5003 (Phase 2), and the query-builder UI
`cimt-explorer.html` served at `/` (Phase 3). Phase 4 (monthly refresh) and
Phase 5 (optional R2 publish) are not built. The store currently holds only the
2007/2012/2017/2023 sample — run the full backfill (`ingest.py --years
2007-2026`) when ready.

Open it: `python api.py` then visit http://127.0.0.1:5003/

## Phase 0 findings (verified 2026-06-26)

Bulk source — one zip per flow per year, **same path for every year 2007–present**:

```
https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_<FLOW>_<YEAR>.zip
  <FLOW> = Imp | Tot_Exp | Dom_Exp
```

Each zip contains:
- one **HS-detail** CSV — imports = **HS10**, exports = **HS8**
- StatCan's own HS6 / HS2 rollup CSVs (we use these only to cross-check ours)
- fixed-width dimension lookup `.TXT` files

Key facts that shaped the pipeline:
- **Data CSVs are UTF-8** (CRLF). **Dimension `.TXT` files are Latin-1.**
- **Schema asymmetry:** imports carry a `Province` column, **exports do not**
  (both carry `State`). Columns are mapped by header name, not position.
- Columns: `YearMonth, HS, Country, [Province,] State, Value[, Quantity, UoM]`.
- **Quantity is not always summable:** ~2.6% of HS6 codes mix units of measure
  among their children. Rollups sum quantity only when the UoM is consistent,
  otherwise quantity/uom are nulled.
- Our HS10→HS6 / HS8→HS6 rollups **reproduce StatCan's shipped rollups exactly**
  (row count + total value). 2023 totals: imports $757.1B, exports $767.9B.
- **No HS4 description file is shipped** (only HS2/HS6/HS8/HS10). `dimensions.py`
  fills this by pulling the ~1,229 standard WCO HS4 headings from a public-domain
  dataset, so the product tree is labelled at every level.
- Footprint: 2023 imports+exports ≈ 180 MB Parquet. Full 2007–present, 3 flows
  ≈ 4–5 GB (within the plan's 5–12 GB estimate).

## Layout

```
cimt/
  ingest.py        download zips → detail Parquet + HS8/6/4/2 rollups
  dimensions.py    parse Latin-1 fixed-width lookups → dim Parquet
  data/            (git-ignored)
    raw/           downloaded zips
    parquet/
      detail/flow=<imp|exp_tot|exp_dom>/year=<yyyy>/data.parquet   HS10/HS8
      hs8|hs6|hs4|hs2/flow=…/year=…/data.parquet                   rollups
      dim/dim_hs|dim_country|dim_province|dim_state|dim_uom.parquet
```

Unified fact schema (every flow/tier): `month, hs, country, province, state,
value, quantity, uom` + partitions `flow, year`. `province` is null for exports.

## Usage

```bash
pip install duckdb pyarrow requests          # one-time

# Ingest (downloads zips if absent; idempotent per flow-year):
python ingest.py --years 2023                       # one year, all 3 flows
python ingest.py --years 2007-2026                  # full backfill
python ingest.py --years 2023 --flows imp,exp_tot   # subset of flows
python ingest.py --years 2023 --no-download         # use cached zips

# Dimension lookups (codes/labels update yearly — use the newest year):
python dimensions.py                                # newest zip in data/raw
python dimensions.py --year 2025
```

### Query example (DuckDB)

```python
import duckdb
con = duckdb.connect()
P = "data/parquet"
con.execute(f"""
  SELECT c.en partner, sum(f.value) v
  FROM read_parquet('{P}/hs2/**/*.parquet', hive_partitioning=true) f
  JOIN read_parquet('{P}/dim/dim_country.parquet') c
    ON f.country=c.code AND c.valid_to='999912'
  WHERE f.flow='imp' AND f.year=2023 AND f.hs='87'   -- vehicles
  GROUP BY 1 ORDER BY v DESC LIMIT 5
""").fetchall()    # → US $73.8B, MX $17.5B, JP $8.9B, KR $7.0B, DE $6.0B; ~5 ms
```

## Query API (Phase 2)

```bash
pip install -r requirements.txt
python api.py            # http://127.0.0.1:5003  (CIMT_HOST/PORT/CIMT_DATA env-configurable)
```

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/health` | store status + flow-years present |
| `GET  /api/dimensions` | dropdown data: countries, provinces, states, UoM, HS2 chapters |
| `GET  /api/hs/children?flow&code` | next HS level under a parent code (tree drill-down) |
| `POST /api/query` | aggregated pivot query (JSON in/out) |
| `POST /api/export` | same query as an `.xlsx` download |

`/api/query` body (all filters optional except `flow`):

```jsonc
{
  "flow": "imp",                              // imp | exp_tot | exp_dom
  "hs_level": 2,                              // tier to read: 2/4/6/8, else detail
  "filters": {
    "hs": ["87"],                            // HS code prefixes (any-of)
    "country": ["US","MX"], "province": ["ON"],
    "year": {"from": 2017, "to": 2023},      // or [2017,2023]; also "month": [1..12]
  },
  "group_by": ["year","country"],            // any of year/month/hs/country/province/state/uom
  "measure": "value",                        // value | quantity (qty nulled when UoM mixes)
  "limit": 1000
}
```

The API runs on the rollup tiers, so typical queries return in a few ms (the
first query after start-up is ~200 ms while DuckDB warms the Parquet cache).
`/api/query` also accepts `filters.period = {from:"YYYYMM", to:"YYYYMM"}` for
month-precise ranges, and sorts time-series breakdowns chronologically.

## Query-builder UI (Phase 3)

`cimt-explorer.html` (served at `/`) — single-file vanilla-JS app, Chart.js, the
StatCan Explorer design system. Pick a flow; optionally filter by product (HS
tree drill-down), partner country, province, and a month-precise time range;
"break down by" country / province / HS chapter-heading-subheading / yearly /
monthly; for over-time views, show level or period-over-period / year-over-year
% change. Results render as a chart + share table with an `.xlsx` export. Run
queries are national by default (province filter optional).

## Monthly refresh (Phase 4)

StatCan trade releases lag ~6 weeks. The current-year zip holds all YTD months
and is the only **mutable** partition; prior years can still see small
back-revisions. `refresh.py` re-downloads (forced) the current + previous year,
re-ingests them (idempotent partition overwrite), and rebuilds the dimension
labels. A lock file guards against overlapping runs.

```bash
python refresh.py                  # current + previous year
python refresh.py --years 2026     # one year
```

**Trigger (macOS launchd) — fires on the actual release dates.** StatCan
publishes the merchandise-trade release calendar; those dates live in
`release_dates.txt`, and `make_refresh_plist.py` turns them into the launchd
agent — one trigger per release day at **08:35 local (ET)**, ~5 min after the
08:30 release. With `--retry`, the job re-checks every 15 min for ~1h45m if the
bulk file posts late, so the app is current the morning you need it.

The job runs from the TCC-safe `~/statcan-explorer` clone (background jobs can't
read `~/Desktop`), like the EV detector and the other StatCan jobs.

```bash
# 1. ensure cimt/ and its data/ exist under ~/statcan-explorer
#    (git pull there; seed data by copying ~/Desktop/StatCanApp/cimt/data over,
#     or run `python ingest.py --years 2007-2026` once from that clone)
# 2. (re)generate the plist from the date list, then install + load it
python ~/statcan-explorer/cimt/make_refresh_plist.py
cp ~/statcan-explorer/cimt/com.statcan.cimt-refresh.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.statcan.cimt-refresh.plist
launchctl enable gui/$(id -u)/com.statcan.cimt-refresh

# verify / run once now / inspect logs
launchctl list | grep cimt
launchctl kickstart -k gui/$(id -u)/com.statcan.cimt-refresh
tail -f ~/statcan-explorer/cimt/cimt_refresh.log
```

The current date list runs through the **Feb 2027** release (December 2026
data). When StatCan publishes the next schedule, append the dates to
`release_dates.txt`, re-run `make_refresh_plist.py`, and re-`bootout`/`bootstrap`
the agent. launchd uses the Mac's **local** time, so these assume the machine is
on Eastern; change `RELEASE_HOUR/MIN` in `make_refresh_plist.py` otherwise. If
the Mac is asleep at 08:35, launchd runs the job on wake.
