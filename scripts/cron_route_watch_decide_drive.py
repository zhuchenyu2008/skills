#!/usr/bin/env python3
"""Route-watch decision for *driving* (AMap driving ETA).

Mirrors cron_route_watch_decide.py output contract so the isolated cron agentTurn
can:
- send Telegram when shouldNotify
- send email when shouldEmail

State file format: same top-level keys as other route-watch states.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return res.stdout


def mcporter_call(selector: str, **kwargs):
    cmd = ["mcporter", "call", selector]
    for k, v in kwargs.items():
        if v is None:
            continue
        if isinstance(v, bool):
            vv = "true" if v else "false"
        else:
            vv = str(v)
        cmd.append(f"{k}={vv}")
    cmd += ["--output", "json"]
    return json.loads(run(cmd))


def duration_from_driving(payload: dict) -> int:
    paths = payload.get("paths") or []
    if not paths:
        return 0
    return int(paths[0].get("duration") or 0)


def weather_summary(city_name: str) -> str | None:
    try:
        wx = mcporter_call("amap.maps_weather", city=city_name, extensions="all")
        forecasts = (wx.get("forecasts") or [])
        if not forecasts:
            return None
        # Use the first forecast entry (today) as fallback; if state includes arrive date,
        # we still keep summary lightweight.
        f0 = forecasts[0]
        dayw = f0.get("dayweather")
        nightw = f0.get("nightweather")
        dayt = f0.get("daytemp")
        nightt = f0.get("nighttemp")
        daywind = f0.get("daywind")
        daypower = f0.get("daypower")
        w = dayw if dayw == nightw else f"{dayw}/{nightw}"
        t = f"{nightt}~{dayt}℃" if (nightt is not None and dayt is not None) else ""
        wind = "".join([str(x) for x in [daywind, daypower] if x])
        parts = [p for p in [w, t, wind] if p]
        return " ".join(parts) if parts else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--recipient-email", default="zhuchenyu2008@foxmail.com")
    ap.add_argument("--force-email", action="store_true")
    args = ap.parse_args()

    with open(args.state, "r", encoding="utf-8") as f:
        state = json.load(f)

    event = state.get("event") or {}
    policy = state.get("policy") or {}
    tz_name = event.get("timezone") or "Asia/Shanghai"
    tz = ZoneInfo(tz_name) if ZoneInfo else None

    arrive_by = (event.get("arriveByLocal") or "").strip()
    origin = event.get("origin")
    dest = event.get("destination")
    city = event.get("city") or "宁波"

    if not arrive_by or not origin or not dest:
        raise SystemExit("state missing event.arriveByLocal/origin/destination")

    buf = policy.get("buffer") or {}
    inside_min = int(buf.get("insideVenueMinutes") if buf.get("insideVenueMinutes") is not None else 8)
    friction_min = int(buf.get("waitAndFrictionMinutes") if buf.get("waitAndFrictionMinutes") is not None else 7)
    threshold_min = int(policy.get("notifyThresholdMinutes") or 5)

    arrive_dt = datetime.strptime(arrive_by, "%Y-%m-%d %H:%M")
    if tz:
        arrive_dt = arrive_dt.replace(tzinfo=tz)

    # Recompute driving ETA
    driving = mcporter_call("amap.maps_direction_driving", origin=origin, destination=dest)
    base_sec = duration_from_driving(driving)

    inside_sec = max(0, inside_min) * 60
    friction_sec = max(0, friction_min) * 60
    total_sec = base_sec + inside_sec + friction_sec
    latest_depart = arrive_dt - timedelta(seconds=total_sec)

    latest_str = latest_depart.strftime("%Y-%m-%d %H:%M") if tz else None

    # Compare to previous
    prev_depart = ((state.get("last") or {}).get("recommendedDepartLocal"))
    shift_min = None
    if prev_depart and tz and latest_str:
        prev_dt = datetime.strptime(prev_depart, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        shift_min = round((latest_depart - prev_dt).total_seconds() / 60)

    should_notify = True if shift_min is None else (abs(shift_min) >= threshold_min)

    # Update state
    state.setdefault("last", {})
    state["last"]["baseTransitSeconds"] = int(base_sec)
    state["last"]["recommendedDepartLocal"] = latest_str
    state["last"]["checkedAt"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M") if tz else None
    with open(args.state, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    name = (event.get("name") or "目的地").strip()
    origin_name = (event.get("originName") or "出发地").strip()

    shift_str = ""
    if shift_min is None:
        shift_str = "（首次计算）"
    else:
        if shift_min > 0:
            shift_str = f"（比上次可晚 {shift_min} 分钟）"
        elif shift_min < 0:
            shift_str = f"（比上次需提前 {abs(shift_min)} 分钟）"
        else:
            shift_str = "（与上次一致）"

    total_min = round(total_sec / 60, 1)

    telegram = (
        f"【路程复算】家→{name}（驾车）\n"
        f"本次依据路线：驾车（高德）\n"
        f"预计总耗时：{total_min} 分钟（含停车/走进校内缓冲）\n"
        f"建议最迟出发：{latest_str} {shift_str}"
    )

    # depart-now 판단
    depart_now = False
    try:
        if tz and latest_str:
            now_dt = datetime.now(tz)
            depart_now = now_dt >= latest_depart
    except Exception:
        depart_now = False

    should_email = bool(args.force_email or should_notify or depart_now)

    email = None
    if should_email:
        if depart_now:
            subject = f"出门提醒：请立即出发｜{arrive_by} 要到｜约 {total_min} 分钟（最迟 {latest_str}）"
            title = "出门提醒：请立即出发"
        else:
            subject = f"出门提醒更新：{arrive_by} 要到｜约 {total_min} 分钟｜最迟 {latest_str} 出发{shift_str}"
            title = f"出门提醒：最迟 {latest_str} 出发"

        subtitle = f"{arrive_by} 到｜{origin_name} → {name}"
        if depart_now:
            recommend = (
                f"请立即出发\n"
                f"最迟 {latest_str}\n"
                f"到达时间：{arrive_by}\n"
                f"路程约 {total_min} 分钟"
            )
        else:
            recommend = (
                f"出门提醒\n"
                f"最迟 {latest_str} 出发\n"
                f"到达时间：{arrive_by}\n"
                f"路程约 {total_min} 分钟"
            )

        details_path = args.state + ".email-details.json"
        details = {
            "weather": weather_summary(city),
            "chosen": {"title": "驾车（高德）", "key": "drive", "breakdownText": ""},
            "options": [],
            "links": [],
        }
        try:
            with open(details_path, "w", encoding="utf-8") as f:
                json.dump(details, f, ensure_ascii=False, indent=2)
        except Exception:
            details_path = None

        email = {
            "to": args.recipient_email,
            "subject": subject,
            "title": title,
            "subtitle": subtitle,
            "recommend": recommend,
            "detailsJsonPath": details_path,
        }

    out = {
        "shouldNotify": bool(should_notify),
        "shouldEmail": bool(should_email),
        "telegramText": telegram,
        "email": email,
        "decision": {
            "plan": "drive",
            "baseMinutes": round(base_sec / 60, 1),
            "totalMinutes": total_min,
            "latestDepartLocal": latest_str,
            "shiftMinutes": shift_min,
            "shouldNotify": bool(should_notify),
        },
    }

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
