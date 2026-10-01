from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS

from fitapp.events import cache_key, enrich, select
from fitapp.sources.event_lookup import EventLookup

TODAY = date(2026, 10, 1)
KEYWORDS = ["tryouts", "pesca", "disco", "ebucc", "hat"]


def cal(title, start, days=1, all_day=True, role=None, location=""):
    s = TODAY + timedelta(days=start)
    return {"title": title, "start": s, "end": s + timedelta(days=days), "all_day": all_day,
            "role": role, "location": location}


def test_select_matches_keywords_and_skips_past_and_swapped():
    evs = [cal("Pesca Disco", 20, 2), cal("Gurls hat", 40), cal("EBUCC", -10, 3),
           cal("Tempo run", 3), cal("Easy run (swapped)", 5, role="light"), cal("Tryouts", 2, location="Odense")]
    out = select(evs, KEYWORDS, [], TODAY)
    assert [e["title"] for e in out] == ["Tryouts", "Pesca Disco", "Gurls hat"]
    pesca = out[1]
    assert pesca["end"] - pesca["start"] == timedelta(days=1)  # Google all-day end is exclusive
    assert out[0]["calendar_location"] == "Odense"


def test_manual_events_merge_without_duplicates():
    manual = [{"name": "Team Denmark tryouts", "start": TODAY + timedelta(days=2)},
              {"name": "Old hat", "start": TODAY - timedelta(days=30)}]
    out = select([cal("Tryouts", 2)], KEYWORDS, manual, TODAY)
    assert [e["title"] for e in out] == ["Tryouts"]
    out = select([], KEYWORDS, manual, TODAY)
    assert [e["title"] for e in out] == ["Team Denmark tryouts"]


def test_enrich_looks_up_once_and_caches():
    calls = []

    def lookup(title, start, end, location):
        calls.append(title)
        return {"full_name": "Pesca Disco Beach", "latitude": 43.87, "longitude": 10.25, "city": "Viareggio"}

    events = select([cal("Pesca Disco", 20)], KEYWORDS, [], TODAY)
    cache = {}
    now = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)
    first = enrich(events, cache, lookup, (45.46, 9.19), TODAY, now)
    again = enrich(events, cache, lookup, (45.46, 9.19), TODAY, now + timedelta(days=2))
    assert calls == ["Pesca Disco"]
    assert first[0]["lookup_status"] == "found" and again[0]["lookup_status"] == "cached"
    assert 150 < first[0]["distance_km"] < 250 and first[0]["days_until"] == 20
    enrich(events, cache, lookup, None, TODAY, now + timedelta(days=31))   # refreshed monthly
    assert len(calls) == 2
    assert cache_key(events[0]) in cache


def test_enrich_without_api_key_and_with_failures():
    events = select([cal("EBUCC", 50)], KEYWORDS, [], TODAY)
    assert enrich(events, {}, None, None, TODAY)[0]["lookup_status"].startswith("add ANTHROPIC_API_KEY")

    def boom(*a):
        raise TimeoutError
    out = enrich(events, {}, boom, None, TODAY)
    assert out[0]["info"] is None and out[0]["lookup_status"] == "lookup failed: TimeoutError"


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def lookup_with(responses):
    finder = EventLookup(api_key="test")
    fake = FakeMessages(responses)
    finder._client = NS(beta=NS(messages=fake))
    return finder, fake


def test_lookup_resumes_paused_search_and_reads_tool_call():
    paused = NS(stop_reason="pause_turn", content=[NS(type="server_tool_use", name="web_search")])
    done = NS(stop_reason="tool_use", content=[
        NS(type="text", text="Found it."),
        NS(type="tool_use", name="save_event", input={"full_name": "Gurls Hat", "city": "Bologna"})])
    finder, fake = lookup_with([paused, done])
    info = finder.lookup("Gurls hat", date(2026, 11, 10), date(2026, 11, 11), None)
    assert info == {"full_name": "Gurls Hat", "city": "Bologna"}
    first, second = fake.calls
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["tool_choice"] == {"type": "auto"}
    assert "Gurls hat" in first["messages"][0]["content"] and "2026-11-10" in first["messages"][0]["content"]
    assert second["messages"][-1]["role"] == "assistant"   # paused turn sent back to resume


def test_lookup_returns_none_on_refusal_or_no_tool_call():
    finder, _ = lookup_with([NS(stop_reason="refusal", content=[])])
    assert finder.lookup("x", TODAY, TODAY) is None
    finder, _ = lookup_with([NS(stop_reason="end_turn", content=[NS(type="text", text="no idea")])])
    assert finder.lookup("x", TODAY, TODAY) is None


def timed(title, day, hour, minutes, location=""):
    from zoneinfo import ZoneInfo
    s = datetime(2026, 10, day, hour, tzinfo=ZoneInfo("Europe/Copenhagen"))
    return {"title": title, "start": s, "end": s + timedelta(minutes=minutes), "all_day": False,
            "role": None, "location": location}


def test_flights_merge_gmail_duplicates_and_attach_to_events():
    from fitapp.events import attach_flights, flights
    cal_events = [
        timed("Flight to Palma (W6 1327)", 8, 15, 195, "Warsaw WAW"),
        timed("Flight to Palma, Majorca (W6 1327)", 8, 15, 195, "Warsaw WAW"),
        timed("Flight to Warsaw WAW 08:45 (08:45 AM) CPH Copenhagen (D8 5610)", 12, 7, 180, "Palma PMI"),
        timed("Flight to Copenhagen (D8 5610)", 12, 7, 180, "Palma PMI"),
        timed("Flight to Porto (D8 3612)", 15, 7, 210, "Copenhagen CPH"),
        timed("Flight to Rome (AZ 1)", 28, 9, 120),
        timed("Tempo run", 9, 18, 60),
    ]
    fl = flights(cal_events, TODAY)
    assert [(f["code"], f["to"]) for f in fl] == [("W61327", "Palma"), ("D85610", "Copenhagen"),
                                                 ("D83612", "Porto"), ("AZ1", "Rome")]
    evs = [{"title": "Pesa disc", "start": "2026-10-08", "end": "2026-10-12"},
           {"title": "EBUCC", "start": "2026-10-15", "end": "2026-10-18"}]
    evs, other = attach_flights(evs, fl)
    assert [f["code"] for f in evs[0]["flights"]] == ["W61327", "D85610"]
    assert [f["code"] for f in evs[1]["flights"]] == ["D83612"]
    assert [f["code"] for f in other] == ["AZ1"]


def test_select_matches_pesa_disc_title():
    from fitapp.config import load_config
    kw = load_config()["events"]["keywords"]
    out = select([cal("Pesa disc - Spain frisbee", 7, 5), cal("Gurls Hat - frisbee", 23, 2), cal("Tempo run", 3)],
                 kw, [], TODAY)
    assert [e["title"] for e in out] == ["Pesa disc - Spain frisbee", "Gurls Hat - frisbee"]


def test_gemini_reply_parsing_and_request(monkeypatch):
    from fitapp.sources import gemini_lookup as gl
    reply = '```json\n{"full_name": "Copa Pescadisco", "city": "Port d\'Alcudia", "country": "Spain", ' \
            '"venue": null, "latitude": 39.84, "longitude": 3.13, "surface": "beach", "division": "mixed", ' \
            '"website": "javascript:alert(1)", "summary": "Beach tournament.", "confidence": "high"}\n```'
    parsed = gl.parse_reply(reply)
    assert parsed["full_name"] == "Copa Pescadisco" and parsed["surface"] == "beach"
    assert parsed["website"] is None          # only http(s) links survive
    assert gl.parse_reply("I could not find it") is None

    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": reply}]}}]}

    def fake_post(url, json, timeout, headers):
        sent.update(url=url, body=json, headers=headers)
        return Resp()

    monkeypatch.setattr(gl.requests, "post", fake_post)
    info = gl.GeminiLookup(api_key="k").lookup("Pesa disc", date(2026, 10, 8), date(2026, 10, 12), None)
    assert info["city"] == "Port d'Alcudia"
    assert "gemini-2.5-flash:generateContent" in sent["url"]
    assert sent["body"]["tools"] == [{"google_search": {}}]
    assert sent["headers"]["x-goog-api-key"] == "k"
    assert "Pesa disc" in sent["body"]["contents"][0]["parts"][0]["text"]


def test_gemini_http_error_raises(monkeypatch):
    import pytest
    from fitapp.sources import gemini_lookup as gl

    class Resp:
        status_code = 429

        def json(self):
            return {"error": {"message": "Resource has been exhausted"}}

    monkeypatch.setattr(gl.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(gl.GeminiError):
        gl.GeminiLookup(api_key="k").lookup("x", TODAY, TODAY)
