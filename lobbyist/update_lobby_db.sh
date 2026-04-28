#!/usr/bin/env bash
# update_lobby_db.sh
# Run daily to pull fresh data from lobbycanada.gc.ca,
# publish lobby.db to GitHub Releases, and redeploy on Render.
# Skips the build entirely if the remote zip hasn't changed.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB="$SCRIPT_DIR/lobby.db"

echo "==> Checking for new data ..."
cd "$REPO_ROOT"

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

# Compare — skip if both Last-Modified and size are unchanged
if [ -n "$REMOTE_LM" ] && [ "$REMOTE_LM" = "$LOCAL_LM" ]; then
    echo "    No change (Last-Modified: $REMOTE_LM). Skipping build."
    exit 0
fi
if [ -z "$REMOTE_LM" ] && [ -n "$REMOTE_CL" ] && [ "$REMOTE_CL" = "$LOCAL_CL" ]; then
    echo "    No change (Content-Length: $REMOTE_CL). Skipping build."
    exit 0
fi

echo "    New data detected (remote: $REMOTE_LM, local: $LOCAL_LM). Rebuilding ..."

# ── 1. Build the database ────────────────────────────────────────────────────
echo "==> Building lobby.db ..."
python3 -u lobbyist/build_db.py

# ── 2. Publish to GitHub Releases ───────────────────────────────────────────
echo "==> Publishing to GitHub Releases (db-latest) ..."
gh release delete db-latest --yes 2>/dev/null || true
git push --delete origin db-latest 2>/dev/null || true
gh release create db-latest lobbyist/lobby.db \
  --title "Latest Lobbyist DB" \
  --notes "Built $(date -u '+%Y-%m-%d %H:%M UTC') from lobbycanada.gc.ca open data"

# ── 3. Trigger Render redeploy ───────────────────────────────────────────────
if [ -n "$RENDER_DEPLOY_HOOK" ]; then
  echo "==> Triggering Render redeploy ..."
  curl -s -X POST "$RENDER_DEPLOY_HOOK"
  echo ""
  echo "    Render is rebuilding — takes ~2 min, then the app will have fresh data."
else
  echo ""
  echo "    Skipping Render deploy (RENDER_DEPLOY_HOOK not set)."
  echo "    Set it in your shell profile or trigger a redeploy manually in Render."
fi

echo ""
echo "==> Done."
