#!/usr/bin/env python3
import argparse
import cgi
import html
import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

AUDIO_ACCEPT = ".mp3,.m4a,.wav,.aac,.opus,.ogg,.oga,.flac,.amr,.wma"
DEFAULT_TITLE = "上传课堂录音"
DEFAULT_DESCRIPTION = "把大音频文件传到这里。上传成功后，这个临时入口会自动关闭。"
DEFAULT_FOOTER = "支持常见音频格式；建议文件名带上课程信息，方便后续归档。"


def sanitize_filename(name: str) -> str:
    cleaned = Path(name).name.strip().replace("\x00", "")
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    return cleaned or f"upload-{int(time.time())}"


class UploadState:
    def __init__(self, result_json: Path | None):
        self.result_json = result_json
        self.lock = threading.Lock()
        self.data = {}

    def update(self, payload: dict) -> None:
        with self.lock:
            self.data = dict(payload)
            if self.result_json:
                self.result_json.parent.mkdir(parents=True, exist_ok=True)
                self.result_json.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_template(template_path: Path) -> str:
    return template_path.read_text(encoding="utf-8")


def render_page(template: str, *, title: str, description: str, action: str, footer: str, accept: str) -> bytes:
    page = template
    page = page.replace("{{TITLE}}", html.escape(title))
    page = page.replace("{{DESCRIPTION}}", html.escape(description))
    page = page.replace("{{ACTION}}", html.escape(action, quote=True))
    page = page.replace("{{FOOTER}}", html.escape(footer))
    page = page.replace("{{ACCEPT}}", html.escape(accept, quote=True))
    return page.encode("utf-8")


def make_handler(config: dict):
    token_path = f"/{config['token']}"
    uploaded = config["uploaded"]
    state = config["state"]
    template = config["template"]
    output_dir = config["output_dir"]
    max_bytes = config["max_bytes"]
    title = config["title"]
    description = config["description"]
    footer = config["footer"]
    accept = config["accept"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "SenseVoiceUpload/1.0"

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write((fmt % args) + "\n")

        def _send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != token_path:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send(200, render_page(template, title=title, description=description, action=token_path, footer=footer, accept=accept))

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != token_path:
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            if uploaded.is_set():
                self._send(409, "这个入口已经用过了。".encode("utf-8"))
                return
            content_length = int(self.headers.get("Content-Length") or "0")
            if max_bytes and content_length and content_length > max_bytes:
                self._send(413, f"文件过大，当前上限 {max_bytes} 字节。".encode("utf-8"))
                return
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")})
            file_item = form["file"] if "file" in form else None
            if file_item is None or not getattr(file_item, "file", None):
                self._send(400, "没有收到文件字段 `file`。".encode("utf-8"))
                return
            original_name = sanitize_filename(getattr(file_item, "filename", "upload.bin"))
            target_path = output_dir / f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{original_name}"
            output_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            with target_path.open("wb") as out:
                while True:
                    chunk = file_item.file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if max_bytes and written > max_bytes:
                        out.close()
                        target_path.unlink(missing_ok=True)
                        self._send(413, f"文件过大，当前上限 {max_bytes} 字节。".encode("utf-8"))
                        return
                    out.write(chunk)
            state.update({
                "status": "uploaded",
                "path": str(target_path),
                "filename": original_name,
                "size": written,
                "content_type": file_item.type or "application/octet-stream",
                "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            uploaded.set()
            self._send(200, f"上传成功：{html.escape(original_name)}（{written} bytes）。这个入口现在会自动关闭。".encode("utf-8"), "text/plain; charset=utf-8")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    return Handler


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="启动一次性音频上传网页；成功上传一次后自动关闭。")
    p.add_argument("--listen", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18793)
    p.add_argument("--public-base", default="")
    p.add_argument("--output-dir", default=os.environ.get("SENSEVOICE_UPLOAD_DIR", "./uploads/sensevoice-local"))
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--max-bytes", type=int, default=0)
    p.add_argument("--token", default="")
    p.add_argument("--title", default=DEFAULT_TITLE)
    p.add_argument("--description", default=DEFAULT_DESCRIPTION)
    p.add_argument("--footer", default=DEFAULT_FOOTER)
    p.add_argument("--accept", default=AUDIO_ACCEPT)
    p.add_argument("--result-json", default="")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or secrets.token_urlsafe(16)
    output_dir = Path(args.output_dir)
    result_json = Path(args.result_json) if args.result_json else None
    template_path = Path(__file__).resolve().parent.parent / "assets" / "upload-form.html"
    state = UploadState(result_json)
    uploaded = threading.Event()
    public_base = (args.public_base or f"http://127.0.0.1:{args.port}").rstrip("/")
    ready = {
        "status": "ready",
        "listen": args.listen,
        "port": args.port,
        "public_base": public_base,
        "token": token,
        "upload_url": f"{public_base}/{token}",
        "output_dir": str(output_dir),
        "timeout_seconds": args.timeout,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    state.update(ready)
    print(json.dumps(ready, ensure_ascii=False), flush=True)
    server = ThreadingHTTPServer((args.listen, args.port), make_handler({
        "token": token,
        "uploaded": uploaded,
        "state": state,
        "template": load_template(template_path),
        "output_dir": output_dir,
        "max_bytes": args.max_bytes,
        "title": args.title,
        "description": args.description,
        "footer": args.footer,
        "accept": args.accept,
    }))

    def timeout_shutdown() -> None:
        if not uploaded.is_set():
            state.update({
                "status": "timeout",
                "listen": args.listen,
                "port": args.port,
                "public_base": public_base,
                "token": token,
                "upload_url": f"{public_base}/{token}",
                "output_dir": str(output_dir),
                "timeout_seconds": args.timeout,
                "timed_out_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            try:
                server.shutdown()
            except Exception:
                pass

    timer = threading.Timer(args.timeout, timeout_shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        timer.cancel()
        server.server_close()
        print(json.dumps(state.data, ensure_ascii=False), flush=True)
    return 0 if uploaded.is_set() else 2


if __name__ == "__main__":
    raise SystemExit(main())
