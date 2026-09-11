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
- **Residential IPs: blocked as well, confirmed 2026-09-11.** Probed from the
  Mac with `lobbyist/check_sources.py`: all three endpoints — both bulk ZIPs
  *and* the live recent-comms endpoint — return `HTTP 403` with
  `cf-mitigated: challenge` and `server: cloudflare` (edge YYZ). The wall is
  now universal, so relocating the job to the Mac or a self-hosted runner
  cannot work. Note this kills `patch_recent.py` too, not just the bulk
  rebuild: the entire lobbycanada.gc.ca surface is unreachable programmatically.

`cf-mitigated: challenge` means a *challenge*, not a block — a human in a real
browser still downloads these files fine. The data has not been withdrawn; it
has become machine-inaccessible. Since the OCL publishes these exports
expressly for reuse, that is plausibly an unintended side-effect of a WAF
rule, which makes asking them to fix or exempt it a real option rather than a
last resort.

`curl_cffi`'s Chrome impersonation defeats JA3/TLS fingerprinting, but **no
TLS-impersonating HTTP client can clear a managed challenge** — that needs JS
execution and a solved Turnstile. With residential now blocked too, no
relocation of the job fixes this; only a different source, a real browser, or
an exemption from the OCL will. To re-check the wall later:

    python3 -c "
    from curl_cffi import requests
    r = requests.get('https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip',
                     impersonate='chrome', stream=True, timeout=30)
    print(r.status_code, r.headers.get('Content-Length'), r.headers.get('cf-mitigated'))
    r.close()"

Or just run `python3 lobbyist/check_sources.py`, which probes this and the
open-data catalogue together and prints a verdict.

**The open-data portal is not a way around it** (checked 2026-09-11). The OCL
does publish both datasets on open.canada.ca — "Lobbying Registrations"
(`70ef2117-1095-4d77-80eb-b87f2bada2a4`) and "Monthly Communication Reports"
(`a34eb330-7136-4f5e-9f5f-3ba41df58b06`) — but their resource URLs are the very
same `lobbycanada.gc.ca/media/...` ZIPs the pipeline already fetches. The
catalogue entry is a pointer, not a copy, so it lands on the same wall. CKAN
is still worth polling as a *signal* (see below); it is not a download path.

Two useful facts did come out of that check:

- Both datasets declare **`frequency=P1W`** — the OCL considers this weekly
  data. A weekly bulk refresh is ample for the alert's 14-day window, so
  losing `patch_recent.py`'s daily top-up costs little once access is restored.
- Both records show `metadata_modified` of 2026-09-07, so the OCL is still
  actively publishing. Only our access is broken. (Their resource-level
  `last_modified` still reads 2016-11-02 — stale since registration, and a
  reminder not to trust CKAN timestamps for change detection.)

That makes **asking the OCL the primary route, not a courtesy**: they publish
these files on the federal open-data portal for reuse, and the portal's own
links now return 403 to every programmatic client. That reads as a WAF rule
with an unintended blast radius rather than a deliberate policy, and it is
concrete enough to report — name the two dataset IDs and the 403.

Browser automation against lobbycanada.gc.ca is the fallback if that goes
nowhere. Check their terms of use first, and expect it to break whenever the
rule is retuned.

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
