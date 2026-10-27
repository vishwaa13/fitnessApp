"""Garmin's Personal API client and the hybrid with the unofficial login."""

from datetime import date, timedelta

import pytest

from fitapp.sources import garmin as g
from fitapp.sources.garmin_official import BASE, TOKEN_PATH, KeyRejected, PersonalApi, RateLimited

TODAY = date(2026, 10, 27)
DS = TODAY.isoformat()


class Resp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code, self._body = status, body
        self.text = text if text is not None else ("" if body is None else str(body))
        self.content = b"x" if (body is not None or text) else b""

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    """Answers by path; records the headers it was sent."""

    def __init__(self, routes, token=None):
        self.routes, self.headers, self.gets = routes, [], []
        self.token = token if token is not None else Resp(body={"access_token": "tok", "expires_in": 86400})

    def post(self, url, headers=None, timeout=None):
        assert url == BASE + TOKEN_PATH
        self.headers.append(headers)
        return self.token

    def get(self, url, params=None, headers=None, timeout=None):
        self.headers.append(headers)
        path = url[len(BASE):]
        self.gets.append((path, params))
        route = self.routes.get(path)
        return route(params) if callable(route) else (route if isinstance(route, Resp) else Resp(404))


def api(routes=None, token=None):
    return PersonalApi(key="k3y", session=Session(routes or {}, token), pause=0)


@pytest.mark.parametrize("token", [Resp(body={"access_token": "tok"}), Resp(body={"accessToken": "tok"}),
                                   Resp(body={"data": {"token": "tok"}}), Resp(text="tok"), Resp(body="tok")])
def test_key_is_swapped_for_a_bearer_token(token):
    a = api({"/hrv-service/hrv/" + DS: Resp(body={"hrvSummary": {}})}, token)
    a.connect()
    assert a.session.headers[0]["Authorization"] == "ApiKey k3y"
    a.hrv(DS)
    assert a.session.headers[1]["Authorization"] == "Bearer tok"


def test_rejected_key_and_rate_limit_are_distinct_errors():
    with pytest.raises(KeyRejected):
        api(token=Resp(401, body={"error": "x"})).connect()
    a = api({"/usersummary-service/usersummary/daily": Resp(429)})
    a.connect()
    with pytest.raises(RateLimited):
        a.summary(DS)
    assert a.hrv(DS) is None   # 404: nothing for that day


def test_activities_page_through_and_sleep_is_wrapped():
    page = [{"activityId": i} for i in range(99)]
    a = api({"/activitylist-service/activities/search/activities": lambda p: Resp(body=page if p["start"] == 0 else page[:5]),
             "/sleep-service/sleep/dailySleep": Resp(body={"sleepTimeSeconds": 27000})})
    a.connect()
    assert len(a.activities(TODAY - timedelta(days=30), TODAY)) == 104
    assert a.session.gets[0][1]["startDate"] == (TODAY - timedelta(days=30)).isoformat()
    assert a.sleep(DS) == {"dailySleepDTO": {"sleepTimeSeconds": 27000}}


OFFICIAL_ROUTES = {
    f"/hrv-service/hrv/{DS}": Resp(body={"hrvSummary": {"lastNightAvg": 61, "baseline": {"balancedLow": 54, "balancedUpper": 70}}}),
    "/sleep-service/sleep/dailySleep": Resp(body={"sleepTimeSeconds": 27000, "sleepScores": {"overall": {"value": 81}},
                                                  "sleepStartTimestampLocal": 1761521460000, "sleepEndTimestampLocal": 1761548400000}),
    "/usersummary-service/usersummary/daily": Resp(body={"restingHeartRate": 47}),
    "/activitylist-service/activities/search/activities": Resp(body=[
        {"activityId": 7, "activityName": "Ultimate", "activityType": {"typeKey": "ultimate_disc"},
         "startTimeLocal": f"{DS} 18:00:00", "duration": 5400, "activityTrainingLoad": 160}]),
    "/biometric-service/heartRateZones/v2": Resp(body=[{"sport": "DEFAULT", "maxHeartRateUsed": 191}]),
}


class Login:
    """The unofficial library: readiness and the lifestyle log, plus old-style reads."""

    def __init__(self):
        self.reads = []

    def get_training_readiness(self, ds):
        return [{"score": 33, "level": "LOW", "feedbackShort": "LOW_HRV", "inputContext": "AFTER_WAKEUP_RESET"}]

    def get_lifestyle_logging_data(self, ds):
        return {"dailyLogsReport": [{"name": "Alcohol", "logStatus": "YES", "details": [{"subTypeName": "BEER", "amount": 2}]}]}

    def __getattr__(self, name):
        def read(*args):
            self.reads.append(name)
            return None
        return read


def login_down(self):
    raise RuntimeError("login down")


def source(login=True, routes=OFFICIAL_ROUTES, cache=None, monkeypatch=None):
    src = g.GarminSource(cache if cache is not None else {}, official=api(dict(routes)))
    monkeypatch.setattr(g.GarminSource, "login", (lambda self: setattr(self, "api", Login())) if login else login_down)
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    src.connect()
    return src


def test_official_api_reads_and_login_adds_readiness_and_drinks(monkeypatch):
    src = source(monkeypatch=monkeypatch)
    assert src.status == {"api": "ok", "login": "ok"} and src.can_write
    row = src.daily(TODAY - timedelta(days=1), TODAY)[DS]
    assert (row["hrv"], row["hrv_low"], row["sleep_score"], row["rhr"]) == (61, 54, 81, 47)   # official
    assert row["readiness"] == 33 and row["drinks"] == {"beer": 2}                          # login
    assert row["bed"] == "2025-10-26T23:31"
    assert "get_hrv_data" not in src.api.reads and "get_sleep_data" not in src.api.reads
    acts = src.activities(TODAY - timedelta(days=30), TODAY)
    assert acts["7"]["load"] == 160 and src.max_hr() == 191


def test_login_down_keeps_reading_and_keeps_old_readiness(monkeypatch):
    cache = {"daily": {DS: {"date": DS, "readiness": 70, "drinks": {"wine": 1}, "lifestyle_tags": ["alcohol"],
                            "lifestyle_version": g.LIFESTYLE_VERSION}}}
    src = source(login=False, cache=cache, monkeypatch=monkeypatch)
    assert src.status["api"] == "ok" and src.status["login"].startswith("error") and not src.can_write
    row = src.daily(TODAY - timedelta(days=1), TODAY)[DS]
    assert row["hrv"] == 61 and row["readiness"] == 70 and row["drinks"] == {"wine": 1}
    other = src.cache["daily"][(TODAY - timedelta(days=1)).isoformat()]
    assert "drinks" not in other      # re-read once the login is back


def test_rejected_key_falls_back_to_the_login(monkeypatch):
    routes = dict(OFFICIAL_ROUTES, **{f"/hrv-service/hrv/{DS}": Resp(401)})
    src = source(routes=routes, monkeypatch=monkeypatch)
    src.daily(TODAY, TODAY)
    assert src.status["api"] == "key rejected" and "get_sleep_data" in src.api.reads


def test_no_connection_at_all_raises(monkeypatch):
    src = g.GarminSource({}, official=api(token=Resp(401)))
    monkeypatch.setattr(g.GarminSource, "login", login_down)
    with pytest.raises(RuntimeError):
        src.connect()
    assert src.status["api"] == "key rejected"


@pytest.mark.parametrize("raw", ["k3y", " k3y\n", '"k3y"', "[k3y]", "ApiKey k3y", "ApiKey [k3y]"])
def test_key_pasted_with_the_docs_wrapping_still_works(raw):
    assert PersonalApi(key=raw).key == "k3y"


def test_token_failure_is_logged_with_status_and_message_but_not_the_key(caplog):
    a = api(token=Resp(406, text="Not Acceptable for key k3y"))
    with pytest.raises(RuntimeError, match="HTTP 406"):
        a.connect()
    assert "HTTP 406: Not Acceptable for key <key>" in caplog.text and "k3y" not in caplog.text
    assert "Accept" not in a.session.headers[0]          # the documented request: Authorization only
