"""Week in review: Monday-to-Sunday weeks, each comparable with the one before."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import sleep
from .util import mean, rnd

LEVEL = {"caution": 1, "high": 2}


def _week(start: date, today: date, days: dict[str, dict], daily: list[dict], activities: list[dict],
          gym_dates: set[str], sets: dict[str, dict[date, int]], alcohol: set[date],
          flags_by_day: dict[str, list[dict]], rest_day_load: float) -> dict[str, Any]:
    end = start + timedelta(days=6)
    last = min(end, today)
    span = [start + timedelta(days=k) for k in range((last - start).days + 1)]
    iso = [x.isoformat() for x in span]
    rows = [r for r in daily if r["date"] in iso]
    acts = [a for a in activities if a["date"] in iso]
    load = {x: 0.0 for x in iso}
    for a in acts:
        load[a["date"]] += a.get("load") or 0
    colours = {"green": 0, "amber": 0, "red": 0}
    for x in iso:
        status = (days.get(x) or {}).get("status")
        if status in colours:
            colours[status] += 1
    # Each kind of warning once: its worst level, the first day it showed, and on how many days.
    flags: dict[str, dict] = {}
    for x in iso:
        for f in flags_by_day.get(x, []):
            seen = flags.get(f["key"])
            if seen is None:
                flags[f["key"]] = {**f, "date": x, "days": 1}
                continue
            seen["days"] += 1
            if LEVEL.get(f["level"], 0) > LEVEL.get(seen["level"], 0):
                seen.update(level=f["level"], text=f["text"])
    return {
        "start": start.isoformat(), "end": end.isoformat(), "days": len(iso), "partial": end > today,
        "load": round(sum(load.values())), "sessions": len(acts),
        "gym_sessions": sum(1 for x in iso if x in gym_dates),
        "rest_days": sum(1 for v in load.values() if v < rest_day_load),
        "colours": colours,
        "hrv": rnd(mean(r.get("hrv") for r in rows), 0),
        "sleep_score": rnd(mean(r.get("sleep_score") for r in rows), 0),
        "sleep_hours": rnd(mean(r.get("sleep_hours") for r in rows), 1),
        "rhr": rnd(mean(r.get("rhr") for r in rows), 0),
        "bedtime": sleep.summary(sleep.nights(rows)),
        "alcohol": sum(1 for x in span if x in alcohol),
        "sets": {part: n for part, by_day in sets.items()
                 if (n := sum(c for day, c in by_day.items() if start <= day <= last))},
        "flags": sorted(flags.values(), key=lambda f: (-LEVEL.get(f["level"], 0), f["date"])),
    }


def build(today: date, days: list[dict], daily: list[dict], activities: list[dict], gym_dates: set[str],
          sets: dict[str, dict[date, int]], alcohol: set[date], flags_by_day: dict[str, list[dict]],
          rest_day_load: float, weeks: int = 8) -> list[dict]:
    """The last ``weeks`` weeks, newest first; the first one may still be in progress."""
    by_date = {x["date"]: x for x in days}
    monday = today - timedelta(days=today.weekday())
    return [_week(monday - timedelta(days=7 * w), today, by_date, daily, activities, gym_dates, sets, alcohol,
                  flags_by_day, rest_day_load) for w in range(weeks)]
