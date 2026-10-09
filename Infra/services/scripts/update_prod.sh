#!/bin/bash
# Auto-update script — pulls latest code from origin/main and rebuilds if needed.
# Safe to run unattended as a cron job; exits 0 with no side-effects when already up-to-date.
#
# CRON SETUP (add to crontab — or run with --setup-cron to do it automatically):
#   0 3 * * * /home/lucascamargo/Lucas/Apps/MD70/Infra/services/scripts/update_prod.sh >> /var/log/md70_update.log 2>&1
#
# Usage:
#   ./update_prod.sh               — normal update check
#   ./update_prod.sh --setup-cron  — install the cron entry automatically
set -euo pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
# scripts → services → Infra → MD70 (repo root)
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# ── Helper ────────────────────────────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ── --setup-cron mode ─────────────────────────────────────────────────────────
if [[ "${1:-}" == "--setup-cron" ]]; then
    CRON_LINE="0 3 * * * $SCRIPT_PATH >> /var/log/md70_update.log 2>&1"

    # Check if already present to avoid duplicates
    if crontab -l 2>/dev/null | grep -qF "$SCRIPT_PATH"; then
        echo "Cron entry already exists — nothing changed."
        crontab -l 2>/dev/null | grep "$SCRIPT_PATH"
    else
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        echo "Cron entry added:"
        echo "  $CRON_LINE"
        echo ""
        echo "Current crontab:"
        crontab -l
    fi
    exit 0
fi

# ── Main update logic ─────────────────────────────────────────────────────────
log "=== MD70 update check started ==="
log "Repo root : $REPO_ROOT"

cd "$REPO_ROOT"

# Fetch remote refs — read-only, no local changes
log "Fetching origin/main..."
git fetch origin main

LOCAL_HASH="$(git rev-parse HEAD)"
REMOTE_HASH="$(git rev-parse origin/main)"
LOCAL_SHORT="${LOCAL_HASH:0:7}"
REMOTE_SHORT="${REMOTE_HASH:0:7}"

log "Local  : $LOCAL_SHORT"
log "Remote : $REMOTE_SHORT"

if [[ "$LOCAL_HASH" == "$REMOTE_HASH" ]]; then
    log "Already up to date — skipping rebuild."
    log "=== Done ==="
    exit 0
fi

log "Changes detected ($LOCAL_SHORT -> $REMOTE_SHORT) — pulling and rebuilding..."

git pull --rebase origin main

NEW_HASH="$(git rev-parse HEAD)"
log "Pulled to $(git log -1 --format='%h %s' "$NEW_HASH")"

log "Starting full build + deploy via start_prod.sh..."
bash "$SCRIPT_DIR/start_prod.sh"

log "=== Update complete ($(date '+%Y-%m-%d %H:%M:%S')) ==="
