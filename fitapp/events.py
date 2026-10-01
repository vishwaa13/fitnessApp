"""Upcoming frisbee events: pick them out of the calendar and attach where they are."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .util import d, has_keyword, haversine_km

log = logging.getLogger(__name__)

RELOOKUP_AFTER_DAYS = 30        # details can firm up closer to the date
RETRY_FAILED_AFTER_DAYS = 3


def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def select(calendar_events: list[dict], keywords: list[str], manual: list[dict], today: date) -> list[dict]:
    """Future events from the calendar matching ``keywords``, plus upcoming manual ones."""
    out: dict[tuple, dict] = {}
    for ev in calendar_events:
        if not has_keyword(ev.get("title"), keywords) or ev.get("role"):
            continue
        start = _day(ev["start"])
        end = _day(ev["end"])
        if ev.get("all_day"):
            end -= timedelta(days=1)  # Google's all-day end date is exclusive
        end = max(start, end)
        if end < today:
            continue
        out[(ev["title"].strip().lower(), start)] = {
            "title": ev["title"].strip(), "start": start, "end": end,
            "calendar_location": ev.get("location") or None, "source": "calendar"}
    for m in manual or []:
        start, end = d(m["start"]), d(m.get("end") or m["start"])
        if end < today or any(abs((k[1] - start).days) <= 1 for k in out):
            continue
        out[(m["name"].lower(), start)] = {"title": m["name"], "start": start, "end": end,
                                           "calendar_location": None, "source": "config"}
    return sorted(out.values(), key=lambda e: e["start"])


def cache_key(event: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", event["title"].lower()).strip("-") + "|" + event["start"].isoformat()


def enrich(events: list[dict], cache: dict[str, dict], lookup: Callable[..., dict | None] | None,
           home: tuple[float, float] | None, today: date, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for ev in events:
        key = cache_key(ev)
        cached = cache.get(key)
        age_days = None
        if cached:
            age_days = (now - datetime.fromisoformat(cached["looked_up"])).days
        stale = cached is None or (cached.get("info") and age_days >= RELOOKUP_AFTER_DAYS) or \
            (not cached.get("info") and age_days >= RETRY_FAILED_AFTER_DAYS)
        status = "cached" if cached else "not looked up"
        if stale and lookup is not None:
            try:
                info = lookup(ev["title"], ev["start"], ev["end"], ev.get("calendar_location"))
                cached = {"looked_up": now.isoformat(), "info": info}
                cache[key] = cached
                status = "found" if info else "not found"
            except Exception as exc:  # noqa: BLE001 - keep the old answer if there is one
                log.error("Event lookup failed: %s", type(exc).__name__)
                status = f"lookup failed: {type(exc).__name__}"
        info = (cached or {}).get("info")
        distance = None
        if info and home and info.get("latitude") is not None and info.get("longitude") is not None:
            distance = round(haversine_km(home, (info["latitude"], info["longitude"])))
        out.append({
            "title": ev["title"], "start": ev["start"].isoformat(), "end": ev["end"].isoformat(),
            "days": (ev["end"] - ev["start"]).days + 1,
            "days_until": (ev["start"] - today).days,
            "calendar_location": ev.get("calendar_location"), "source": ev["source"],
            "info": info, "distance_km": distance,
            "lookup_status": status if (cached or lookup) else "add ANTHROPIC_API_KEY to look this up",
            "looked_up": (cached or {}).get("looked_up"),
        })
    return out


# --------------------------------------------------------------------------
# Flights: Gmail adds them to the calendar as "Flight to Porto (D8 3612)".
# --------------------------------------------------------------------------
FLIGHT_RE = re.compile(r"^\s*(?:✈\s*)?flight\b", re.I)
CODE_RE = re.compile(r"\(([A-Z0-9]{2}\s?\d{1,4}[A-Z]?)\)")
DEST_RE = re.compile(r"flight\s+to\s+([^(]+?)\s*(?:\(|$)", re.I)


def flights(calendar_events: list[dict], today: date) -> list[dict]:
    """Upcoming flights, with Gmail's duplicate copies of the same flight merged."""
    best: dict[tuple, dict] = {}
    for ev in calendar_events:
        title = (ev.get("title") or "").strip()
        if ev.get("all_day") or not FLIGHT_RE.search(title) or _day(ev["end"]) < today:
            continue
        codes = CODE_RE.findall(title)
        code = codes[-1].replace(" ", "") if codes else None
        dest = DEST_RE.search(title)
        item = {"title": title, "code": code, "to": dest.group(1).strip() if dest else None,
                "from": ev.get("location") or None,
                "depart": ev["start"].isoformat(), "arrive": ev["end"].isoformat()}
        key = (code or title.lower(), item["depart"])
        if key not in best or len(title) < len(best[key]["title"]):
            best[key] = item
    return sorted(best.values(), key=lambda f: f["depart"])


def attach_flights(events: list[dict], trip_flights: list[dict]) -> tuple[list[dict], list[dict]]:
    """Give each event the flights from 3 days before to 2 days after it; return the rest."""
    used: set[int] = set()
    for ev in events:
        lo = d(ev["start"]) - timedelta(days=3)
        hi = d(ev["end"]) + timedelta(days=2)
        ev["flights"] = []
        for i, f in enumerate(trip_flights):
            if i not in used and lo <= d(f["depart"]) <= hi:
                ev["flights"].append(f)
                used.add(i)
    return events, [f for i, f in enumerate(trip_flights) if i not in used]
