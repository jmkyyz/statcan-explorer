#!/usr/bin/env bash
# update_lobby_db.sh
# Run daily to pull fresh data from lobbycanada.gc.ca,
# publish lobby.db to GitHub Releases, and redeploy on Render.
# Skips the build entirely if the remote zip hasn't changed.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB="$SCRIPT_DIR/lobby.db"

# --- Loud failure handling -------------------------------------------------
# Anything that exits non-zero (or an explicit `fail`) prints a single
# greppable !!! UPDATE FAILED !!! marker so a silent failure can't hide in the
# log again (see the 13-day RENDER_DEPLOY_HOOK outage, June 2026).
fail() {
    echo ""
    echo "!!! UPDATE FAILED !!! $1"
    exit 1
}
trap 'rc=$?; [ $rc -ne 0 ] && echo "" && echo "!!! UPDATE FAILED !!! (line $LINENO, exit $rc)"' ERR

echo "==> Checking for new data ..."
cd "$REPO_ROOT"

# Keep this clone current so scheduled runs pick up the latest committed code.
# Fast-forward only; if it can't (local edits / diverged), keep going with what we have.
git pull --ff-only >/dev/null 2>&1 && echo "    Synced to latest ($(git rev-parse --short HEAD))." \
    || echo "    (git pull skipped — running with current code)"

# Fetch remote Last-Modified and Content-Length for BOTH open-data ZIPs
# (communications + registrations) via Chrome TLS impersonation.
REMOTE=$(python3 - <<'EOF'
from curl_cffi import requests
URLS = {
    "comms": "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip",
    "regs":  "https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip",
}
try:
    out = []
    for _, url in URLS.items():
        r = requests.get(url, impersonate="chrome", stream=True, timeout=15)
        out.append(r.headers.get("Last-Modified", ""))
        out.append(r.headers.get("Content-Length", ""))
        r.close()
    # comms_lm|||comms_cl|||regs_lm|||regs_cl
    print("|||".join(out))
except Exception as e:
    print(f"ERROR: {e}")
EOF
)

if [[ "$REMOTE" == ERROR:* ]]; then
    echo "    Could not reach lobbycanada.gc.ca: ${REMOTE#ERROR: }"
    echo "    Skipping update."
    exit 0
fi

# Split the "a|||b|||c|||d" payload (awk is reliable with the multi-char delimiter)
REMOTE_LM=$(echo "$REMOTE"     | awk -F'\\|\\|\\|' '{print $1}')
REMOTE_CL=$(echo "$REMOTE"     | awk -F'\\|\\|\\|' '{print $2}')
REG_REMOTE_LM=$(echo "$REMOTE" | awk -F'\\|\\|\\|' '{print $3}')
REG_REMOTE_CL=$(echo "$REMOTE" | awk -F'\\|\\|\\|' '{print $4}')

# Read stored values from the existing DB (if it exists)
db_meta() {  # $1 = meta key
    [ -f "$DB" ] || { echo ""; return; }
    python3 -c "
import sqlite3
try:
    con = sqlite3.connect('$DB')
    row = con.execute(\"SELECT value FROM meta WHERE key='$1'\").fetchone()
    print(row[0] if row else '')
except: print('')
"
}
LOCAL_LM=$(db_meta source_last_modified)
LOCAL_CL=$(db_meta source_file_size)
REG_LOCAL_LM=$(db_meta reg_source_last_modified)
REG_LOCAL_CL=$(db_meta reg_source_file_size)

# Returns "true" if a remote ZIP differs from what the DB was built from.
zip_changed() {  # $1 remote_lm  $2 local_lm  $3 remote_cl  $4 local_cl
    if [ -n "$1" ] && [ "$1" = "$2" ]; then echo false; return; fi
    if [ -z "$1" ] && [ -n "$3" ] && [ "$3" = "$4" ]; then echo false; return; fi
    echo true
}
COMMS_CHANGED=$(zip_changed "$REMOTE_LM" "$LOCAL_LM" "$REMOTE_CL" "$LOCAL_CL")
REG_CHANGED=$(zip_changed "$REG_REMOTE_LM" "$REG_LOCAL_LM" "$REG_REMOTE_CL" "$REG_LOCAL_CL")

# A change in EITHER open-data ZIP warrants a full rebuild (build_db.py ingests both)
ZIP_CHANGED=false
[ "$COMMS_CHANGED" = true ] && ZIP_CHANGED=true
[ "$REG_CHANGED" = true ]   && ZIP_CHANGED=true

if [ "$ZIP_CHANGED" = false ]; then
    echo "    No change in either open-data ZIP (comms LM: $REMOTE_LM, regs LM: $REG_REMOTE_LM). Skipping full rebuild."
fi

if [ "$ZIP_CHANGED" = true ]; then
    echo "    New open-data ZIP detected (comms changed: $COMMS_CHANGED, regs changed: $REG_CHANGED). Rebuilding ..."
    # ── 1. Full rebuild from open-data ZIP ──────────────────────────────────────
    echo "==> Building lobby.db ..."
    python3 -u lobbyist/build_db.py
fi

# ── 1b. Always patch with real-time records from the live registry ────────────
echo "==> Patching with recent live records ..."
# Capture with `set -e` disabled so a non-zero exit doesn't kill the run BEFORE
# we echo the output — otherwise the actual error is swallowed and the log shows
# only a bare "UPDATE FAILED" with no cause (see the July 10 2026 patch failure).
set +e
PATCH_OUTPUT=$(python3 -u lobbyist/patch_recent.py 2>&1)
PATCH_RC=$?
set -e
echo "$PATCH_OUTPUT"
if [ "$PATCH_RC" -ne 0 ]; then
    fail "patch_recent.py exited $PATCH_RC — see its output above for the cause."
fi
PATCH_NEW=$(echo "$PATCH_OUTPUT" | sed -n 's/.*New: \([0-9][0-9]*\).*/\1/p' | tail -1)
PATCH_NEW="${PATCH_NEW:-0}"

# Skip publish/redeploy if nothing changed at all
if [ "$ZIP_CHANGED" = false ] && [ "$PATCH_NEW" = "0" ]; then
    echo ""
    echo "==> Nothing changed — no publish or redeploy needed."
    exit 0
fi

# ── 2. Publish to GitHub Releases ───────────────────────────────────────────
# Keep the db-latest release/tag in place and replace the asset in-place with
# --clobber, instead of deleting and recreating the whole release. This keeps
# the release/tag stable and shrinks the window in which the download URL 404s
# (the old delete-then-recreate could 404 a Render build for the whole upload).
echo "==> Publishing to GitHub Releases (db-latest) ..."
if ! gh release view db-latest >/dev/null 2>&1; then
  gh release create db-latest \
    --title "Latest Lobbyist DB" \
    --notes "Lobbyist DB published by update_lobby_db.sh"
fi
gh release upload db-latest lobbyist/lobby.db --clobber
gh release edit db-latest \
  --notes "Built $(date -u '+%Y-%m-%d %H:%M UTC') from lobbycanada.gc.ca open data" >/dev/null 2>&1 || true

# ── 3. Trigger Render redeploy ───────────────────────────────────────────────
# We only get here when there was something new to publish, so a missing hook
# means a fresh DB is live on GitHub but the running site is now STALE. That is
# a hard failure, not a skippable warning.
if [ -z "$RENDER_DEPLOY_HOOK" ]; then
  fail "RENDER_DEPLOY_HOOK not set — new lobby.db published to GitHub but Render was NOT redeployed; live site is STALE. Set RENDER_DEPLOY_HOOK in ~/.zshenv (not ~/.zshrc — scheduled jobs don't source it)."
fi

echo "==> Triggering Render redeploy ..."
if ! curl -fsS -X POST "$RENDER_DEPLOY_HOOK" >/dev/null; then
  fail "Render deploy hook POST failed — new lobby.db published but redeploy was not accepted; live site is STALE."
fi
echo ""
echo "    Render is rebuilding — takes ~2 min, then the app will have fresh data."

echo ""
echo "==> Done."
