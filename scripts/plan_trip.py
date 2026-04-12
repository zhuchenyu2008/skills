#!/usr/bin/env python3
"""Plan Ningbo commute options using AMap MCP via mcporter.

Outputs JSON with a recommended (fastest) option, and optionally all options.

Usage example:
  plan_trip.py --arrive-by "2026-02-18 11:00" --tz Asia/Shanghai \
    --origin 121.5230315924,29.8652491273 \
    --dest 121.590364,29.880799 \
    --city 宁波 --cityd 宁波 \
    --stations '[["柳西", "121.531320,29.871117"],["丽园南路","121.517716,29.858133"],["云霞路","121.526364,29.858542"]]' \
    --inside-venue-min 12 --friction-min 8

Note: AMap MCP transit tools do not accept departure time; treat durations as current/default.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def mcporter_call(selector: str, **kwargs):
    # Use --output json for stable parsing
    cmd = ["mcporter", "call", selector]
    for k, v in kwargs.items():
        if v is None:
            continue
        # key=value style
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


def parse_lnglat(s: str):
    lng, lat = s.split(",")
    return float(lng), float(lat)


def duration_from_bicycling(payload: dict) -> int:
    # payload: {paths:[{duration:seconds}]}
    paths = payload.get("paths") or []
    if not paths:
        return 0
    return int(paths[0].get("duration") or 0)


def duration_from_transit(payload: dict) -> int:
    transits = payload.get("transits") or []
    if not transits:
        return 0
    # choose shortest duration
    return min(int(t.get("duration") or 0) for t in transits)


@dataclass
class Option:
    key: str
    title: str
    base_seconds: int
    buffer_seconds: int
    total_seconds: int
    breakdown: list


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrive-by", required=True, help="YYYY-MM-DD HH:MM")
    ap.add_argument("--tz", default="Asia/Shanghai")
    ap.add_argument("--origin", required=True, help="lng,lat")
    ap.add_argument("--dest", required=True, help="lng,lat")
    ap.add_argument("--city", default="宁波")
    ap.add_argument("--cityd", default="宁波")
    ap.add_argument("--stations", required=True, help="JSON list of [name, lnglat]")
    ap.add_argument("--inside-venue-min", type=int, default=12)
    ap.add_argument("--friction-min", type=int, default=8)
    ap.add_argument(
        "--output-mode",
        default="recommended",
        choices=["recommended", "full"],
        help="recommended: print only the fastest option summary; full: include all options",
    )
    args = ap.parse_args()

    tz = ZoneInfo(args.tz) if ZoneInfo else None
    arrive_by = datetime.strptime(args.arrive_by, "%Y-%m-%d %H:%M")
    if tz:
        arrive_by = arrive_by.replace(tzinfo=tz)

    inside = max(0, args.inside_venue_min) * 60
    friction = max(0, args.friction_min) * 60

    stations = json.loads(args.stations)

    options: list[Option] = []

    # 1) Fastest: direct transit origin->dest
    direct_transit = mcporter_call(
        "amap.maps_direction_transit_integrated",
        origin=args.origin,
        destination=args.dest,
        city=args.city,
        cityd=args.cityd,
    )
    tsec = duration_from_transit(direct_transit)
    if tsec:
        options.append(
            Option(
                key="fastest",
                title="Fastest (direct public transit per AMap)",
                base_seconds=tsec,
                buffer_seconds=inside + friction,
                total_seconds=tsec + inside + friction,
                breakdown=[
                    {"mode": "transit", "from": "origin", "to": "dest", "seconds": tsec},
                    {"mode": "buffer", "kind": "friction", "seconds": friction},
                    {"mode": "buffer", "kind": "insideVenue", "seconds": inside},
                ],
            )
        )

    # 2) Habit: bike to one of stations + transit station->dest
    best_habit: Option | None = None
    for name, lnglat in stations:
        bike = mcporter_call(
            "amap.maps_direction_bicycling", origin=args.origin, destination=lnglat
        )
        bike_sec = duration_from_bicycling(bike)
        transit = mcporter_call(
            "amap.maps_direction_transit_integrated",
            origin=lnglat,
            destination=args.dest,
            city=args.city,
            cityd=args.cityd,
        )
        transit_sec = duration_from_transit(transit)
        base = bike_sec + transit_sec
        total = base + inside + friction
        opt = Option(
            key=f"habit:{name}",
            title=f"Habit (shared e-bike -> metro via {name})",
            base_seconds=base,
            buffer_seconds=inside + friction,
            total_seconds=total,
            breakdown=[
                {"mode": "bike", "from": "origin", "to": name, "seconds": bike_sec},
                {"mode": "transit", "from": name, "to": "dest", "seconds": transit_sec},
                {"mode": "buffer", "kind": "friction", "seconds": friction},
                {"mode": "buffer", "kind": "insideVenue", "seconds": inside},
            ],
        )
        if not best_habit or opt.total_seconds < best_habit.total_seconds:
            best_habit = opt

    if best_habit:
        options.append(best_habit)

    # 3) Direct bike
    bike_direct = mcporter_call(
        "amap.maps_direction_bicycling", origin=args.origin, destination=args.dest
    )
    bike_direct_sec = duration_from_bicycling(bike_direct)
    if bike_direct_sec:
        # still add insideVenue; friction smaller for bike
        bike_friction = max(0, int(friction * 0.6))
        options.append(
            Option(
                key="bike_direct",
                title="Direct shared e-bike / bicycling",
                base_seconds=bike_direct_sec,
                buffer_seconds=inside + bike_friction,
                total_seconds=bike_direct_sec + inside + bike_friction,
                breakdown=[
                    {"mode": "bike", "from": "origin", "to": "dest", "seconds": bike_direct_sec},
                    {"mode": "buffer", "kind": "friction", "seconds": bike_friction},
                    {"mode": "buffer", "kind": "insideVenue", "seconds": inside},
                ],
            )
        )

    options.sort(key=lambda o: o.total_seconds)

    latest_depart = arrive_by - timedelta(seconds=options[0].total_seconds) if options else arrive_by
    fastest = options[0] if options else None

    payload = {
        "arriveBy": args.arrive_by,
        "timezone": args.tz,
        "origin": args.origin,
        "destination": args.dest,
        "buffers": {
            "insideVenueMinutes": args.inside_venue_min,
            "frictionMinutes": args.friction_min,
        },
        "recommended": {
            "key": fastest.key if fastest else None,
            "title": fastest.title if fastest else None,
            "baseMinutes": round(fastest.base_seconds / 60, 1) if fastest else None,
            "bufferMinutes": round(fastest.buffer_seconds / 60, 1) if fastest else None,
            "totalMinutes": round(fastest.total_seconds / 60, 1) if fastest else None,
            "latestDepartLocal": latest_depart.strftime("%Y-%m-%d %H:%M") if tz else None,
        },
    }

    if args.output_mode == "full":
        payload["options"] = [
            {
                "key": o.key,
                "title": o.title,
                "baseMinutes": round(o.base_seconds / 60, 1),
                "bufferMinutes": round(o.buffer_seconds / 60, 1),
                "totalMinutes": round(o.total_seconds / 60, 1),
                "breakdown": o.breakdown,
            }
            for o in options
        ]

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
