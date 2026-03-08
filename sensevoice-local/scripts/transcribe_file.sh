#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${SENSEVOICE_RUNTIME_DIR:-/opt/sensevoice-local}"
exec bash "$RUNTIME_DIR/scripts/transcribe_file.sh" "$@"
