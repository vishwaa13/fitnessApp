from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fitapp.config import load_config
from fitapp.readiness import assess, classify, plan_swaps

CFG = load_config()["readiness"]
TH = CFG["thresholds"]
TZ = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 10, 1, 7, 0, tzinfo=TZ)


def row(**kw):
    base = {"readiness": 70, "hrv": 62, "hrv_low": 54, "hrv_high": 71, "hrv_status": "BALANCED",
            "sleep_score": 80, "sleep_hours": 7.5, "rhr": 48}
    base.update(kw)
    return base


PREV = [row() for _ in range(7)]


def test_green_morning():
    assert assess(row(), PREV, TH)["status"] == "green"


def test_low_readiness_alone_is_red():
    assert assess(row(readiness=30), PREV, TH)["status"] == "red"


def test_one_red_plus_one_amber_is_red():
    v = assess(row(hrv=50, hrv_status="UNBALANCED", sleep_score=60), PREV, TH)
    assert v["status"] == "red"


def test_single_amber_stays_green_two_ambers_amber():
    assert assess(row(sleep_score=60), PREV, TH)["status"] == "green"
    assert assess(row(sleep_score=60, rhr=54), PREV, TH)["status"] == "amber"


def test_no_data_is_unknown():
    assert assess(None, PREV, TH)["status"] == "unknown"


def ev(i, title, days, hour=18, all_day=False, role=None):
    d = NOW.date() + timedelta(days=days)
    start = d if all_day else datetime(d.year, d.month, d.day, hour, tzinfo=TZ)
    end = (d + timedelta(days=1)) if all_day else start + timedelta(hours=1)
    return {"id": str(i), "title": title, "start": start, "end": end, "all_day": all_day, "role": role}


def test_classify_words_not_substrings():
    assert classify(ev(1, "Hat tournament", 0), CFG) == "protected"
    assert classify(ev(1, "Chat with coach", 0), CFG) == "other"
    assert classify(ev(1, "Hill repeats", 0), CFG) == "hard"


def test_swap_moves_to_next_free_day_avoiding_tournament_eve():
    events = [ev(1, "Track intervals", 0), ev(2, "Gym – lower", 1, 7),
              {**ev(3, "Team Denmark tryouts", 3, all_day=True)}, ev(4, "Tempo run", 5)]
    acts = plan_swaps(events, "red", CFG, NOW)
    assert len(acts) == 1
    a = acts[0]
    # +1 has a hard gym session, +2 is the eve of the tryouts, +3 is the tryouts, +4 is free
    assert a["moved_to"] == NOW.date() + timedelta(days=4)
    assert a["light"]["title"].startswith("Easy run")


def test_no_swap_on_green_or_for_past_sessions():
    assert plan_swaps([ev(1, "Tempo run", 0)], "green", CFG, NOW) == []
    assert plan_swaps([ev(1, "Tempo run", 0, hour=6)], "red", CFG, NOW) == []


def test_amber_swaps_only_when_configured():
    events = [ev(1, "Tempo run", 0)]
    assert plan_swaps(events, "amber", CFG, NOW) == []
    assert len(plan_swaps(events, "amber", {**CFG, "swap_when": "amber"}, NOW)) == 1


def test_light_events_are_left_alone_and_two_hard_sessions_get_different_days():
    events = [ev(1, "Easy run · 30–40 min Z2", 0, role="light"), ev(2, "Tempo run", 0, 18), ev(3, "Heavy squats", 0, 19)]
    acts = plan_swaps(events, "red", CFG, NOW)
    assert [a["event_id"] for a in acts] == ["2", "3"]
    assert acts[0]["moved_to"] != acts[1]["moved_to"]
    assert acts[1]["light"]["title"].startswith("Mobility")


def test_no_free_day_means_replace_in_place():
    events = [ev(i, "Intervals", k) for i, k in enumerate(range(0, 9))]
    acts = plan_swaps(events, "red", CFG, NOW)
    assert acts[0]["moved_to"] is None


def test_manual_protected_days():
    events = [ev(1, "Intervals", 0)]
    acts = plan_swaps(events, "red", CFG, NOW, {date(2026, 10, 3)})
    assert acts[0]["moved_to"] == date(2026, 10, 4)
