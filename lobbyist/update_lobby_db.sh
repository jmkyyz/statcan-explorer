#!/usr/bin/env bash
# update_lobby_db.sh
# Run this weekly to pull fresh data from lobbycanada.gc.ca,
# publish lobby.db to GitHub Releases, and redeploy on Render.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 1. Build the database ────────────────────────────────────────────────────
echo "==> Building lobby.db ..."
cd "$REPO_ROOT"
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
