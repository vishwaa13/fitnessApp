"""Tournaments, recovery correlations and injury scan on small hand-built data."""

import random
from datetime import date, timedelta

from fitapp import injury, recovery, tournaments
from fitapp.config import load_config

CFG = load_config()
TODAY = date(2026, 10, 1)
HOME = (45.46, 9.19)
VIAREGGIO = (43.87, 10.25)


def act(i, day, name="Ultimate practice", typ="ultimate_disc", hour=19, minutes=90, load=150,
        avg=150, mx=180, coords=HOME, loc="Milano"):
    start = f"{day.isoformat()}T{hour:02d}:00"
    end_h = hour + minutes // 60
    return {"id": i, "name": name, "type": typ, "date": day.isoformat(), "start": start,
            "end": f"{day.isoformat()}T{min(end_h, 23):02d}:{minutes % 60:02d}", "duration_min": minutes,
            "avg_hr": avg, "max_hr": mx, "load": load, "lat": coords[0], "lon": coords[1], "location": loc}


def daily_rows(start, n, hrv_fn):
    return [{"date": (start + timedelta(days=k)).isoformat(), "hrv": hrv_fn(start + timedelta(days=k)),
             "hrv_low": 54, "hrv_high": 70, "sleep_score": 78, "rhr": 48} for k in range(n)]


def burla_games():
    d0 = date(2026, 6, 20)
    games = []
    for day in range(3):
        for g in range(2):
            games.append(act(100 + day * 2 + g, d0 + timedelta(days=day), name=f"Game {day * 2 + g + 1}",
                             hour=9 + 3 * g, minutes=75, load=160 - day * 15, avg=165 - day * 8, mx=188 - day * 3,
                             coords=VIAREGGIO, loc="Viareggio"))
    return d0, games


def test_tournament_detected_named_and_rebound_counted():
    d0, games = burla_games()
    practices = [act(1, date(2026, 6, 10)), act(2, date(2026, 6, 17))]
    end = d0 + timedelta(days=2)

    def hrv(day):
        if day <= d0:
            return 60
        if day <= end + timedelta(days=2):
            return 45
        return 61

    daily = daily_rows(date(2026, 6, 1), 60, hrv)
    reps = tournaments.build(games + practices, daily, CFG["tournaments"], HOME, 190, TODAY)
    assert len(reps) == 1
    t = reps[0]
    assert t["name"] == "Burla 2026" and t["days"] == 3 and len(t["games"]) == 6
    assert t["total_load"] == sum(g["load"] for g in games)
    assert t["peak_hr"] == 188
    assert t["fade_pct"] < 0
    assert t["hrv_baseline"] == 60 and t["hrv_nadir"] == 45
    assert t["rebound_status"] == "rebounded" and t["rebound_days"] == 3


def test_weekly_practices_are_not_tournaments():
    acts = [act(i, date(2026, 9, 1) + timedelta(days=7 * i)) for i in range(6)]
    assert tournaments.build(acts, [], CFG["tournaments"], HOME, 190, TODAY) == []


def test_manual_tournament():
    cfg = {**CFG["tournaments"], "manual": [{"name": "Hat", "start": "2026-09-05", "end": "2026-09-06"}]}
    acts = [act(1, date(2026, 9, 5), name="Morning"), act(2, date(2026, 9, 6), name="Afternoon")]
    reps = tournaments.build(acts, [], cfg, HOME, 190, TODAY)
    assert [r["name"] for r in reps] == ["Hat"]


def test_alcohol_effect_found_and_signed():
    rng = random.Random(1)
    start = TODAY - timedelta(days=150)
    drink_days = {start + timedelta(days=k) for k in range(5, 150, 6)}
    def hrv(day):
        return 60 + rng.gauss(0, 2) - (10 if (day - timedelta(days=1)) in drink_days else 0)
    daily = daily_rows(start, 150, hrv)
    tags = {d.isoformat(): ["alcohol"] for d in drink_days}
    ev = recovery.evening_tags(daily, [], [], tags, CFG["recovery"], HOME, 180)
    res = recovery.analyse(daily, ev, 150, TODAY)
    alc = next(e for e in res["effects"] if e["key"] == "alcohol")
    assert alc["hrv"]["confidence"] == "clear"
    assert -12 < alc["hrv"]["delta"] < -8
    assert alc["hrv"]["ci"][1] < 0


def test_late_training_and_travel_tags():
    acts = [act(1, date(2026, 9, 20), hour=20), act(2, date(2026, 9, 21), hour=10, coords=VIAREGGIO)]
    ev = recovery.evening_tags([], acts, [], {}, CFG["recovery"], HOME, 180)
    assert ev[date(2026, 9, 20)] == {"late_training"}
    assert ev[date(2026, 9, 21)] == {"travel"}


def test_injury_flags_spike_and_no_rest():
    acts = []
    i = 0
    for k in range(60, 7, -1):          # steady weeks: 3 sessions of 100
        d = TODAY - timedelta(days=k)
        if d.weekday() in (0, 2, 4):
            i += 1
            acts.append(act(i, d, load=100))
    for k in range(7):                  # last week: every day, 200 each
        i += 1
        acts.append(act(i, TODAY - timedelta(days=k), load=200))
    res = injury.build(acts, [], CFG["injury"], TODAY)
    keys = {f["key"]: f["level"] for f in res["current"]["flags"]}
    assert res["current"]["risk"] == "high"
    assert keys["acwr"] == "high" and keys["rest"] == "high" and keys["b2b"] == "high"


def test_injury_quiet_week_is_low_risk():
    acts = []
    for k in range(60, -1, -1):
        d = TODAY - timedelta(days=k)
        if d.weekday() in (0, 2, 4):
            acts.append(act(k, d, load=100))
    res = injury.build(acts, [], CFG["injury"], TODAY)
    assert res["current"]["risk"] == "low"
