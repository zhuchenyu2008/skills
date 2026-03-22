#!/usr/bin/env bash
set -euo pipefail

# One-click safe Obsidian Headless Sync for the review workflow.
# This is copied from obsidian-study-notes and kept here so this skill is self-contained.
# Configure the vault path via OBSIDIAN_VAULT_PATH or edit the fallback below.

VAULT_PATH="${OBSIDIAN_VAULT_PATH:-/data/obsidian-vault}"
LOCK_DIR="$VAULT_PATH/.obsidian/.sync.lock"

# Best-effort detection: if an 'ob sync' process is running, do not touch the lock.
if ps -eo pid,args | grep -E "(^|[[:space:]])ob([[:space:]]|$)" | grep -F " sync" | grep -v grep >/dev/null 2>&1; then
  echo "[sync_safe] Detected running 'ob sync' process. Skip lock cleanup."
else
  if [ -d "$LOCK_DIR" ]; then
    echo "[sync_safe] Removing stale lock (attempt): $LOCK_DIR"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    if [ -d "$LOCK_DIR" ]; then
      echo "[sync_safe] Lock directory is not empty or could not be removed."
      echo "[sync_safe] Contents:"
      ls -la "$LOCK_DIR" || true
      echo "[sync_safe] Refusing to continue to avoid masking a real concurrent sync."
      echo "[sync_safe] If you are sure no 'ob sync' is running, remove the lock manually."
      exit 1
    fi
  fi
fi

echo "[sync_safe] Running sync for: $VAULT_PATH"
ob sync --path "$VAULT_PATH"
