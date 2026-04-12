#!/usr/bin/env python3
"""Recheck a previously chosen plan and decide whether to notify.

This script is intentionally small: it recomputes a plan's ETA via mcporter,
compares recommended latest-departure time with previous, and prints a JSON decision.

State file format is agent-owned (e.g., workspace/memory/route-watch-*.json).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


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
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return json.loads(res.stdout)


def duration_from_bicycling(payload: dict) -> int:
    paths = payload.get("paths") or []
    if not paths:
        return 0
    return int(paths[0].get("duration") or 0)


def duration_from_transit(payload: dict) -> int:
    transits = payload.get("transits") or []
    if not transits:
        return 0
    return min(int(t.get("duration") or 0) for t in transits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="path to state json")
    ap.add_argument("--arrive-by", required=True, help="YYYY-MM-DD HH:MM")
    ap.add_argument("--tz", default="Asia/Shanghai")
    ap.add_argument("--origin", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--city", default="宁波")
    ap.add_argument("--cityd", default="宁波")
    ap.add_argument("--plan", required=True, help="fastest | bike_direct | habit:<stationName>")
    ap.add_argument("--station-lnglat", help="lng,lat (required for habit plan)")
    ap.add_argument("--inside-venue-min", type=int, default=12)
    ap.add_argument("--friction-min", type=int, default=8)
    ap.add_argument("--threshold-min", type=int, default=5)
    args = ap.parse_args()

    tz = ZoneInfo(args.tz) if ZoneInfo else None
    arrive_by = datetime.strptime(args.arrive_by, "%Y-%m-%d %H:%M")
    if tz:
        arrive_by = arrive_by.replace(tzinfo=tz)

    inside = max(0, args.inside_venue_min) * 60
    friction = max(0, args.friction_min) * 60

    if args.plan == "fastest":
        payload = mcporter_call(
            "amap.maps_direction_transit_integrated",
            origin=args.origin,
            destination=args.dest,
            city=args.city,
            cityd=args.cityd,
        )
        base = duration_from_transit(payload)
    elif args.plan == "bike_direct":
        payload = mcporter_call(
            "amap.maps_direction_bicycling", origin=args.origin, destination=args.dest
        )
        base = duration_from_bicycling(payload)
        friction = int(friction * 0.6)
    else:
        # habit plan
        if not args.station_lnglat:
            raise SystemExit("--station-lnglat required for habit plan")
        bike = mcporter_call(
            "amap.maps_direction_bicycling",
            origin=args.origin,
            destination=args.station_lnglat,
        )
        transit = mcporter_call(
            "amap.maps_direction_transit_integrated",
            origin=args.station_lnglat,
            destination=args.dest,
            city=args.city,
            cityd=args.cityd,
        )
        base = duration_from_bicycling(bike) + duration_from_transit(transit)

    total = base + inside + friction
    latest_depart = arrive_by - timedelta(seconds=total)

    # read prior
    with open(args.state, "r", encoding="utf-8") as f:
        state = json.load(f)
    prev = state.get("last", {})
    prev_depart = prev.get("recommendedDepartLocal")

    shift_min = None
    if prev_depart and tz:
        prev_dt = datetime.strptime(prev_depart, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        shift_min = round((latest_depart - prev_dt).total_seconds() / 60)

    should_notify = False
    if shift_min is None:
        should_notify = True
    else:
        should_notify = abs(shift_min) >= args.threshold_min

    decision = {
        "plan": args.plan,
        "baseMinutes": round(base / 60, 1),
        "totalMinutes": round(total / 60, 1),
        "latestDepartLocal": latest_depart.strftime("%Y-%m-%d %H:%M") if tz else None,
        "shiftMinutes": shift_min,
        "shouldNotify": should_notify,
    }

    # update state
    state.setdefault("last", {})
    state["last"]["baseTransitSeconds"] = int(base)
    state["last"]["recommendedDepartLocal"] = decision["latestDepartLocal"]
    state["last"]["checkedAt"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M") if tz else None

    with open(args.state, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
