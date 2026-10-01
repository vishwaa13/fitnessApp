"""Injury early-warning: the load patterns that tend to come before a strain.

Checks: acute:chronic workload ratio (7-day load vs 28-day weekly average),
rest days, back-to-back high-load days, Foster's training monotony, and HRV
sitting under baseline. Past injuries from config get the same scan for the
fortnight before them, so you can see whether today looks like then.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from .util import d, rnd

LEVELS = {"ok": 0, "caution": 1, "high": 2}


def daily_load(activities: list[dict], start: date, end: date) -> dict[date, float]:
    loads = {start + timedelta(days=k): 0.0 for k in range((end - start).days + 1)}
    for a in activities:
        day = d(a["date"])
        if start <= day <= end:
            loads[day] += a.get("load") or 0
    return loads


def scan(loads: dict[date, float], hrv_rows: dict[date, dict], day: date, cfg: dict) -> dict[str, Any]:
    """Risk flags as of the end of ``day``."""
    last7 = [loads.get(day - timedelta(days=k), 0.0) for k in range(7)][::-1]
    last14 = [loads.get(day - timedelta(days=k), 0.0) for k in range(14)][::-1]
    last28 = [loads.get(day - timedelta(days=k), 0.0) for k in range(28)]
    acute = sum(last7)
    chronic = sum(last28) / 4
    acwr = acute / chronic if chronic > 0 else None
    rest7 = sum(v < cfg["rest_day_load"] for v in last7)
    rest14 = sum(v < cfg["rest_day_load"] for v in last14)
    high = [v >= cfg["high_day_load"] for v in last7]
    b2b = sum(1 for i in range(1, 7) if high[i] and high[i - 1])
    three_in_row = any(high[i] and high[i - 1] and high[i - 2] for i in range(2, 7))
    sd = statistics.pstdev(last7)
    monotony = (statistics.fmean(last7) / sd) if sd > 0 else None
    low_hrv = 0
    seen = 0
    for k in range(5):
        r = hrv_rows.get(day - timedelta(days=k))
        if r and r.get("hrv") is not None and r.get("hrv_low") is not None:
            seen += 1
            low_hrv += r["hrv"] < r["hrv_low"]

    flags = []
    if acwr is not None and chronic >= 50:
        if acwr >= cfg["acwr_high"]:
            flags.append(("acwr", "high", f"Load spike: last 7 days are {acwr:.2f}× your 4-week average"))
        elif acwr >= cfg["acwr_caution"]:
            flags.append(("acwr", "caution", f"Load climbing: {acwr:.2f}× your 4-week average"))
    if rest7 == 0:
        flags.append(("rest", "high", "No rest day in the last 7 days"))
    elif rest14 <= 1:
        flags.append(("rest", "caution", f"Only {rest14} rest day in 14 days"))
    if three_in_row or b2b >= 2:
        flags.append(("b2b", "high", "Three high-intensity days in a row" if three_in_row
                      else f"{b2b} back-to-back high-intensity pairs this week"))
    elif b2b == 1:
        flags.append(("b2b", "caution", "Back-to-back high-intensity days this week"))
    if monotony is not None and monotony >= cfg["monotony_caution"] and acute > 0:
        flags.append(("monotony", "caution", f"Training monotony {monotony:.1f}: every day looks the same"))
    if seen >= 3 and low_hrv >= 3:
        flags.append(("hrv", "caution", f"HRV under baseline on {low_hrv} of the last {seen} mornings"))

    highs = sum(f[1] == "high" for f in flags)
    cautions = sum(f[1] == "caution" for f in flags)
    risk = "high" if highs or cautions >= 3 else "moderate" if cautions else "low"
    return {
        "date": day.isoformat(), "risk": risk,
        "flags": [{"key": k, "level": lvl, "text": txt} for k, lvl, txt in flags],
        "acute": rnd(acute, 0), "chronic": rnd(chronic, 0), "acwr": rnd(acwr, 2),
        "rest_days_7": rest7, "rest_days_14": rest14, "back_to_back": b2b,
        "monotony": rnd(monotony, 2),
    }


def build(activities: list[dict], daily: list[dict], cfg: dict, today: date) -> dict[str, Any]:
    start = today - timedelta(days=400)
    loads = daily_load(activities, start, today)
    hrv_rows = {d(r["date"]): r for r in daily}
    current = scan(loads, hrv_rows, today, cfg)

    weeks = []
    for w in range(11, -1, -1):
        end = today - timedelta(days=7 * w)
        s = scan(loads, hrv_rows, end, cfg)
        weeks.append({"week_ending": end.isoformat(), "load": s["acute"], "acwr": s["acwr"],
                      "rest_days": s["rest_days_7"], "back_to_back": s["back_to_back"],
                      "monotony": s["monotony"], "risk": s["risk"], "flags": [f["key"] for f in s["flags"]]})

    history = []
    for inj in cfg.get("history") or []:
        when = d(inj["date"])
        if when < start:
            continue
        before = scan(loads, hrv_rows, when - timedelta(days=1), cfg)
        history.append({"date": when.isoformat(), "label": inj.get("label", "Injury"), "scan": before})
    shared = []
    if history:
        now_keys = {f["key"] for f in current["flags"]}
        for h in history:
            common = now_keys & {f["key"] for f in h["scan"]["flags"]}
            if common:
                shared.append({"label": h["label"], "date": h["date"], "shared": sorted(common)})

    series = [{"date": day.isoformat(), "load": rnd(v, 0)}
              for day, v in sorted(loads.items()) if day >= today - timedelta(days=84)]
    acwr_series = []
    for day in sorted(loads):
        if day >= today - timedelta(days=84):
            s = scan(loads, hrv_rows, day, cfg)
            acwr_series.append({"date": day.isoformat(), "acwr": s["acwr"]})
    return {"current": current, "weeks": weeks, "history": history, "matches_past": shared,
            "daily_load": series, "acwr_series": acwr_series,
            "thresholds": {k: cfg[k] for k in ("acwr_caution", "acwr_high", "rest_day_load", "high_day_load")}}
