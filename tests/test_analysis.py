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


def _pain(day, label="Left shoulder pain", part="shoulder"):
    from fitapp.gymlog import Session
    s = Session(date=day, notes=[{"text": "Left shoulder pain, stopped", "body_part": part, "side": "left",
                                  "exercise": "Incline dumbbell bench press", "stopped": True}])
    return injury.Signals(pain=injury.pain_reports([s], CFG["injury"], TODAY))


def _flags(res):
    return {f["key"]: (f["level"], f["text"]) for f in res["current"]["flags"]}


def test_recent_pain_makes_risk_high_then_caution_then_clears():
    res = injury.build([], [], CFG["injury"], TODAY, _pain(TODAY - timedelta(days=1)))
    flag = res["current"]["flags"][0]
    assert res["current"]["risk"] == "high" and flag["key"] == "pain"
    assert flag["text"] == "Left shoulder pain yesterday during incline dumbbell bench press (you stopped)"
    assert injury.build([], [], CFG["injury"], TODAY, _pain(TODAY - timedelta(days=9)))["current"]["risk"] == "moderate"
    assert injury.build([], [], CFG["injury"], TODAY, _pain(TODAY - timedelta(days=20)))["current"]["risk"] == "low"


def test_pain_from_the_gym_log_becomes_injury_history():
    res = injury.build([], [], CFG["injury"], TODAY, _pain(TODAY - timedelta(days=30)))
    assert [(h["label"], h["source"]) for h in res["history"]] == [("Left shoulder pain", "gym log")]
    assert res["pain"][0]["active"] is False


def _log(*lines):
    from fitapp.gymlog import parse_gym_log
    return parse_gym_log("\n".join(lines), today=TODAY, set_format="weight_x_reps")


def test_hard_sets_skip_warm_ups_and_map_to_body_parts():
    from fitapp import gymload
    s, = _log("30/09", "Squats", "60 X 10", "80 X 10", "100 X 4", "Bench press 70 x 8, 70 x 7", "Pull ups 0 X 5")
    sets = gymload.daily_sets([s], CFG["injury"])
    day = date(2026, 9, 30)
    assert sets["quad"][day] == 2 and sets["glute"][day] == 2        # 60 kg warm-up doesn't count
    assert sets["chest"][day] == 2 and sets["tricep"][day] == 2 and sets["back"][day] == 1


def test_gym_volume_spike_is_flagged():
    from fitapp import gymload
    lines = []
    for k in (34, 27, 20, 13):                 # easy weeks: 3 bench sets
        lines += [(TODAY - timedelta(days=k)).strftime("%d/%m"), "Bench press 70 x 8, 70 x 8, 70 x 8"]
    for k in (5, 3, 1):                        # this week: 4 sets three times
        lines += [(TODAY - timedelta(days=k)).strftime("%d/%m"), "Bench press 70 x 8, 70 x 8, 70 x 8, 70 x 8"]
    sets = gymload.daily_sets(_log(*lines), CFG["injury"])
    res = injury.build([], [], CFG["injury"], TODAY, injury.Signals(sets=sets))
    level, text = _flags(res)["volume"]
    assert level == "high" and text.startswith("Chest: 12 hard sets this week, 2.3×")


def test_no_volume_flag_until_the_log_has_four_weeks():
    from fitapp import gymload
    lines = []
    for k in (12, 5, 3, 1):
        lines += [(TODAY - timedelta(days=k)).strftime("%d/%m"), "Bench press 70 x 8, 70 x 8, 70 x 8, 70 x 8"]
    sets = gymload.daily_sets(_log(*lines), CFG["injury"])
    assert "volume" not in _flags(injury.build([], [], CFG["injury"], TODAY, injury.Signals(sets=sets)))


def test_first_session_after_a_break_is_flagged_and_restarts_lighter():
    from fitapp import gymload, overload
    sessions = _log("05/09", "Bench press 70 x 8, 70 x 8", "29/09", "Squats 100 x 5")
    sets = gymload.daily_sets(sessions, CFG["injury"])
    res = injury.build([], [], CFG["injury"], TODAY, injury.Signals(sets=sets))
    assert "return" not in _flags(res)       # squats on 29/09 were the first ever, not a return
    sessions = _log("05/09", "Bench press 70 x 8, 70 x 8", "29/09", "Bench press 70 x 8")
    sets = gymload.daily_sets(sessions, CFG["injury"])
    level, text = _flags(injury.build([], [], CFG["injury"], TODAY, injury.Signals(sets=sets)))["return"]
    assert text.startswith("29 Sep was your first chest/shoulder/tricep session in 24 days")
    plan = overload.build_plan(_log("05/09", "Bench press 70 x 8, 70 x 8"), CFG["overload"], TODAY, [], 14)
    nxt = plan["templates"][0]["exercises"][0]["next"]
    assert nxt["action"] == "return" and nxt["weight"] == 62.5 and "26 days ago" in nxt["note"]


def test_soreness_flags_and_bad_soreness_counts_as_pain():
    sore = [{"date": (TODAY - timedelta(days=1)).isoformat(), "body_part": "hamstring", "side": None,
             "score": 3, "text": "hamstrings 3/5"}]
    assert _flags(injury.build([], [], CFG["injury"], TODAY, injury.Signals(soreness=sore)))["soreness"] == \
        ("caution", "Hamstring soreness 3/5 yesterday")
    sore[0]["score"] = 4
    pain = injury.pain_reports([], CFG["injury"], TODAY, sore)
    assert pain[0]["label"] == "Hamstring soreness 4/5" and pain[0]["active"]


def test_alcohol_flags():
    last_night = {TODAY - timedelta(days=1)}
    assert _flags(injury.build([], [], CFG["injury"], TODAY, injury.Signals(alcohol=last_night)))["alcohol"][1] \
        .startswith("Alcohol last night")
    week = {TODAY - timedelta(days=k) for k in (2, 4, 6)}
    res = injury.build([], [], CFG["injury"], TODAY, injury.Signals(alcohol=week))
    assert _flags(res)["alcohol"][1] == "Alcohol on 3 of the last 7 evenings" and res["current"]["alcohol_7"] == 3
