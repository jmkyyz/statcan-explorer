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
returns **HTTP 403** to GitHub-hosted runners. The block began between the
2026-07-19 run (reached the registry, patch step ran) and the 2026-07-20 run
(check step returned in 0s, everything downstream skipped), and has been
continuous since.

The site is behind bot protection that appears to have rolled out in stages,
challenging low-reputation IP ranges first:

- **Datacenter IPs: blocked since 2026-07-20** (first-hand, from the run logs
  above). Corroborated independently: a colleague's separate fork, running on
  his employer's servers, now hits a Cloudflare "are you a human" interstitial
  that breaks its daily and weekly downloads. Both data points are
  datacenter-class egress.
- **Residential IPs: unknown.** The last confirmed success from one was the
  Mac's 2026-07-21 publish, the day after the datacenter block began. Nothing
  since has tested it, in either direction. Do not assume either way — test it
  before designing around it (see below).

This matters for what a fix can be. `curl_cffi`'s Chrome impersonation defeats
JA3/TLS fingerprinting, but **no TLS-impersonating HTTP client can clear a
managed challenge** — that needs JS execution and a solved Turnstile. So a
self-hosted runner on the Mac is worth trying only if a residential IP still
passes. Settle that first, from the Mac, before building anything:

    python3 -c "
    from curl_cffi import requests
    r = requests.get('https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip',
                     impersonate='chrome', stream=True, timeout=30)
    print(r.status_code, r.headers.get('Content-Length'), r.headers.get('cf-mitigated'))
    r.close()"

200 with a Content-Length in the hundreds of MB means residential still works.
403 — especially with a `cf-mitigated: challenge` header — means it does not,
and only a real browser or a different source will do.

Prefer changing source over escalating the arms race. The Office of the
Commissioner of Lobbying publishes to the federal open-data portal, and this
repo already has working CKAN patterns against it — `proxy.py:102` (`ckan_proxy`,
which notes it "strips WAF-triggering headers") and `ev_change_detector.py:28`.
A CKAN resource for the registry would be the same data on different
infrastructure. Verify that first; browser automation against lobbycanada.gc.ca
is the fallback, not the plan.

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
