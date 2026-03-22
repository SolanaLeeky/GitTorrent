#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────────────
# setup.sh — Create a new GitTorrent peer node repository.
#
# Usage:
#   ./peer/setup.sh <owner/peer-repo-name> <owner/tracker-repo> [--dry-run]
#
# Example:
#   ./peer/setup.sh myuser/peer-node-01 myuser/torrent-tracker
#
# Prerequisites:
#   - gh CLI installed and authenticated
#   - NETWORK_TOKEN env var set (GitHub PAT with repo scope)
# ───────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Args ───────────────────────────────────────────────────────────
if [ $# -lt 2 ]; then
  echo "Usage: $0 <owner/peer-repo> <owner/tracker-repo> [--dry-run]"
  echo "  Example: $0 myuser/peer-node-01 myuser/torrent-tracker"
  exit 1
fi

PEER_REPO="$1"
TRACKER_REPO="$2"
DRY_RUN=false
if [ "${3:-}" = "--dry-run" ]; then
  DRY_RUN=true
fi

PEER_NAME=$(echo "$PEER_REPO" | cut -d'/' -f2)
OWNER=$(echo "$PEER_REPO" | cut -d'/' -f1)

echo "═══════════════════════════════════════════════"
echo "  GitTorrent Peer Setup"
echo "  Peer:    $PEER_REPO"
echo "  Tracker: $TRACKER_REPO"
echo "═══════════════════════════════════════════════"

if $DRY_RUN; then
  echo "[DRY RUN] Would perform the following steps:"
  echo "  1. Create repo: $PEER_REPO"
  echo "  2. Copy workflow files to .github/workflows/"
  echo "  3. Copy config.json, manifest.json, update_manifest.py"
  echo "  4. Set NETWORK_TOKEN secret"
  echo "  5. Create chunks/ directory"
  echo "  6. Push initial commit"
  echo "[DRY RUN] No changes made."
  exit 0
fi

# ── Validate prerequisites ─────────────────────────────────────────
if ! command -v gh &>/dev/null; then
  echo "ERROR: gh CLI not found. Install from https://cli.github.com"
  exit 1
fi

if [ -z "${NETWORK_TOKEN:-}" ]; then
  echo "ERROR: NETWORK_TOKEN env var not set."
  echo "  Export a GitHub PAT with repo scope: export NETWORK_TOKEN=ghp_..."
  exit 1
fi

# ── Create repo ────────────────────────────────────────────────────
TMPDIR=$(mktemp -d)
echo "Working in $TMPDIR"

echo "Creating repository $PEER_REPO..."
gh repo create "$PEER_REPO" --public --clone --description "GitTorrent peer node" || {
  echo "Repo may already exist. Cloning..."
  gh repo clone "$PEER_REPO" "$TMPDIR/$PEER_NAME"
}

cd "$TMPDIR/$PEER_NAME" 2>/dev/null || cd "$TMPDIR"

# If we're not in the cloned repo, clone it
if [ ! -d .git ]; then
  gh repo clone "$PEER_REPO" .
fi

# ── Copy peer files ────────────────────────────────────────────────
echo "Copying peer files..."

# Workflows
mkdir -p .github/workflows
cp "$SCRIPT_DIR/store.yml"     .github/workflows/store.yml
cp "$SCRIPT_DIR/fetch.yml"     .github/workflows/fetch.yml
cp "$SCRIPT_DIR/heartbeat.yml" .github/workflows/heartbeat.yml
cp "$SCRIPT_DIR/replicate.yml" .github/workflows/replicate.yml
cp "$SCRIPT_DIR/prune.yml"     .github/workflows/prune.yml

# Config + manifest
cp "$SCRIPT_DIR/update_manifest.py" update_manifest.py

# Write config with correct tracker repo
cat > config.json <<EOF
{
  "tracker_repo": "$TRACKER_REPO",
  "network_token_secret": "NETWORK_TOKEN",
  "storage_limit_mb": 2000,
  "heartbeat_interval_hours": 6,
  "chunk_expiry_days": 30,
  "auto_prune": true,
  "accept_new_chunks": true,
  "max_concurrent_fetches": 3
}
EOF

# Seed manifest
cat > manifest.json <<EOF
{
  "peer_id": "$PEER_REPO",
  "tracker": "$TRACKER_REPO",
  "storage_limit_mb": 2000,
  "storage_used_mb": 0,
  "chunk_count": 0,
  "chunks": {},
  "last_updated": ""
}
EOF

# Chunks directory
mkdir -p chunks
touch chunks/.gitkeep

# README
cat > README.md <<EOF
# $PEER_NAME

GitTorrent peer node. Part of the [$TRACKER_REPO](https://github.com/$TRACKER_REPO) network.

**Status**: Online
**Storage limit**: 2 GB
EOF

# ── Set secret ─────────────────────────────────────────────────────
echo "Setting NETWORK_TOKEN secret..."
echo "$NETWORK_TOKEN" | gh secret set NETWORK_TOKEN --repo "$PEER_REPO"

# ── Commit and push ────────────────────────────────────────────────
echo "Committing and pushing..."
git config user.name "SolanaLeeky"
git config user.email "SolanaLeeky@users.noreply.github.com"
git add -A
git commit -m "Initialize GitTorrent peer node

Tracker: $TRACKER_REPO
Workflows: store, fetch, heartbeat, replicate, prune"

git push origin main 2>/dev/null || git push origin master

# ── Cleanup ────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "  Peer $PEER_REPO created successfully!"
echo ""
echo "  Next steps:"
echo "  1. Register with tracker:"
echo "     Open issue on $TRACKER_REPO titled:"
echo "     REGISTER_PEER $PEER_REPO"
echo ""
echo "  2. Verify heartbeat runs (check Actions tab)"
echo "═══════════════════════════════════════════════"
