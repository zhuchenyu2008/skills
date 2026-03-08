#!/usr/bin/env python3
"""Install/remove a root crontab entry for btc-position-watch.

This manages a single cron block identified by an ID.

Examples:
  sudo python3 manage_cron_watch.py install \
    --id btc1 --every-min 5 --to alerts@example.com \
    --symbol BTC-USD --qty -0.0042 --entry 67840 --tag "btc-short"

  sudo python3 manage_cron_watch.py remove --id btc1

Implementation notes:
- Uses `crontab -l` / `crontab -`.
- Adds BEGIN/END markers so removal is deterministic.
- Uses flock to prevent overlap.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
MAILER = SKILL_DIR / "scripts" / "position_mailer.py"


def _run(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=False)


def read_crontab() -> str:
    p = _run(["crontab", "-l"])  # exit=1 when empty
    if p.returncode != 0:
        return ""
    return p.stdout


def write_crontab(text: str) -> None:
    p = _run(["crontab", "-"], input_text=text)
    if p.returncode != 0:
        raise SystemExit(f"Failed to write crontab: {p.stderr.strip()}")


def block_markers(id_: str) -> tuple[str, str]:
    b = f"# BEGIN BTC_POSITION_WATCH {id_}"
    e = f"# END BTC_POSITION_WATCH {id_}"
    return b, e


def remove_block(text: str, id_: str) -> tuple[str, bool]:
    begin, end = block_markers(id_)
    lines = text.splitlines()
    out = []
    in_block = False
    removed = False
    for ln in lines:
        if ln.strip() == begin:
            in_block = True
            removed = True
            continue
        if in_block and ln.strip() == end:
            in_block = False
            continue
        if not in_block:
            out.append(ln)
    return "\n".join(out).rstrip() + ("\n" if out else ""), removed


def make_block(id_: str, every_min: int, to: str, symbol: str, qty: str, entry: str, tag: str, note: str) -> str:
    begin, end = block_markers(id_)

    # cron: */N * * * *
    if every_min <= 0 or every_min > 60:
        raise SystemExit("--every-min must be 1..60")

    cron_spec = f"*/{every_min} * * * *"
    lock = f"/tmp/btc_position_watch_{id_}.lock"

    cmd = [
        "/usr/bin/flock",
        "-n",
        lock,
        sys.executable,
        str(MAILER),
        "--to",
        to,
        "--symbol",
        symbol,
        "--qty",
        qty,
        "--entry",
        entry,
    ]
    if tag:
        cmd += ["--tag", tag]
    if note:
        cmd += ["--note", note]

    workspace_dir = Path(os.environ.get("OPENCLAW_WORKSPACE", "/opt/openclaw/workspace"))
    log_dir = workspace_dir / "watchers" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cron_line = f"{cron_spec} {shlex.join(cmd)} >> {shlex.quote(str(log_dir / f'btc_position_watch_{id_}.log'))} 2>&1"

    return "\n".join([begin, cron_line, end]) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_i = sub.add_parser("install")
    ap_i.add_argument("--id", required=True)
    ap_i.add_argument("--every-min", type=int, default=5)
    ap_i.add_argument("--to", required=True)
    ap_i.add_argument("--symbol", default="BTC-USD")
    ap_i.add_argument("--qty", required=True)
    ap_i.add_argument("--entry", required=True)
    ap_i.add_argument("--tag", default="")
    ap_i.add_argument("--note", default="")

    ap_r = sub.add_parser("remove")
    ap_r.add_argument("--id", required=True)

    args = ap.parse_args()

    txt = read_crontab()
    txt2, _ = remove_block(txt, args.id)

    if args.cmd == "remove":
        write_crontab(txt2)
        return 0

    block = make_block(
        id_=args.id,
        every_min=args.every_min,
        to=args.to,
        symbol=args.symbol,
        qty=args.qty,
        entry=args.entry,
        tag=args.tag,
        note=args.note,
    )
    new_txt = (txt2.rstrip() + "\n\n" + block).lstrip() if txt2.strip() else block
    write_crontab(new_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
