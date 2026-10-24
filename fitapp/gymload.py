"""Gym load per body part: hard sets from the gym log, and coming back after a break.

Garmin's training load is heart-rate based, so a heavy squat session barely
registers. Counting hard sets per body part from the gym log fills that gap.
A set is hard when it's at least ``hard_set_fraction`` of the heaviest weight
you used for that lift that day (so warm-ups don't count); bodyweight sets
always count.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .gymlog import Session
from .util import has_keyword

# Shown in this order on the dashboard, top of the body down.
ORDER = ["chest", "shoulder", "tricep", "back", "bicep", "core", "quad", "glute", "hamstring",
         "lower back", "calf"]


def body_parts(name: str, cfg: dict) -> list[str]:
    text = name.replace("-", " ")
    for keywords, parts in cfg.get("lift_body_parts") or []:
        if has_keyword(text, keywords):
            return list(parts)
    return []


def hard_sets(sets: list[dict], fraction: float) -> int:
    top = max((s["w"] for s in sets if s["w"]), default=None)
    return sum(1 for s in sets if s["r"] >= 1 and (not s["w"] or not top or s["w"] >= fraction * top))


def daily_sets(sessions: list[Session], cfg: dict) -> dict[str, dict[date, int]]:
    """{body part: {day: hard sets}}."""
    fraction = float(cfg.get("hard_set_fraction", 0.7))
    out: dict[str, dict[date, int]] = {}
    for s in sessions:
        for e in s.exercises:
            n = hard_sets(e.sets, fraction)
            if not n:
                continue
            for part in body_parts(e.name, cfg):
                out.setdefault(part, {})
                out[part][s.date] = out[part].get(s.date, 0) + n
    return out


def window(days: dict[date, int], end: date, length: int) -> int:
    return sum(n for day, n in days.items() if end - timedelta(days=length - 1) <= day <= end)


def volume(sets: dict[str, dict[date, int]], day: date) -> list[dict[str, Any]]:
    """This week's hard sets against the 4-week weekly average, per body part."""
    rows = []
    for part, days in sets.items():
        acute = window(days, day, 7)
        chronic = window(days, day, 28) / 4
        rows.append({"part": part, "acute": acute, "chronic": round(chronic, 1),
                     "ratio": round(acute / chronic, 2) if chronic else None})
    return rows


def returns(sets: dict[str, dict[date, int]], day: date, break_days: int, lookback: int = 7) -> list[dict]:
    """Sessions in the last ``lookback`` days that came after a gap of ``break_days`` or more."""
    out = []
    for part, days in sets.items():
        trained = sorted(x for x in days if x <= day)
        for prev, cur in zip(trained, trained[1:]):
            gap = (cur - prev).days
            if gap >= break_days and (day - cur).days < lookback:
                out.append({"part": part, "date": cur.isoformat(), "gap": gap, "last": prev.isoformat()})
    return sorted(out, key=lambda r: (r["date"], ORDER.index(r["part"]) if r["part"] in ORDER else 99))


def weekly_table(sets: dict[str, dict[date, int]], today: date, weeks: int = 8) -> dict[str, Any]:
    ends = [today - timedelta(days=7 * w) for w in range(weeks - 1, -1, -1)]
    rows = []
    for part in sorted(sets, key=lambda p: ORDER.index(p) if p in ORDER else 99):
        days = sets[part]
        counts = [window(days, end, 7) for end in ends]
        if not any(counts):
            continue
        last = max((x for x in days if x <= today), default=None)
        rows.append({"part": part, "sets": counts, "last": last.isoformat() if last else None})
    return {"week_ends": [e.isoformat() for e in ends], "rows": rows}
