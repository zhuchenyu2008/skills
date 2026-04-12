#!/usr/bin/env python3
"""Compute whether to notify for a route-watch cadence.

This script is designed to be run by an *isolated cron agentTurn* which will:
1) run this script
2) parse the JSON output
3) if notify: send Telegram via OpenClaw `message` tool
4) if email: send email via send_commute_email.py

It updates the route-watch state indirectly via recheck_trip.py and returns a
stable email dedupe key so the caller can mark successful sends in the state.

Output JSON schema:
{
  "shouldNotify": bool,
  "shouldEmail": bool,
  "telegramText": str,
  "email": {"to": str, "subject": str, "title": str, "subtitle": str, "recommend": str} | null,
  "emailDedupeKey": str | null,
  "duplicateEmailSuppressed": bool,
  "decision": { ... from recheck_trip.py ... }
}
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return res.stdout


def build_email_dedupe_key(
    *,
    kind: str,
    arrive_by: str,
    latest: str | None,
    total_min: float | int | None,
    plan: str,
    recipient_email: str,
) -> str:
    if kind == "depart_now":
        # Final departure reminder should be sent at most once per trip/route even if
        # a retry sees tiny ETA fluctuations after the user is already due to leave.
        return "|".join([kind, arrive_by, plan, recipient_email])
    total_str = "" if total_min is None else str(total_min)
    latest_str = latest or ""
    return "|".join([kind, arrive_by, latest_str, total_str, plan, recipient_email])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--recipient-email", default="zhuchenyu2008@foxmail.com")
    ap.add_argument("--force-email", action="store_true", help="send email even if shouldNotify is false")
    args = ap.parse_args()

    state_path = args.state
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    event = state.get("event") or {}
    policy = state.get("policy") or {}
    if "notifications" not in state:
        state["notifications"] = {}
    notifications = state["notifications"]
    tz_name = event.get("timezone") or "Asia/Shanghai"
    tz = ZoneInfo(tz_name) if ZoneInfo else None

    arrive_by = event.get("arriveByLocal")
    origin = event.get("origin")
    dest = event.get("destination")
    city = event.get("city") or "宁波"
    cityd = event.get("cityd") or "宁波"

    # Buffers (minutes)
    buf = policy.get("buffer") or {}
    inside = (buf.get("insideVenueMinutes") if buf.get("insideVenueMinutes") is not None else 12)
    friction = (buf.get("waitAndFrictionMinutes") if buf.get("waitAndFrictionMinutes") is not None else 8)
    threshold = (policy.get("notifyThresholdMinutes") or 5)

    if not arrive_by or not origin or not dest:
        raise SystemExit("state missing event.arriveByLocal/origin/destination")

    # Ensure chosen plan exists: default lock 'fastest' per user rule.
    chosen = state.get("chosen") or {}
    plan = chosen.get("plan") or "fastest"
    station_lnglat = chosen.get("stationLngLat")

    # If user had chosen habit but station missing, fallback to fastest.
    if plan.startswith("habit") and not station_lnglat:
        plan = "fastest"

    # Run recheck_trip.py
    recheck_py = __file__.replace("cron_route_watch_decide.py", "recheck_trip.py")
    cmd = [
        "python3",
        recheck_py,
        "--state",
        state_path,
        "--arrive-by",
        arrive_by,
        "--tz",
        tz_name,
        "--origin",
        origin,
        "--dest",
        dest,
        "--city",
        city,
        "--cityd",
        cityd,
        "--plan",
        plan,
        "--inside-venue-min",
        str(int(inside)),
        "--friction-min",
        str(int(friction)),
        "--threshold-min",
        str(int(threshold)),
    ]
    if plan.startswith("habit"):
        cmd += ["--station-lnglat", station_lnglat]

    decision = json.loads(run(cmd))

    # Compose text
    name = (event.get("name") or "目的地").strip()
    latest = decision.get("latestDepartLocal")
    total_min = decision.get("totalMinutes")
    shift = decision.get("shiftMinutes")

    if shift is None:
        shift_str = "（首次计算）"
    elif shift > 0:
        shift_str = f"（比上次可晚 {shift} 分钟）"
    elif shift < 0:
        shift_str = f"（比上次需提前 {abs(shift)} 分钟）"
    else:
        shift_str = "（与上次一致）"

    plan_str = plan
    if plan == "fastest":
        plan_str = "最快（公交/地铁）"
    elif plan == "bike_direct":
        plan_str = "直骑小遛"
    elif plan.startswith("habit"):
        plan_str = f"骑小遛→地铁（{plan.split(':', 1)[1]}上）"

    telegram = (
        f"【路程复算】家→{name}\n"
        f"本次依据路线：{plan_str}\n"
        f"预计总耗时：{total_min} 分钟（含进商场/到店缓冲）\n"
        f"建议最迟出发：{latest} {shift_str}"
    )

    should_notify = bool(decision.get("shouldNotify"))

    # Email policy (user preference):
    # - Email is for "出门提醒" (depart-now) and also for material changes (shouldNotify).
    # - Route/weather are included but must be clearly secondary.
    def weather_summary(city_name: str) -> str | None:
        try:
            wx = json.loads(run(["mcporter", "call", "amap.maps_weather", f"city={city_name}", "--output", "json"]))
            forecasts = (wx.get("forecasts") or [])
            if not forecasts:
                return None
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

    # Determine if it's already time to leave
    depart_now = False
    try:
        if tz and latest:
            latest_dt = datetime.strptime(latest, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
            now_dt = datetime.now(tz)
            depart_now = now_dt >= latest_dt
    except Exception:
        depart_now = False

    should_email = bool(args.force_email or should_notify or depart_now)
    email_kind = "depart_now" if depart_now else "update"
    email_dedupe_key = None
    duplicate_email_suppressed = False

    email = None
    if should_email:
        email_dedupe_key = build_email_dedupe_key(
            kind=email_kind,
            arrive_by=arrive_by,
            latest=latest,
            total_min=total_min,
            plan=plan,
            recipient_email=args.recipient_email,
        )
        if notifications.get("lastEmailKey") == email_dedupe_key:
            should_email = False
            duplicate_email_suppressed = True
        else:
            if depart_now:
                subject = f"出门提醒：请立即出发｜{arrive_by} 要到｜约 {total_min} 分钟（最迟 {latest}）"
                title = "出门提醒：请立即出发"
            else:
                subject = f"出门提醒更新：{arrive_by} 要到｜约 {total_min} 分钟｜最迟 {latest} 出发{shift_str}"
                title = f"出门提醒：最迟 {latest} 出发"

            origin_name = (event.get("originName") or "出发地").strip()
            subtitle = f"{arrive_by} 到｜{origin_name} → {name}"
            if depart_now:
                recommend = (
                    f"请立即出发\n"
                    f"最迟 {latest}\n"
                    f"到达时间：{arrive_by}\n"
                    f"路程约 {total_min} 分钟"
                )
            else:
                recommend = (
                    f"出门提醒\n"
                    f"最迟 {latest} 出发\n"
                    f"到达时间：{arrive_by}\n"
                    f"路程约 {total_min} 分钟"
                )

            details_path = state_path + ".email-details.json"
            details = {
                "weather": weather_summary(city),
                "chosen": {"title": plan_str, "key": plan, "breakdownText": ""},
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

            # Actually send the email
            try:
                send_email_py = __file__.replace("cron_route_watch_decide.py", "send_commute_email.py")
                email_cmd = [
                    "python3", send_email_py,
                    "--to", args.recipient_email,
                    "--subject", subject,
                    "--title", title,
                    "--subtitle", subtitle,
                    "--recommend", recommend,
                ]
                if details_path:
                    email_cmd += ["--details-json", details_path]
                subprocess.run(email_cmd, capture_output=True, text=True, check=True)
                # Record dedupe key to state so next run won't send duplicate
                notifications["lastEmailKey"] = email_dedupe_key
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
            except Exception as e:
                # If email fails, mark email as None so caller knows
                email = None

    # pushTelegram: true only when there is something urgent to tell the user
    push_telegram = bool(should_notify or depart_now)

    out = {
        "shouldNotify": should_notify,
        "shouldEmail": should_email,
        "pushTelegram": push_telegram,
        "telegramText": telegram,
        "email": email,
        "emailDedupeKey": email_dedupe_key,
        "emailKind": email_kind if email_dedupe_key else None,
        "duplicateEmailSuppressed": duplicate_email_suppressed,
        "decision": decision,
    }

    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
