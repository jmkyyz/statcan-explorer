# statcan-explorer — canonical repo

**This monorepo is the source of truth for every app in it.** Per-app repos on
GitHub (`canada-trade-explorer`, `lobbyist-explorer`, `statcan-econ-explorer`,
`statcan-social-explorer`) are July-2026 snapshot mirrors. Develop here.

## Why, concretely

- Every scheduled job runs from the `~/statcan-explorer` clone on the Mac —
  launchd agents write their logs to `/Users/jasonkirby/statcan-explorer/...`
  (that path is baked into the committed plists, including the one shipped in
  the `canada-trade-explorer` mirror).
- Both Render services build from here: `statcan-explorer` (root `render.yaml`
  → `proxy.py`) and `lobbyist-explorer` (`lobbyist/render.yaml`, `rootDir:
  lobbyist`). The mirrors' `render.yaml` files also say `rootDir: lobbyist`, a
  path that only exists here — a deploy from a mirror fails at build.
- The `db-latest` release lives on this repo, and both `render.yaml` files
  hardcode `github.com/jmkyyz/statcan-explorer/releases/download/db-latest/`.
- `.github/workflows/lobby-db-update.yml` (daily 14:00 UTC) is the lobbyist
  data pipeline and publishes to this repo's own release.

The mirrors were created by copying files, not by a history-preserving split,
and the source directories were never deleted from here. With no shared
ancestry, git cannot detect or report drift between the two copies — so
**always check this repo first**, whatever a mirror's README claims.

- `lobbyist/` has drifted **badly**: the mirror is frozen at 2026-07-06 and is
  missing `send_lobby_weekly.py` entirely. See that repo's README.
- `cimt/` happens to be byte-identical to its mirror today. That is luck, not a
  guarantee.

If a per-app repo is ever made real, do it properly: `git filter-repo
--subdirectory-filter <dir>` to carry history, `git rm -r` the directory here in
the same commit, and repoint the launchd agents, the Render service, and the
release URL before calling it done.

## Known broken: the lobbyist data pipeline (as of 2026-09-11)

`lobby.db` has not been updated since **2026-07-21 14:00 UTC** — that publish
came from the Mac's `update_lobby_db.sh`, which was retired when the GitHub
Actions workflow replaced it on 2026-07-18.

**The Actions workflow has never published successfully.** `lobbycanada.gc.ca`
returns **HTTP 403** to GitHub-hosted runners; `curl_cffi`'s Chrome TLS
impersonation defeats JA3 fingerprinting but not a datacenter-IP block. The
registry is reachable from a residential IP — this is not a dead data source.

Fixing the fetch is not enough on its own. Three layers each convert this
outage into a silent success, and any fix should close them:

1. `lobby-db-update.yml`, "Check registry" step — a fetch exception prints
   `rebuild=skip` and `sys.exit(0)`, so every later step is skipped and the run
   is green. 55 consecutive green runs, zero data.
2. `lobbyist/patch_recent.py:90` — `fetch_all_chunks()` catches every chunk
   failure and returns what it has, so total failure reports `New: 0`.
3. `lobbyist/send_lobby_weekly.py` — never checks data freshness. `open_db()`
   validates that the file opens and the tables exist, but nothing reads
   `meta.built_at`/`patched_at` or `MAX(posted_date)`. A frozen DB yields an
   empty 14-day window, which renders as a confident "quiet week" email.

A staleness guard in (3) is the highest-value single change: it makes this
class of outage impossible to sit through unnoticed again.
