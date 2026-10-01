"""Find tournaments in the activity list and report what each one cost.

A tournament is a cluster of game activities on consecutive days at the same
place. A cluster counts when it has 2+ games and is away from home, has 3+
games, or has 2+ games on one day. Tournaments listed under
``tournaments.manual`` in config.yml are always reported.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from .util import d, has_keyword, haversine_km, mean, rnd

NOT_GAMES = {"strength_training", "indoor_cardio", "cycling", "road_biking", "virtual_ride",
             "mountain_biking", "gravel_cycling", "indoor_cycling", "e_bike_fitness", "swimming",
             "lap_swimming", "open_water_swimming", "walking", "hiking", "yoga", "pilates",
             "breathwork", "running", "treadmill_running", "trail_running", "track_running",
             "indoor_rowing", "elliptical", "stair_climbing", "hiit", "mobility"}


def is_game(act: dict, cfg: dict) -> bool:
    if has_keyword(act.get("name"), ["practice", "training", "drills", "throwing", "pickup"]):
        return False
    if act.get("type") in NOT_GAMES and not has_keyword(act.get("name"), ["game", "match", "tournament"]):
        return False
    return act.get("type") in cfg["game_types"] or bool(has_keyword(act.get("name"), cfg["game_keywords"]))


def _coords(act: dict) -> tuple[float, float] | None:
    if act.get("lat") is not None and act.get("lon") is not None:
        return (act["lat"], act["lon"])
    return None


def _same_place(a: dict, b: dict) -> bool:
    ca, cb = _coords(a), _coords(b)
    if ca and cb:
        return haversine_km(ca, cb) <= 40
    la, lb = (a.get("location") or "").lower(), (b.get("location") or "").lower()
    return not la or not lb or la == lb


def _away(acts: list[dict], home: tuple[float, float] | None) -> bool:
    if not home:
        return False
    pts = [c for c in (_coords(a) for a in acts) if c]
    return bool(pts) and min(haversine_km(p, home) for p in pts) > 60


def _name(acts: list[dict], cfg: dict, start: date) -> str:
    locs = [a.get("location") for a in acts if a.get("location")]
    loc = Counter(locs).most_common(1)[0][0] if locs else None
    for place, label in (cfg.get("names_by_location") or {}).items():
        if loc and place.lower() in loc.lower():
            return f"{label} {start.year}"
        if any(has_keyword(a.get("name"), [place]) for a in acts):
            return f"{label} {start.year}"
    # A word that appears in most activity names ("Burla game 3") is a good label.
    words = Counter()
    for a in acts:
        for w in set(re.findall(r"[A-Za-z][A-Za-z']{2,}", a.get("name") or "")):
            if w.lower() not in {"game", "match", "ultimate", "frisbee", "the", "and", "vs", "day",
                                 "final", "semi", "quarter", "pool", "other", "running", "walk"}:
                words[w] += 1
    if words:
        word, count = words.most_common(1)[0]
        if count >= max(2, len(acts) // 2):
            return f"{word} {start.year}"
    return f"{loc or 'Tournament'} · {start.strftime('%b %Y')}"


def detect(activities: list[dict], cfg: dict, home: tuple[float, float] | None) -> list[list[dict]]:
    games = sorted((a for a in activities if is_game(a, cfg)), key=lambda a: a["start"])
    manual = []
    for m in cfg.get("manual") or []:
        start, end = d(m["start"]), d(m.get("end") or m["start"])
        acts = [a for a in activities if start <= d(a["date"]) <= end
                and (is_game(a, cfg) or a.get("type") not in NOT_GAMES)]
        manual.append((m, start, end, acts))
    claimed = {a["id"] for *_, acts in manual for a in acts}

    clusters: list[list[dict]] = []
    for g in games:
        if g["id"] in claimed:
            continue
        last = clusters[-1][-1] if clusters else None
        if last and (d(g["date"]) - d(last["date"])).days <= 1 and _same_place(g, last):
            clusters[-1].append(g)
        else:
            clusters.append([g])

    found = []
    for c in clusters:
        per_day = Counter(a["date"] for a in c)
        if len(c) >= 2 and (_away(c, home) or len(c) >= 3 or max(per_day.values()) >= 2):
            found.append(c)
    for m, start, end, acts in manual:
        if acts:
            for a in acts:
                a.setdefault("_manual_name", m["name"])
            found.append(sorted(acts, key=lambda a: a["start"]))
    return sorted(found, key=lambda c: c[0]["start"])


def _hrv_by_date(daily: list[dict]) -> dict[date, float]:
    return {d(r["date"]): r["hrv"] for r in daily if r.get("hrv") is not None}


def report(cluster: list[dict], daily: list[dict], cfg: dict, max_hr: float | None,
           today: date) -> dict[str, Any]:
    start, end = d(cluster[0]["date"]), d(cluster[-1]["date"])
    name = cluster[0].get("_manual_name") or _name(cluster, cfg, start)
    days = sorted({d(a["date"]) for a in cluster})
    games = []
    for i, a in enumerate(cluster, 1):
        dur = a.get("duration_min") or 0
        intensity = (a["avg_hr"] / max_hr) if (a.get("avg_hr") and max_hr) else None
        games.append({
            "n": i, "id": a["id"], "name": a.get("name"), "date": a["date"], "start": a["start"],
            "day": days.index(d(a["date"])) + 1,
            "duration_min": rnd(dur, 0), "avg_hr": a.get("avg_hr"), "max_hr": a.get("max_hr"),
            "load": rnd(a.get("load"), 0), "aerobic_te": a.get("aerobic_te"),
            "anaerobic_te": a.get("anaerobic_te"),
            "intensity_pct": rnd(intensity * 100 if intensity else None, 1),
            "load_per_min": rnd(a["load"] / dur, 2) if a.get("load") and dur else None,
            "distance_km": a.get("distance_km"),
        })

    per_day = []
    for i, day in enumerate(days, 1):
        g = [x for x in games if x["day"] == i]
        per_day.append({
            "day": i, "date": day.isoformat(), "games": len(g),
            "load": rnd(sum(x["load"] or 0 for x in g), 0),
            "minutes": rnd(sum(x["duration_min"] or 0 for x in g), 0),
            "avg_intensity_pct": rnd(mean(x["intensity_pct"] for x in g), 1),
            "load_per_min": rnd(mean(x["load_per_min"] for x in g), 2),
            "peak_hr": max((x["max_hr"] or 0 for x in g), default=None) or None,
        })

    # Intensity fade: first day vs last day (or first vs last game on a one-day event).
    fade = None
    basis = "avg_intensity_pct" if any(p["avg_intensity_pct"] for p in per_day) else "load_per_min"
    if len(per_day) >= 2 and per_day[0][basis] and per_day[-1][basis]:
        fade = (per_day[-1][basis] - per_day[0][basis]) / per_day[0][basis] * 100
    elif len(games) >= 2:
        key = "intensity_pct" if basis == "avg_intensity_pct" else "load_per_min"
        first, last = games[0][key], games[-1][key]
        if first and last:
            fade = (last - first) / first * 100

    # HRV rebound: pre-event baseline vs the mornings after.
    hrv = _hrv_by_date(daily)
    pre = [hrv[start - timedelta(days=k)] for k in range(0, 7) if (start - timedelta(days=k)) in hrv]
    baseline = mean(pre)
    tol = float(cfg.get("hrv_rebound_tolerance", 0.05))
    # Morning-indexed: the morning of day 1 is still "before"; the morning after
    # the last game day is the first one that reflects the final games.
    series = []
    day = start - timedelta(days=6)
    while day <= min(end + timedelta(days=14), today):
        series.append({"date": day.isoformat(), "hrv": hrv.get(day),
                       "phase": "before" if day <= start else "during" if day <= end else "after"})
        day += timedelta(days=1)
    during_after = [hrv[x] for x in hrv if start < x <= end + timedelta(days=3)]
    nadir = min(during_after) if during_after else None
    rebound_days = None
    rebound_status = "no_hrv"
    if baseline:
        rebound_status = "pending"
        for k in range(1, 15):
            day = end + timedelta(days=k)
            if day > today:
                break
            v = hrv.get(day)
            if v is not None and v >= baseline * (1 - tol):
                rebound_days = k
                rebound_status = "rebounded"
                break
        else:
            rebound_status = "not_within_14d"
        if rebound_status == "pending" and (today - end).days >= 14:
            rebound_status = "not_within_14d"

    total_load = sum(g["load"] or 0 for g in games)
    return {
        "id": f"{start.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}",
        "name": name,
        "location": next((a.get("location") for a in cluster if a.get("location")), None),
        "start": start.isoformat(), "end": end.isoformat(), "days": len(days),
        "games": games, "per_day": per_day,
        "total_load": rnd(total_load, 0),
        "total_minutes": rnd(sum(g["duration_min"] or 0 for g in games), 0),
        "peak_hr": max((g["max_hr"] or 0 for g in games), default=None) or None,
        "fade_pct": rnd(fade, 1), "fade_basis": "HR % of max" if basis == "avg_intensity_pct" else "load per minute",
        "hrv_baseline": rnd(baseline, 1), "hrv_nadir": nadir,
        "hrv_drop_pct": rnd((nadir - baseline) / baseline * 100, 1) if (nadir and baseline) else None,
        "rebound_days": rebound_days, "rebound_status": rebound_status,
        "hrv_series": series,
    }


def build(activities: list[dict], daily: list[dict], cfg: dict, home: tuple[float, float] | None,
          max_hr: float | None, today: date) -> list[dict]:
    reports = [report(c, daily, cfg, max_hr, today) for c in detect(activities, cfg, home)]
    return sorted(reports, key=lambda r: r["start"], reverse=True)
