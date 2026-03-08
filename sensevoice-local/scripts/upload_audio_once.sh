#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/serve_upload_once.py"

listen="0.0.0.0"
port="18793"
public_base=""
default_public_host="${PUBLIC_UPLOAD_HOST:-127.0.0.1}"
output_dir="${SENSEVOICE_UPLOAD_DIR:-./uploads/sensevoice-local}"
timeout="1800"
max_bytes="0"
state_file=""
title="上传课堂录音"
description="把大音频文件传到这里。上传成功后，这个临时入口会自动关闭。"
footer="支持 mp3、m4a、wav、aac、opus、ogg、flac。上传完成后继续走本地转写流程。"

usage() {
  cat <<'USAGE'
Usage:
  upload_audio_once.sh [--listen HOST] [--port PORT] [--public-base URL] [--output-dir DIR]
                       [--timeout SECONDS] [--max-bytes BYTES] [--state-file FILE]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --listen) listen="$2"; shift 2 ;;
    --port) port="$2"; shift 2 ;;
    --public-base) public_base="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    --max-bytes) max_bytes="$2"; shift 2 ;;
    --state-file) state_file="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -z "$public_base" ]]; then
  public_base="http://$default_public_host:$port"
fi

mkdir -p "$output_dir"
args=(
  --listen "$listen"
  --port "$port"
  --output-dir "$output_dir"
  --timeout "$timeout"
  --max-bytes "$max_bytes"
  --title "$title"
  --description "$description"
  --footer "$footer"
)

if [[ -n "$public_base" ]]; then
  args+=(--public-base "$public_base")
fi
if [[ -n "$state_file" ]]; then
  mkdir -p "$(dirname -- "$state_file")"
  args+=(--result-json "$state_file")
fi

exec python3 "$PY_SCRIPT" "${args[@]}"
