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

# Fetch remote Last-Modified and Content-Length via Chrome TLS impersonation
REMOTE=$(python3 - <<'EOF'
from curl_cffi import requests
try:
    r = requests.get(
        "https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip",
        impersonate="chrome", stream=True, timeout=15
    )
    lm = r.headers.get("Last-Modified", "")
    cl = r.headers.get("Content-Length", "")
    r.close()
    print(f"{lm}|||{cl}")
except Exception as e:
    print(f"ERROR: {e}")
EOF
)

if [[ "$REMOTE" == ERROR:* ]]; then
    echo "    Could not reach lobbycanada.gc.ca: ${REMOTE#ERROR: }"
    echo "    Skipping update."
    exit 0
fi

REMOTE_LM="${REMOTE%%|||*}"
REMOTE_CL="${REMOTE##*|||}"

# Read stored values from the existing DB (if it exists)
if [ -f "$DB" ]; then
    LOCAL_LM=$(python3 -c "
import sqlite3, sys
try:
    con = sqlite3.connect('$DB')
    row = con.execute(\"SELECT value FROM meta WHERE key='source_last_modified'\").fetchone()
    print(row[0] if row else '')
except: print('')
")
    LOCAL_CL=$(python3 -c "
import sqlite3, sys
try:
    con = sqlite3.connect('$DB')
    row = con.execute(\"SELECT value FROM meta WHERE key='source_file_size'\").fetchone()
    print(row[0] if row else '')
except: print('')
")
else
    LOCAL_LM=""
    LOCAL_CL=""
fi

# Compare — skip full rebuild if ZIP is unchanged, but always run patch
ZIP_CHANGED=true
if [ -n "$REMOTE_LM" ] && [ "$REMOTE_LM" = "$LOCAL_LM" ]; then
    echo "    No change in open-data ZIP (Last-Modified: $REMOTE_LM). Skipping full rebuild."
    ZIP_CHANGED=false
elif [ -z "$REMOTE_LM" ] && [ -n "$REMOTE_CL" ] && [ "$REMOTE_CL" = "$LOCAL_CL" ]; then
    echo "    No change in open-data ZIP (Content-Length: $REMOTE_CL). Skipping full rebuild."
    ZIP_CHANGED=false
fi

if [ "$ZIP_CHANGED" = true ]; then
    echo "    New open-data ZIP detected (remote: $REMOTE_LM, local: $LOCAL_LM). Rebuilding ..."
    # ── 1. Full rebuild from open-data ZIP ──────────────────────────────────────
    echo "==> Building lobby.db ..."
    python3 -u lobbyist/build_db.py
fi

# ── 1b. Always patch with real-time records from the live registry ────────────
echo "==> Patching with recent live records ..."
PATCH_OUTPUT=$(python3 -u lobbyist/patch_recent.py 2>&1)
echo "$PATCH_OUTPUT"
PATCH_NEW=$(echo "$PATCH_OUTPUT" | sed -n 's/.*New: \([0-9][0-9]*\).*/\1/p' | tail -1)
PATCH_NEW="${PATCH_NEW:-0}"

# Skip publish/redeploy if nothing changed at all
if [ "$ZIP_CHANGED" = false ] && [ "$PATCH_NEW" = "0" ]; then
    echo ""
    echo "==> Nothing changed — no publish or redeploy needed."
    exit 0
fi

# ── 2. Publish to GitHub Releases ───────────────────────────────────────────
echo "==> Publishing to GitHub Releases (db-latest) ..."
gh release delete db-latest --yes 2>/dev/null || true
git push --delete origin db-latest 2>/dev/null || true
git tag -d db-latest 2>/dev/null || true   # drop stale local tag so gh can recreate it
gh release create db-latest lobbyist/lobby.db \
  --title "Latest Lobbyist DB" \
  --notes "Built $(date -u '+%Y-%m-%d %H:%M UTC') from lobbycanada.gc.ca open data"

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
