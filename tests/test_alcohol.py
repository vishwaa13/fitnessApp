"""Drinks from Garmin and the recovery tags note, by evening and by month."""

from datetime import date

from fitapp import alcohol
from fitapp.gymlog import parse_drinks, parse_tags_note
from fitapp.sources.garmin import drinks, lifestyle_tags

TODAY = date(2026, 10, 27)


def test_garmin_drinks_by_type_yes_only_and_not_logged():
    logged = {"dailyLogsReport": [{"name": "Alcohol", "logStatus": "YES",
                                   "details": [{"subTypeName": "BEER", "amount": 2}, {"subTypeName": "WINE", "amount": 1},
                                               {"subTypeName": "LIQUOR", "amount": 0}]}]}
    assert drinks(logged) == {"beer": 2, "wine": 1} and lifestyle_tags(logged) == ["alcohol"]
    assert drinks({"dailyLogsReport": [{"name": "Alcohol", "logStatus": "YES", "details": [{"subTypeName": "BEER"}]}]}) == {}
    assert drinks({"dailyLogsReport": [{"name": "Alcohol", "details": [{"subTypeId": 1, "subTypeName": "BEER"}]}]}) is None
    assert drinks({"dailyLogsReport": [{"name": "ALCOHOL", "quantity": 3, "details": []}]}) == {"drinks": 3}


def test_note_amounts_and_tags():
    note = "27/10 3 beers, wine 2, travel\n26/10 alcohol\n25/10 2 glasses of wine and a gin"
    assert parse_drinks(note, TODAY) == {"2026-10-27": {"beer": 3, "wine": 2}, "2026-10-25": {"wine": 2}}
    tags = parse_tags_note(note, TODAY)
    assert tags["2026-10-27"] == ["alcohol", "travel"] and tags["2026-10-26"] == ["alcohol"]


def test_evenings_prefer_garmin_and_months_add_up():
    tags = {date(2026, 10, d): {"alcohol"} for d in (3, 10, 24)} | {date(2026, 9, 26): {"alcohol"}}
    daily = [{"date": "2026-10-03", "drinks": {"beer": 3}}, {"date": "2026-10-10", "drinks": {}}]
    note = {"2026-10-03": {"beer": 9}, "2026-10-24": {"wine": 2}, "2026-09-26": {"beer": 4}}
    ev = alcohol.evenings(daily, tags, note, TODAY)
    assert ev["2026-10-03"]["total"] == 3 and ev["2026-10-03"]["source"] == "garmin"   # Garmin wins
    assert ev["2026-10-10"]["total"] is None and ev["2026-10-24"]["types"] == {"wine": 2}
    assert alcohol.describe(ev["2026-10-03"]) == "3 beers" and alcohol.describe(ev["2026-10-10"]) == "amount not logged"
    oct_, sep = alcohol.months(ev, TODAY)[:2]
    assert (oct_["month"], oct_["evenings"], oct_["drinks"], oct_["unknown"], oct_["partial"]) == ("2026-10", 3, 5, 1, True)
    assert oct_["types"] == {"beer": 3, "wine": 2} and oct_["biggest"] == {"date": "2026-10-03", "total": 3}
    assert oct_["per_evening"] == 2.5 and (sep["evenings"], sep["drinks"], sep["partial"]) == (1, 4, False)
