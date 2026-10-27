"""End-to-end: demo build, and a real run against fake Garmin / Keep / Calendar."""

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fitapp import cache as cache_mod
from fitapp import demo, pipeline
from fitapp.config import load_config
from fitapp.crypto import decrypt_json

TZ = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 10, 1, 7, 30, tzinfo=TZ)
TODAY = NOW.date()


def test_demo_builds_every_section():
    data = demo.build(load_config(), NOW)
    assert data["demo"] is True
    assert data["today"]["status"] == "red" and data["today"]["actions"]
    assert {t["name"].split()[0] for t in data["tournaments"]} >= {"Burla", "Pesca"}
    assert data["overload"]["templates"] and data["recovery"]["effects"]
    assert data["injury"]["history"][0]["label"] == "Glute strain"
    json.dumps(data)  # fully serialisable


class FakeGarmin:
    instances = []

    def __init__(self, cache):
        self.cache, self.api, self.calls = cache, None, 0
        self.uploaded, self.scheduled, self.descriptions = [], [], {}
        FakeGarmin.instances.append(self)

    def login(self):
        self.api = object()

    def save_tokens(self):
        self.cache["garmin_tokens"] = "tok"

    def activities(self, since):
        store = self.cache.setdefault("activities", {})
        store["1"] = {"id": 1, "name": "Strength", "type": "strength_training", "date": "2026-09-29",
                      "start": "2026-09-29T07:00", "end": "2026-09-29T08:00", "duration_min": 60,
                      "avg_hr": 110, "max_hr": 150, "load": 50, "lat": None, "lon": None}
        return store

    def daily(self, since, today):
        store = self.cache.setdefault("daily", {})
        for k in range(30):
            day = today - timedelta(days=k)
            store[day.isoformat()] = {"date": day.isoformat(), "hrv": 62, "hrv_low": 54, "hrv_high": 70,
                                      "hrv_status": "BALANCED", "sleep_score": 80, "sleep_hours": 7.5,
                                      "rhr": 48, "readiness": 70, "lifestyle_tags": []}
        store[today.isoformat()].update(readiness=20, hrv=45, hrv_status="UNBALANCED")
        return store

    def max_hr(self):
        return 190

    def replace_workout(self, workout):
        self.uploaded.append(workout["workoutName"])
        return 1000 + len(self.uploaded)

    def schedule(self, workout_id, day):
        self.scheduled.append((workout_id, day))

    def activity_description(self, activity_id):
        return None

    def set_description(self, activity_id, text):
        self.descriptions[activity_id] = text


class FakeKeep:
    configured = True

    def notes_text(self, title):
        if title == "gym logs":
            return "29/09 Lower A\nSquat 3x8 100\nRDL 3x10 60\n"
        return "30/09 alcohol"


class FakeCalendar:
    applied = []

    def __init__(self, calendar_id, tz):
        self.configured = True

    def events(self, start, days):
        s = datetime.combine(start, datetime.min.time(), TZ).replace(hour=18)
        return [{"id": "e1", "title": "Tempo run", "start": s, "end": s + timedelta(hours=1), "all_day": False, "role": None},
                {"id": "e2", "title": "Gym lower", "start": s + timedelta(days=2), "end": s + timedelta(days=2, hours=1),
                 "all_day": False, "role": None}]

    def apply_swap(self, action, reason):
        FakeCalendar.applied.append((action["event_id"], action["moved_to"]))


@pytest.fixture
def fakes(monkeypatch):
    FakeGarmin.instances.clear()
    FakeCalendar.applied.clear()
    monkeypatch.setattr("fitapp.sources.garmin.GarminSource", FakeGarmin)
    monkeypatch.setattr("fitapp.sources.keep.KeepSource", FakeKeep)
    monkeypatch.setattr("fitapp.sources.gcal.CalendarSource", FakeCalendar)
    monkeypatch.setenv("DASHBOARD_PASSPHRASE", "test pass")


def test_run_publishes_encrypted_data_and_acts_once_per_day(tmp_path, fakes):
    cfg = load_config()
    cfg["tournaments"]["manual"] = []  # independent of whatever events config.yml lists
    out, cache = tmp_path / "site", tmp_path / "state.enc.json"
    data = pipeline.run(cfg, out, cache, now=NOW)

    assert not (out / "data.json").exists()
    published = decrypt_json(json.loads((out / "data.enc.json").read_text()), "test pass")
    assert published["today"]["status"] == "red"
    assert published["today"]["actions"][0]["status"] == "applied"
    assert FakeCalendar.applied == [("e1", TODAY + timedelta(days=1))]

    g = FakeGarmin.instances[-1]
    assert g.uploaded == ["FA · Lower A"]
    assert g.scheduled == [(1001, TODAY + timedelta(days=2))]   # next "gym" event
    assert g.descriptions[1].startswith("Squat: 100×8")
    assert data["overload"]["templates"][0]["garmin_status"] == "uploaded"

    state = cache_mod.load(cache, "test pass")
    assert state["garmin_tokens"] == "tok" and state["swaps"][TODAY.isoformat()]

    # Second run the same morning: nothing is moved, uploaded or rewritten again.
    pipeline.run(cfg, out, cache, now=NOW + timedelta(hours=1))
    g2 = FakeGarmin.instances[-1]
    assert len(FakeCalendar.applied) == 1
    assert g2.uploaded == [] and g2.scheduled == [] and g2.descriptions == {}


def test_suggest_mode_and_dry_run_leave_calendar_alone(tmp_path, fakes):
    cfg = load_config()
    cfg["readiness"]["mode"] = "suggest"
    data = pipeline.run(cfg, tmp_path / "a", tmp_path / "c1.json", now=NOW)
    assert data["today"]["actions"][0]["status"] == "suggested"
    cfg["readiness"]["mode"] = "apply"
    pipeline.run(cfg, tmp_path / "b", tmp_path / "c2.json", now=NOW, dry_run=True)
    assert FakeCalendar.applied == []
    assert FakeGarmin.instances[-1].uploaded == []


def test_refuses_to_publish_without_passphrase(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_PASSPHRASE", raising=False)
    with pytest.raises(SystemExit):
        pipeline.run(load_config(), tmp_path, tmp_path / "c.json", now=NOW)


def test_garmin_normalisers():
    from fitapp.sources.garmin import lifestyle_tags, normalize_activity, normalize_day
    a = normalize_activity({"activityId": 5, "activityName": "Burla game 2", "startTimeLocal": "2026-06-20 09:00:00",
                            "activityType": {"typeKey": "ultimate_disc"}, "duration": 4500, "elapsedDuration": 4800,
                            "distance": 6500.0, "averageHR": 160, "maxHR": 188, "activityTrainingLoad": 155.2,
                            "locationName": "Viareggio", "startLatitude": 43.87, "startLongitude": 10.25})
    assert a["date"] == "2026-06-20" and a["end"] == "2026-06-20T10:20" and a["duration_min"] == 75
    row = normalize_day(date(2026, 10, 1),
                        {"hrvSummary": {"lastNightAvg": 48, "weeklyAvg": 58, "status": "UNBALANCED",
                                        "baseline": {"balancedLow": 54, "balancedUpper": 70}}},
                        {"dailySleepDTO": {"sleepTimeSeconds": 22500, "sleepScores": {"overall": {"value": 61}}}},
                        [{"score": 31, "level": "LOW", "feedbackShort": "LOW_HRV", "inputContext": "AFTER_WAKEUP_RESET"}],
                        {"restingHeartRate": 52}, None)
    assert (row["hrv"], row["hrv_low"], row["sleep_score"], row["sleep_hours"], row["readiness"], row["rhr"]) == (48, 54, 61, 6.25, 31, 52)
    assert row["readiness_feedback"] == "Low HRV"
    assert lifestyle_tags({"dailyLogs": [{"name": "Alcohol", "status": "YES"}, {"name": "Caffeine", "status": "NO"}]}) == ["alcohol"]
    # Other plausible shapes: "logStatus", and amounts of beer/wine in sub-entries.
    assert lifestyle_tags({"dailyLogsReport": [{"name": "Alcohol", "logStatus": "YES",
                                                "details": [{"subTypeName": "BEER", "amount": 2}]}]}) == ["alcohol"]
    assert lifestyle_tags({"logs": [{"subTypeName": "WINE", "amount": 1}]}) == ["alcohol"]
    assert lifestyle_tags({"logs": [{"name": "Alcohol", "logStatus": "NO", "amount": 0}]}) == []


def test_calendar_errors_are_explained_without_the_calendar_id():
    import httplib2
    from googleapiclient.errors import HttpError

    from fitapp.sources.gcal import describe_error

    def err(status, reason, message):
        body = json.dumps({"error": {"code": status, "message": message,
                                     "errors": [{"reason": reason, "message": message}]}}).encode()
        return HttpError(httplib2.Response({"status": status}), body)

    nf = describe_error(err(404, "notFound", "Not Found: someone@gmail.com"))
    assert nf.startswith("HTTP 404 notFound") and "share the calendar" in nf and "@" not in nf
    off = describe_error(err(403, "accessNotConfigured", "Google Calendar API has not been used in project 12"))
    assert "turn on the Google Calendar API" in off
    assert "not valid JSON" in describe_error(json.JSONDecodeError("x", "{", 0))


def test_garmin_rereads_stored_lifestyle_logs_once(monkeypatch, caplog):
    from fitapp.sources import garmin as g
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    today = date(2026, 10, 24)
    old = (today - timedelta(days=20)).isoformat()

    class Api:
        lifestyle_calls = []

        def get_lifestyle_logging_data(self, ds):
            self.lifestyle_calls.append(ds)
            return {"dailyLogsReport": [{"name": "Alcohol", "logStatus": "YES" if ds == old else "NO"}]}

        def __getattr__(self, name):
            return lambda *a: None

    cache = {"daily": {old: {"date": old, "hrv": 50, "sleep_score": 70, "lifestyle_tags": []}},
             "daily_fetched": {old: "2026-10-05T06:00:00"}}
    src = g.GarminSource(cache)
    src.api = Api()
    store = src.daily(today - timedelta(days=30), today)
    assert store[old]["lifestyle_tags"] == ["alcohol"] and cache["lifestyle_version"] == g.LIFESTYLE_VERSION
    n = len(Api.lifestyle_calls)
    src.daily(today - timedelta(days=30), today)
    assert old not in Api.lifestyle_calls[n:]          # only once



def test_strip_days_explain_their_colour():
    data = demo.build(load_config(), NOW)
    strip = data["today"]["strip"]
    assert len(strip) == 14 and strip[-1]["date"] == NOW.date().isoformat()
    for s in strip:
        assert {"summary", "signals", "activities", "gym", "notes", "before", "load"} <= set(s)
        assert s["before"]["date"] < s["date"]
    known = [s for s in strip if s["status"] != "unknown"]
    assert known and all(s["signals"] for s in known)
    assert any(s["activities"] for s in strip) and any(s["gym"] for s in strip)
    assert any(s["before"]["tags"] for s in strip)



def test_month_calendar_and_bedtimes_in_the_published_data():
    data = demo.build(load_config(), NOW)
    cal = data["calendar"]
    assert len(cal["days"]) == pipeline.CALENDAR_DAYS and cal["days"][-14:] == data["today"]["strip"]
    assert len(cal["weeks"]) == 8 and cal["weeks"][0]["start"] <= NOW.date().isoformat()
    bed = data["recovery"]["bedtime"]
    assert bed["n"] == 28 and bed["usual_bed"] and bed["nights"][0]["bed_m"] < bed["nights"][0]["wake_m"]
    assert "late_bed" in data["recovery"]["tag_labels"]
    assert "flags_by_day" not in data["injury"]          # used for the weeks, not published


def test_garmin_backfills_bedtimes_for_stored_days(monkeypatch):
    from fitapp.sources import garmin as g
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    today = date(2026, 10, 27)
    old = (today - timedelta(days=30)).isoformat()

    class Api:
        def get_sleep_data(self, ds):
            return {"dailySleepDTO": {"sleepStartTimestampLocal": 1761521460000, "sleepEndTimestampLocal": 1761548400000}}

        def __getattr__(self, name):
            return lambda *a: None

    cache = {"daily": {old: {"date": old, "hrv": 50, "sleep_score": 70}}, "daily_fetched": {old: "2026-09-28T06:00:00"},
             "lifestyle_version": g.LIFESTYLE_VERSION}
    src = g.GarminSource(cache)
    src.api = Api()
    store = src.daily(today - timedelta(days=40), today)
    assert (store[old]["bed"], store[old]["wake"]) == ("2025-10-26T23:31", "2025-10-27T07:00")


def test_lifestyle_diagnostic_speaks_only_when_something_was_logged():
    from fitapp.sources.garmin import answered, payload_keys
    assert not answered({"dailyLogsReport": [{"name": "Alcohol"}], "completionStats": {"completedTracking": 0}})
    logged = {"dailyLogsReport": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "Alcohol", "loggedValue": 2}],
              "completionStats": {"completedTracking": 1}}
    assert answered(logged) and "dailyLogsReport.loggedValue" in payload_keys(logged)   # past the first three
