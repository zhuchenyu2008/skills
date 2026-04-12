#!/usr/bin/env python3
"""Schedule route-watch cron jobs (isolated agentTurn) for a given state file.

This is the *correct* way to schedule commute rechecks:
- use cron sessionTarget=isolated + payload.kind=agentTurn
- the agentTurn runs cron_route_watch_decide.py and then uses OpenClaw tools to notify

Note: This script only prints the cron job objects. The caller (agent) should
pass them to `cron add` tool.

Why print-only? So the assistant can review/patch before actually creating jobs.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


DECIDE_PY = "/root/.openclaw/workspace/skills/amap-commute-planner/scripts/cron_route_watch_decide.py"
SEND_EMAIL_PY = "/root/.openclaw/workspace/skills/amap-commute-planner/scripts/send_commute_email.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--tz", default="Asia/Shanghai")
    ap.add_argument("--target-telegram", required=True, help="telegram chat/user id")
    ap.add_argument("--arrive-by", required=True, help="YYYY-MM-DD HH:MM local")
    args = ap.parse_args()

    tz = ZoneInfo(args.tz) if ZoneInfo else None
    arrive = datetime.strptime(args.arrive_by, "%Y-%m-%d %H:%M")
    if tz:
        arrive = arrive.replace(tzinfo=tz)

    # Determine anchor depart time (T)
    anchor = None
    try:
        with open(args.state, "r", encoding="utf-8") as f:
            st = json.load(f)
        t_str = ((st.get("last") or {}).get("recommendedDepartLocal"))
        if t_str:
            anchor = datetime.strptime(t_str, "%Y-%m-%d %H:%M")
            if tz:
                anchor = anchor.replace(tzinfo=tz)
    except Exception:
        anchor = None

    if anchor is None:
        anchor = arrive + timedelta(minutes=-60)

    # Cadence: relative to *recommended depart time* (T): T-30, -20, -15, -10, -5, 0.
    offsets_min = [-30, -20, -15, -10, -5, 0]

    jobs = []
    for m in offsets_min:
        at = anchor + timedelta(minutes=m)
        at_ms = int(at.timestamp() * 1000)
        jobs.append(
            {
                "name": f"route-watch {args.state} {m}m",
                "schedule": {"kind": "at", "atMs": at_ms},
                "sessionTarget": "isolated",
                "enabled": True,
                "payload": {
                    "kind": "agentTurn",
                    "timeoutSeconds": 90,
                    "deliver": False,
                    "message": (
                        "你是一个定时出行复算执行器。严格按步骤做：\n"
                        f"1) 运行：python3 {DECIDE_PY} --state '{args.state}'\n"
                        "2) 解析 stdout JSON 为 out。\n"
                        f"3) 若 out.shouldNotify=true：用 message 工具向 telegram 发送 out.telegramText（channel=telegram,target={args.target_telegram}）。\n"
                        f"4) 若 out.shouldEmail=true 且 out.email 非空：用 exec 运行：python3 {SEND_EMAIL_PY} --to <to> --subject <subject> --title <title> --subtitle <subtitle> --recommend <recommend> --details-json <detailsJsonPath>（参数取 out.email；detailsJsonPath 取 out.email.detailsJsonPath）。邮件发送成功后，再用 exec 运行一段 python，把状态文件里的 notifications.lastEmailKey 写成 out.emailDedupeKey，notifications.lastEmailSentAt 写成当前时间。\n"
                        "5) 若 out.duplicateEmailSuppressed=true，则不要再发重复邮件。\n"
                        "6) 最终必须只输出一行短摘要，且绝不能留空：DONE notify+email / DONE notify / DONE email / DONE quiet / DONE duplicate-email-suppressed / FAIL <一句话原因>。不要输出其他解释。"
                    ),
                },
            }
        )

    print(json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
