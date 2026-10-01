"""What wrecks your recovery: next-morning HRV and sleep against evening tags.

Each morning is compared with your own rolling baseline (median of the
previous 21 mornings), so slow fitness trends don't masquerade as effects.
For every tag we compare the mornings after a tagged evening with all the
other mornings and bootstrap a 90% interval for the difference.
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from datetime import date, timedelta
from typing import Any

from .util import d, haversine_km, mean, parse_local, rnd

TAG_LABELS = {
    "alcohol": "Alcohol",
    "late_training": "Late training",
    "travel": "Travel",
    "tournament": "Tournament day",
    "high_load": "Big training day",
}


def evening_tags(daily: list[dict], activities: list[dict], tournaments: list[dict],
                 manual_tags: dict[str, list[str]], cfg: dict, home: tuple[float, float] | None,
                 high_load: float) -> dict[date, set[str]]:
    """Tags for each *evening* (calendar day)."""
    tags: dict[date, set[str]] = {}

    def add(day: date, tag: str) -> None:
        tags.setdefault(day, set()).add(tag)

    for day_str, items in manual_tags.items():
        for t in items:
            add(d(day_str), t)
    for row in daily:
        for t in row.get("lifestyle_tags") or []:
            add(d(row["date"]), t)

    load_by_day: dict[date, float] = {}
    for a in activities:
        day = d(a["date"])
        load_by_day[day] = load_by_day.get(day, 0) + (a.get("load") or 0)
        end = parse_local(a.get("end"))
        if end and end.hour >= int(cfg.get("late_training_hour", 20)):
            add(day, "late_training")
        if home and a.get("lat") is not None and a.get("lon") is not None:
            if haversine_km((a["lat"], a["lon"]), home) > float(cfg.get("travel_km", 150)):
                add(day, "travel")
    for day, load in load_by_day.items():
        if load >= high_load:
            add(day, "high_load")
    for t in tournaments:
        day = d(t["start"])
        while day <= d(t["end"]):
            add(day, "tournament")
            day += timedelta(days=1)
    return tags


def _bootstrap_ci(a: list[float], b: list[float], n: int = 1000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    diffs = []
    for _ in range(n):
        sa = [rng.choice(a) for _ in a]
        sb = [rng.choice(b) for _ in b]
        diffs.append(statistics.fmean(sa) - statistics.fmean(sb))
    diffs.sort()
    return diffs[int(0.05 * n)], diffs[int(0.95 * n) - 1]


def _baseline(values: dict[date, float], day: date, window: int = 21) -> float | None:
    prev = [values[day - timedelta(days=k)] for k in range(1, window + 1) if (day - timedelta(days=k)) in values]
    return statistics.median(prev) if len(prev) >= 5 else None


def analyse(daily: list[dict], tags_by_evening: dict[date, set[str]], window_days: int,
            today: date) -> dict[str, Any]:
    start = today - timedelta(days=window_days)
    rows = [r for r in daily if d(r["date"]) >= start]
    metrics = {"hrv": "HRV", "sleep_score": "Sleep score", "rhr": "Resting HR"}
    series: dict[str, dict[date, float]] = {
        m: {d(r["date"]): float(r[m]) for r in daily if r.get(m) is not None} for m in metrics}

    # Residual = morning value minus personal rolling baseline.
    resid: dict[str, dict[date, float]] = {m: {} for m in metrics}
    for m, vals in series.items():
        for day, v in vals.items():
            if day < start:
                continue
            base = _baseline(vals, day)
            if base is not None:
                resid[m][day] = v - base

    morning_tags = {day + timedelta(days=1): t for day, t in tags_by_evening.items()}
    all_tags = sorted({t for ts in tags_by_evening.values() for t in ts})
    effects = []
    for tag in all_tags:
        entry: dict[str, Any] = {"key": tag, "label": TAG_LABELS.get(tag, tag.replace("_", " ").capitalize())}
        # Tags that mostly happen together (travel + tournament) share their effect.
        tagged_days = [day for day, ts in morning_tags.items() if tag in ts and start <= day <= today]
        co = Counter(t for day in tagged_days for t in morning_tags[day] if t != tag)
        entry["n_total"] = len(tagged_days)
        entry["overlaps"] = [{"key": t, "share": round(c / len(tagged_days), 2)}
                             for t, c in co.most_common(2) if tagged_days and c / len(tagged_days) >= 0.5]
        for m in metrics:
            tagged = [v for day, v in resid[m].items() if tag in morning_tags.get(day, set())]
            other = [v for day, v in resid[m].items() if tag not in morning_tags.get(day, set())]
            base_mean = mean(series[m].get(day) for day in resid[m])
            if len(tagged) < 3 or len(other) < 5:
                entry[m] = {"n": len(tagged), "delta": rnd(mean(tagged) - mean(other), 1) if tagged and other else None,
                            "confidence": "too_few"}
                continue
            delta = statistics.fmean(tagged) - statistics.fmean(other)
            lo, hi = _bootstrap_ci(tagged, other)
            sd = statistics.pstdev(other) or 1.0
            clear = lo > 0 or hi < 0
            entry[m] = {
                "n": len(tagged), "delta": rnd(delta, 1),
                "delta_pct": rnd(delta / base_mean * 100, 1) if base_mean else None,
                "ci": [rnd(lo, 1), rnd(hi, 1)], "effect_size": rnd(delta / sd, 2),
                "confidence": "clear" if clear and len(tagged) >= 5 else "possible" if abs(delta / sd) >= 0.3 else "none",
            }
        effects.append(entry)
    # Biggest HRV hit first.
    effects.sort(key=lambda e: (e["hrv"].get("delta") is None, e["hrv"].get("delta") or 0))

    timeline = []
    for r in rows:
        day = d(r["date"])
        timeline.append({
            "date": r["date"], "hrv": r.get("hrv"), "hrv_low": r.get("hrv_low"), "hrv_high": r.get("hrv_high"),
            "sleep_score": r.get("sleep_score"), "sleep_hours": r.get("sleep_hours"), "rhr": r.get("rhr"),
            "readiness": r.get("readiness"),
            "tags": sorted(morning_tags.get(day, set())),
        })
    return {"window_days": window_days, "effects": effects, "timeline": timeline,
            "tag_labels": {t: TAG_LABELS.get(t, t.replace("_", " ").capitalize()) for t in all_tags}}
