#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
UPLOAD_SCRIPT="$SCRIPT_DIR/upload_audio_once.sh"

port="18793"
output_dir="/root/.openclaw/workspace/uploads/sensevoice-local"
state_file=""
log_file=""
pid_file=""
timeout="1800"
public_base=""
listen="0.0.0.0"
max_bytes="0"

usage() {
  cat <<'USAGE'
Usage:
  start_upload_audio_once_detached.sh [--listen HOST] [--port PORT] [--public-base URL]
                                     [--output-dir DIR] [--state-file FILE] [--log-file FILE]
                                     [--pid-file FILE] [--timeout SECONDS] [--max-bytes BYTES]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --listen) listen="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    --public-base) public_base="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --state-file) state_file="$2"; shift 2 ;;
    --log-file) log_file="$2"; shift 2 ;;
    --pid-file) pid_file="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    --max-bytes) max_bytes="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

mkdir -p "$output_dir"
if [[ -z "$state_file" ]]; then
  state_file="$output_dir/state-${port}.json"
fi
if [[ -z "$log_file" ]]; then
  log_file="$output_dir/upload-${port}.log"
fi
if [[ -z "$pid_file" ]]; then
  pid_file="$output_dir/upload-${port}.pid"
fi
mkdir -p "$(dirname -- "$state_file")" "$(dirname -- "$log_file")" "$(dirname -- "$pid_file")"

if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    sleep 1
  fi
fi

cmd=(bash "$UPLOAD_SCRIPT" --listen "$listen" --port "$port" --output-dir "$output_dir" --timeout "$timeout" --max-bytes "$max_bytes" --state-file "$state_file")
if [[ -n "$public_base" ]]; then
  cmd+=(--public-base "$public_base")
fi

nohup "${cmd[@]}" >"$log_file" 2>&1 &
pid=$!
echo "$pid" > "$pid_file"

for _ in $(seq 1 50); do
  if [[ -s "$state_file" ]]; then
    cat "$state_file"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

echo "Detached upload server failed to become ready. See log: $log_file" >&2
if [[ -f "$log_file" ]]; then
  tail -n 50 "$log_file" >&2 || true
fi
exit 1
