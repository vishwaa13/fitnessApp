"""Bedtime consistency and the week in review."""

from datetime import date, timedelta

from fitapp import sleep, weekly
from fitapp.recovery import evening_tags

TODAY = date(2026, 10, 27)   # a Tuesday


def night(morning: date, bed: str, wake: str) -> dict:
    """A daily row for the night that ended on ``morning``; bed "HH:MM" before midnight is the evening before."""
    bed_day = morning - timedelta(days=1) if bed >= "12:00" else morning
    return {"date": morning.isoformat(), "bed": f"{bed_day.isoformat()}T{bed}", "wake": f"{morning.isoformat()}T{wake}",
            "hrv": 60, "sleep_score": 75, "sleep_hours": 7.5, "rhr": 48}


def test_bedtimes_wrap_past_midnight():
    assert sleep.minutes("2026-10-26T23:30") == 330 and sleep.minutes("2026-10-27T00:45") == 405
    assert sleep.clock(330) == "23:30" and sleep.clock(405) == "00:45"


def test_late_bedtime_against_your_own_usual_time():
    rows = [night(TODAY - timedelta(days=k), "23:00", "07:00") for k in range(20, 0, -1)]
    rows.append(night(TODAY, "00:30", "08:00"))          # 90 min after the usual 23:00
    assert sleep.late_bed_evenings(rows) == {TODAY - timedelta(days=1)}
    tags = evening_tags(rows, [], [], {}, {"late_bed_minutes": 60}, None, 180)
    assert "late_bed" in tags[TODAY - timedelta(days=1)]


def test_schedule_summary_and_weekend_shift():
    rows = []
    for k in range(27, -1, -1):
        morning = TODAY - timedelta(days=k)
        weekend = morning.weekday() in (5, 6)             # Friday and Saturday nights
        rows.append(night(morning, "00:30" if weekend else "23:00", "08:30" if weekend else "07:00"))
    s = sleep.schedule(rows, TODAY)
    assert s["n"] == 28 and s["usual_bed"] == "23:00" and s["weekend_shift"] == 90
    assert s["nights"][-1]["hours"] == 8.0


def test_weeks_run_monday_to_sunday_and_compare():
    days = [{"date": (TODAY - timedelta(days=k)).isoformat(), "status": "red" if k == 2 else "green"} for k in range(20)]
    acts = [{"date": (TODAY - timedelta(days=k)).isoformat(), "load": 100} for k in (1, 3, 5, 9)]
    flags = {(TODAY - timedelta(days=k)).isoformat(): [{"key": "alcohol", "level": "caution", "text": "Alcohol"}]
             for k in (3, 4)}
    flags[(TODAY - timedelta(days=5)).isoformat()] = [{"key": "pain", "level": "high", "text": "Pain"}]
    weeks = weekly.build(TODAY, days, [], acts, set(), {}, {TODAY - timedelta(days=3)}, flags, 25)
    this, last = weeks[0], weeks[1]
    assert this["start"] == "2026-10-26" and this["partial"] and this["days"] == 2
    assert last["start"] == "2026-10-19" and last["end"] == "2026-10-25" and not last["partial"]
    assert last["load"] == 200 and last["sessions"] == 2 and last["rest_days"] == 5 and last["alcohol"] == 1   # 24 and 22 Oct
    assert last["colours"] == {"green": 6, "amber": 0, "red": 1}
    assert [(f["key"], f["days"], f["date"]) for f in last["flags"]] == \
        [("pain", 1, "2026-10-22"), ("alcohol", 2, "2026-10-23")]   # worst first
