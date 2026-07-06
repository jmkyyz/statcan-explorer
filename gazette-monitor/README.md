# Canada Gazette Regulatory Monitor

Personal workflow tool for a journalist: monitors the Canada Gazette
(Part I — proposed regulations, weekly Saturdays; Part II — enacted
regulations, biweekly Wednesdays; Part III — Acts of Parliament) and
matches new items against a keyword watchlist organized by beat.

## How it works

- The three Gazette RSS feeds signal new **issues** (one RSS item = one
  whole issue). Each new issue's HTML index page is fetched and parsed
  down to individual items: section, department, enabling act, title, link.
- For Part I **Proposed Regulations**, the item page is also fetched to
  extract the Regulatory Impact Analysis Statement (RIAS, first 2,000
  characters) and the **comment deadline** (explicit date, or computed
  from "within N days after the date of publication").
- Part II index pages are flat lists (no department metadata); the SOR/SI
  registration number is appended to the title. Part III links straight
  to a PDF, so each Part III issue is stored as a single title-level item.
- Every ingest run re-evaluates **all** stored items against all active
  rules (`INSERT OR IGNORE` + a unique item/rule constraint), so adding or
  editing a rule retroactively matches history on the next run.
- Matching is a transparent case-insensitive **whole-word** check
  (tolerating plural "s"/"es") over `title + RIAS + department`, with
  `any`/`all` keyword modes and an optional department-substring filter.
  Whole-word rather than substring because "rent" would otherwise match
  "current" and "import" would match "important". Multi-word keywords
  work ("greenhouse gas" also hits "greenhouse gases").

## Setup

The app lives in `~/statcan-explorer/gazette-monitor` (outside `~/Desktop`
so the cron ingest avoids macOS TCC folder restrictions) and runs on the
system Python at `/usr/local/bin/python3`, which has the dependencies
installed (`pip3 install -r requirements.txt` if starting fresh).

```bash
cd ~/statcan-explorer/gazette-monitor

# First run: creates database.db, seeds 5 default beat rules,
# and backfills the last 4 weeks of issues (~1–2 minutes; the
# ingester waits 1 s between requests to gazette.gc.ca).
python3 ingest.py --init

# Start the web UI
python3 app.py
```

Then open <http://localhost:5006>.

- **Feed** (`/`) — matched items, newest first, with Part/date/rule filters,
  comment-deadline countdowns (highlighted when under 30 days, red under 7),
  and per-item mark-as-seen.
- **Watchlist** (`/watchlist`) — add / edit / delete / enable-disable rules.
- **Run ingest** (`/run-ingest`) — manual trigger with a run log.

## Scheduling the daily ingest

Installed in the user crontab (July 4, 2026):

```cron
30 8 * * * cd /Users/jasonkirby/statcan-explorer/gazette-monitor && /usr/local/bin/python3 ingest.py >> ingest.log 2>&1
```

Runs at 8:30 a.m. daily. The pipeline is idempotent — `index_url` and
`item_url` are UNIQUE and inserts use `INSERT OR IGNORE` — so re-runs and
overlapping lookback windows never create duplicates. `--lookback N`
widens the catch-up window beyond the default 28 days.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app + routes (feed, watchlist, run-ingest) |
| `ingest.py` | Ingestion pipeline, callable standalone or from the app |
| `models.py` | SQLite schema + seed rules |
| `database.db` | SQLite data file (gitignored) |

## Notes

- Digest tracking: the `matches` table has a `seen` flag; a weekly digest
  job can read `WHERE seen = 0`, send a summary, then mark rows seen.
- The parser logs warnings instead of crashing when a Gazette page
  doesn't match the expected structure (the site occasionally changes).
- No authentication — local, personal use only.
