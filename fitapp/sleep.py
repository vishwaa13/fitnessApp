"""Bedtime consistency: when you fell asleep and woke, from Garmin's sleep record.

Times are kept as minutes after 18:00 on the evening you went to bed, so a
23:30 bedtime (330) and a 00:45 one (405) sit on one scale. A row dated D is
the night that ended on the morning of D, so its bedtime is the evening of D-1.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any

from .util import d

EVENING = 18 * 60


def minutes(iso: str | None) -> int | None:
    """Minutes after 18:00 of the evening the night started."""
    if not iso:
        return None
    t = datetime.fromisoformat(iso)
    return (t.hour * 60 + t.minute - EVENING) % 1440


def clock(m: float | None) -> str | None:
    if m is None:
        return None
    m = int(round(m + EVENING)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def nights(daily: list[dict]) -> list[dict]:
    """[{date (morning), bed_m, wake_m}] for rows with both times, oldest first."""
    out = []
    for r in sorted(daily, key=lambda r: r["date"]):
        bed, wake = minutes(r.get("bed")), minutes(r.get("wake"))
        if bed is not None and wake is not None and wake > bed:
            out.append({"date": r["date"], "bed_m": bed, "wake_m": wake})
    return out


def late_bed_evenings(daily: list[dict], late_by: int = 60) -> set[date]:
    """Evenings you went to bed ``late_by`` minutes or more after your usual time
    (median of the 14 nights before, with at least 5 of them)."""
    rows = nights(daily)
    out = set()
    for i, n in enumerate(rows):
        prev = [r["bed_m"] for r in rows[max(0, i - 14):i]]
        if len(prev) >= 5 and n["bed_m"] >= statistics.median(prev) + late_by:
            out.add(d(n["date"]) - timedelta(days=1))
    return out


def _sd(values: list[float]) -> int | None:
    return round(statistics.pstdev(values)) if len(values) >= 3 else None


def summary(rows: list[dict]) -> dict[str, Any]:
    """Usual bed and wake time and how much they move, for a set of nights."""
    beds = [r["bed_m"] for r in rows]
    wakes = [r["wake_m"] for r in rows]
    return {"n": len(rows),
            "usual_bed": clock(statistics.median(beds)) if beds else None,
            "usual_wake": clock(statistics.median(wakes)) if wakes else None,
            "bed_sd": _sd(beds), "wake_sd": _sd(wakes)}


def schedule(daily: list[dict], today: date, days: int = 28, late_by: int = 60) -> dict[str, Any]:
    """The last ``days`` nights for the Recovery tab."""
    start = (today - timedelta(days=days - 1)).isoformat()
    rows = [r for r in nights(daily) if r["date"] >= start]
    late = late_bed_evenings(daily, late_by)
    weekend = [r["bed_m"] for r in rows if d(r["date"]).weekday() in (5, 6)]   # Friday and Saturday nights
    weekday = [r["bed_m"] for r in rows if d(r["date"]).weekday() not in (5, 6)]
    shift = (round(statistics.median(weekend) - statistics.median(weekday))
             if len(weekend) >= 2 and len(weekday) >= 3 else None)
    return {**summary(rows), "weekend_shift": shift,
            "late_nights": sum(1 for r in rows if d(r["date"]) - timedelta(days=1) in late),
            "late_by": late_by,
            "nights": [{**r, "bed": clock(r["bed_m"]), "wake": clock(r["wake_m"]),
                        "hours": round((r["wake_m"] - r["bed_m"]) / 60, 2),
                        "late": d(r["date"]) - timedelta(days=1) in late} for r in rows]}
