"""Small helpers shared by the analysis modules."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Iterable
from datetime import date, datetime, timedelta


def d(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iso(value: date) -> str:
    return value.isoformat()


def daterange(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def has_keyword(text: str | None, keywords: Iterable[str]) -> str | None:
    """Return the first keyword that appears in ``text`` as a whole word."""
    if not text:
        return None
    lowered = text.lower()
    for kw in keywords:
        if re.search(r"(?<![a-z0-9])" + re.escape(str(kw).lower()) + r"(?:e?s)?(?![a-z0-9])", lowered):
            return kw
    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def rnd(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def parse_local(ts: str | None) -> datetime | None:
    """Parse Garmin's '2026-09-27 10:05:00' / ISO local timestamps."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace(" ", "T").replace("Z", "")[:19])
    except ValueError:
        return None
