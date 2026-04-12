#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${OPENCLAW_WORKSPACE:-/opt/openclaw/workspace}"
RUNTIME_DIR="${SENSEVOICE_RUNTIME_DIR:-$WORKSPACE_DIR/sensevoice-local}"
exec bash "$RUNTIME_DIR/scripts/transcribe_file.sh" "$@"
