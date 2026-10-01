"""Synthetic but realistic data so the dashboard works before any secrets exist.

Runs the exact same analysis code as a real run. Nothing here is real data.
"""

from __future__ import annotations

import copy
import math
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .pipeline import analyze

HOME = (45.46, 9.19)
VIAREGGIO = (43.87, 10.25)
BOLOGNA = (44.49, 11.34)


def _act(i, name, typ, day, hour, minutes, load, avg_hr, max_hr, loc=None, coords=HOME, dist=None, ate=None, ante=None):
    start = datetime.combine(day, time(int(hour) % 24, int(round((hour % 1) * 60))))
    return {"id": 9_000_000 + i, "name": name, "type": typ, "date": day.isoformat(),
            "start": start.isoformat(timespec="minutes"),
            "end": (start + timedelta(minutes=minutes)).isoformat(timespec="minutes"),
            "duration_min": minutes, "distance_km": dist, "avg_hr": avg_hr, "max_hr": max_hr,
            "load": load, "aerobic_te": ate, "anaerobic_te": ante, "location": loc,
            "lat": coords[0] if coords else None, "lon": coords[1] if coords else None}


def build(cfg: dict, now: datetime | None = None) -> dict:
    tz = ZoneInfo(cfg["timezone"])
    now = now or datetime.now(tz).replace(hour=7, minute=10, second=0, microsecond=0)
    today = now.date()
    rng = random.Random(42)
    cfg = copy.deepcopy(cfg)
    cfg["tournaments"]["manual"] = [{"name": "National team tryouts", "start": today + timedelta(days=2),
                                     "end": today + timedelta(days=3)}]
    cfg["injury"]["history"] = [{"date": today - timedelta(days=78), "label": "Glute strain"}]

    start = today - timedelta(days=200)
    tournaments = [
        ("Burla", today - timedelta(days=103), 3, "Viareggio", VIAREGGIO),
        ("Pesca", today - timedelta(days=45), 2, "Bologna", BOLOGNA),
        ("Club", today - timedelta(days=12), 2, "Milano", (45.48, 9.21)),
    ]
    t_days = {}
    for name, s, n, loc, xy in tournaments:
        for k in range(n):
            t_days[s + timedelta(days=k)] = (name, k, loc, xy)

    acts, aid = [], 0
    late_days, travel_days, alcohol_days = set(), set(), set()
    injury_day = today - timedelta(days=78)
    for k in range((today - start).days):
        day = start + timedelta(days=k)
        wd = day.weekday()
        if day in t_days:
            name, idx, loc, xy = t_days[day]
            games = 3 if idx < 2 else 2
            for g in range(games):
                fade = 1 - 0.035 * (idx * 3 + g)
                aid += 1
                acts.append(_act(aid, f"{name} game {idx * 3 + g + 1}", "ultimate_disc", day, 9 + g * 2.5, 75,
                                 round(rng.uniform(140, 175) * fade), round(165 * fade + rng.uniform(-4, 4)),
                                 round(187 * fade + rng.uniform(-3, 3)), loc, xy, round(6.5 * fade, 1), 3.4, 2.6 * fade))
            if loc != "Milano":
                travel_days.add(day)
            if idx == 1:
                alcohol_days.add(day)
            continue
        # The fortnight before the injury: no rest days, back-to-back hard sessions.
        spike = injury_day - timedelta(days=13) <= day < injury_day
        if wd == 0 or (spike and wd == 4):
            aid += 1
            acts.append(_act(aid, "Strength – Lower", "strength_training", day, 7, 55, rng.randint(45, 65), 112, 150, ate=1.8, ante=0.9))
        if wd == 1:
            aid += 1
            kind = rng.choice(["Track intervals", "Tempo run", "Hill repeats"])
            acts.append(_act(aid, kind, "running", day, 18, 50, rng.randint(140, 185) + (40 if spike else 0), 158, 184,
                             dist=round(rng.uniform(8, 11), 1), ate=3.8, ante=2.4))
        if wd == 2 or (spike and wd == 6):
            aid += 1
            acts.append(_act(aid, "Ultimate practice", "ultimate_disc", day, 19.5, 110, rng.randint(150, 200) + (30 if spike else 0),
                             148, 186, ate=3.5, ante=2.8))
            late_days.add(day)
        if wd == 3:
            aid += 1
            acts.append(_act(aid, "Strength – Upper", "strength_training", day, 7, 50, rng.randint(35, 55), 105, 142, ate=1.5, ante=0.6))
        if wd == 5:
            aid += 1
            acts.append(_act(aid, "Long run", "running", day, 9, rng.randint(70, 95), rng.randint(110, 150), 142, 165,
                             dist=round(rng.uniform(13, 18), 1), ate=3.2, ante=0.4))
            if rng.random() < 0.45:
                alcohol_days.add(day)
        if wd == 4 and rng.random() < 0.3:
            alcohol_days.add(day)
        if wd in (1, 3) and rng.random() < 0.6:
            aid += 1
            acts.append(_act(aid, "Bike commute", "cycling", day, 8.3, 25, rng.randint(15, 25), 118, 140, dist=7.5, ate=1.2))
    # Yesterday: a big late session followed by drinks, so this morning is red.
    y = today - timedelta(days=1)
    aid += 1
    acts.append(_act(aid, "Hill sprints", "running", y, 20, 55, 190, 162, 189, dist=8.2, ate=4.1, ante=3.3))
    late_days.add(y)
    alcohol_days.add(y)

    # Daily recovery metrics, driven by what happened the evening before.
    loads = {}
    for a in acts:
        loads[a["date"]] = loads.get(a["date"], 0) + a["load"]
    daily, fatigue = [], 0.0
    for k in range((today - start).days + 1):
        day = start + timedelta(days=k)
        prev = day - timedelta(days=1)
        load = loads.get(prev.isoformat(), 0)
        fatigue = fatigue * 0.6 + max(0, load - 150) / 70
        trend = 3 * math.sin(k / 30)
        hrv = 62 + trend - fatigue + rng.gauss(0, 3.2)
        sleep = 78 + rng.gauss(0, 6)
        rhr = 48 + fatigue * 0.4 + rng.gauss(0, 1.2)
        if prev in alcohol_days:
            hrv -= 9; sleep -= 11; rhr += 4
        if prev in late_days:
            hrv -= 4; sleep -= 6; rhr += 1
        if prev in travel_days:
            hrv -= 4; sleep -= 7
        if prev in t_days:
            hrv -= 5
        if prev == today - timedelta(days=1):
            hrv -= 8; sleep -= 8
        hrv = max(30, hrv)
        sleep = int(max(30, min(98, sleep)))
        readiness = int(max(5, min(100, 55 + (hrv - 58) * 2.2 + (sleep - 72) * 0.8 - fatigue * 2)))
        level = ("PRIME" if readiness >= 95 else "HIGH" if readiness >= 75 else "MODERATE" if readiness >= 50
                 else "LOW" if readiness >= 25 else "POOR")
        daily.append({
            "date": day.isoformat(), "hrv": round(hrv), "hrv_weekly": None,
            "hrv_low": 54, "hrv_high": 71, "hrv_status": "BALANCED" if hrv > 54 else "UNBALANCED",
            "sleep_score": sleep, "sleep_hours": round(7.4 + (sleep - 78) / 25 + rng.gauss(0, 0.3), 2),
            "rhr": round(rhr), "readiness": readiness, "readiness_level": level,
            "readiness_feedback": "HRV below baseline, poor sleep" if readiness < 40 else "",
            "bb_high": None, "bb_wake": None, "stress": None, "lifestyle_tags": [],
        })
    for i, row in enumerate(daily):
        window = [r["hrv"] for r in daily[max(0, i - 6):i + 1]]
        row["hrv_weekly"] = round(sum(window) / len(window))

    tags_text = "\n".join(f"{d.strftime('%d/%m')} alcohol" for d in sorted(alcohol_days)
                          if d >= today - timedelta(days=300))

    events = _calendar(today, tz)
    upcoming = _upcoming(events, cfg, today)
    data = analyze(activities=acts, daily=daily, gym_text=_gym_log(today, rng), manual_tags=_tags(tags_text, today),
                   cfg=cfg, now=now, calendar_events=events, upcoming_events=upcoming,
                   sources={"garmin": "demo", "keep": "demo", "calendar": "demo"})
    data["demo"] = True
    for t in data["overload"]["templates"]:
        t["garmin_status"] = "demo (would upload)"
    for a in data["today"]["actions"]:
        a["status"] = "demo (would apply)"
    return data


def _tags(text: str, today: date) -> dict:
    from .gymlog import parse_tags_note
    return parse_tags_note(text, today)


DEMO_PLACES = {
    "National team tryouts": ("National team tryouts 2026", "Odense", "Denmark", "Fruens Bøge sports park", 55.39, 10.39, "grass", "open"),
    "Beach hat": ("Autumn Beach Hat", "Viareggio", "Italy", "Spiaggia della Lecciona", 43.87, 10.25, "beach", "hat (random teams)"),
    "Club championships": ("European club championships", "Lisbon", "Portugal", None, 38.72, -9.14, "grass", "mixed"),
}


def _upcoming(events: list[dict], cfg: dict, today: date) -> list[dict]:
    from .events import enrich, select

    def fake_lookup(title, start, end, location):
        name, city, country, venue, lat, lon, surface, division = DEMO_PLACES[title]
        return {"full_name": name, "city": city, "country": country, "venue": venue, "latitude": lat,
                "longitude": lon, "surface": surface, "division": division, "website": None,
                "summary": "Demo entry. With the free GEMINI_API_CODE secret set, this comes from a Google search for your event.",
                "confidence": "medium"}

    from .events import attach_flights, flights

    chosen = select(events, list(cfg["events"]["keywords"]) + ["championships"], cfg["tournaments"]["manual"], today)
    upcoming, _ = attach_flights(enrich(chosen, {}, fake_lookup, HOME, today), flights(events, today))
    return upcoming


def _calendar(today: date, tz: ZoneInfo) -> list[dict]:
    def ev(i, title, offset, hour, minutes=60):
        s = datetime.combine(today + timedelta(days=offset), time(hour), tz)
        return {"id": f"demo{i}", "title": title, "start": s, "end": s + timedelta(minutes=minutes),
                "all_day": False, "role": None}
    tryouts_start = today + timedelta(days=2)
    return [
        ev(1, "Track intervals 6×800m", 0, 18),
        ev(2, "Gym – Lower A", 1, 7),
        {"id": "demo3", "title": "National team tryouts", "start": tryouts_start,
         "end": tryouts_start + timedelta(days=2), "all_day": True, "role": None},
        ev(4, "Tempo run 5 km", 4, 18),
        ev(5, "Easy run", 5, 9),
        ev(6, "Gym – Upper A", 6, 7),
        {"id": "demo7", "title": "Beach hat", "start": today + timedelta(days=24),
         "end": today + timedelta(days=26), "all_day": True, "role": None},
        {"id": "demo8", "title": "Club championships", "start": today + timedelta(days=61),
         "end": today + timedelta(days=65), "all_day": True, "role": None},
        {**ev(9, "Flight to Lisbon (TP 753)", 60, 7, 255), "location": "Milan MXP"},
        {**ev(10, "Flight to Milan (TP 828)", 65, 19, 170), "location": "Lisbon LIS"},
    ]


def _gym_log(today: date, rng: random.Random) -> str:
    """Twelve weeks of Lower A / Upper A written the way people actually write them."""
    lifts = {
        "Lower A": [("Squat", 85.0, 5, 8, 5, "{n}x{r} {w}kg"), ("RDL", 60.0, 6, 10, 2.5, "{w}: {reps}"),
                    ("Hip thrust", 80.0, 5, 8, 5, "{w}x{r}x{n}"), ("Bulgarian split squat", 14.0, 8, 12, 2, "{n}x{r} @ {w}")],
        "Upper A": [("Bench", 62.5, 6, 10, 2.5, "{w}kg {reps}"), ("Pull-ups", None, 6, 10, 2.5, "bw {reps}"),
                    ("OHP", 37.5, 6, 10, 2.5, "{n}x{r} {w}"), ("DB row", 22.0, 8, 12, 2, "{w}x{r}, {w}x{r}, {w}x{r2}")],
    }
    state = {name: {lift[0]: [lift[1], [lift[2]] * 3] for lift in ls} for name, ls in lifts.items()}
    lines = ["Gym logs", ""]
    day = today - timedelta(days=84)
    while day < today:
        name = "Lower A" if day.weekday() == 0 else "Upper A" if day.weekday() == 3 else None
        if name:
            lines.append(f"{day.strftime('%a %d/%m')} – {name}")
            for lname, _w0, lo, hi, inc, fmt in lifts[name]:
                w, reps = state[name][lname]
                done = [max(lo - 1, min(hi, r + (1 if rng.random() < 0.75 else 0))) for r in reps]
                w_txt = f"{w:g}" if w else "bw"
                text = fmt.format(n=len(done), r=done[0], r2=done[-1], w=w_txt, reps=",".join(str(x) for x in done))
                lines.append(f"{lname} {text}")
                if all(r >= hi for r in done):
                    state[name][lname] = [(w + inc) if w else None, [lo] * 3]
                else:
                    state[name][lname] = [w, done]
            lines.append("")
        day += timedelta(days=1)
    return "\n".join(lines)
