"""Alcohol by evening and by month, from the Food tab, Garmin's lifestyle log and the recovery tags note.

An evening counts when any source says you drank. The amount comes from the
Food tab's Alcohol section when you logged drinks there, else from Garmin
(drinks by type), else from the note ("3 beers"), else it's unknown, which is
still an evening. One source per evening, so drinks logged twice count once.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


PLURAL = {"beer": "beers", "cocktail": "cocktails", "cider": "ciders", "shot": "shots", "spirit": "spirits",
          "wine": "wines", "other": "other drinks"}


def evenings(daily: list[dict], tags: dict[date, set[str]], note: dict[str, dict[str, float]],
             today: date, days: int = 190, logged: dict[str, dict[str, float]] | None = None) -> dict[str, dict[str, Any]]:
    garmin = {r["date"]: r.get("drinks") for r in daily}
    logged = logged or {}
    out = {}
    for day, items in sorted(tags.items()):
        if "alcohol" not in items or not 0 <= (today - day).days <= days:
            continue
        iso = day.isoformat()
        source = next((name for name, src in (("food log", logged), ("garmin", garmin), ("note", note)) if src.get(iso)), None)
        types = {"food log": logged, "garmin": garmin, "note": note}[source][iso] if source else {}
        out[iso] = {"types": {k: round(v, 1) for k, v in sorted(types.items(), key=lambda kv: -kv[1])},
                    "total": round(sum(types.values()), 1) if types else None,
                    "source": source}
    return out


def describe(e: dict | None) -> str | None:
    """"2 beer, 1 wine" or "amount not logged"."""
    if e is None:
        return None
    if not e["types"]:
        return "amount not logged"
    return ", ".join(f"{v:g} {PLURAL.get(k, k) if v != 1 else k}" for k, v in e["types"].items())


def months(by_evening: dict[str, dict], today: date, n: int = 6) -> list[dict[str, Any]]:
    """The last ``n`` calendar months, newest first."""
    out = []
    first = today.replace(day=1)
    for _ in range(n):
        ym = first.strftime("%Y-%m")
        days = {k: v for k, v in by_evening.items() if k.startswith(ym)}
        known = {k: v for k, v in days.items() if v["total"] is not None}
        types: dict[str, float] = {}
        for v in known.values():
            for k, amt in v["types"].items():
                types[k] = round(types.get(k, 0) + amt, 1)
        biggest = max(known.items(), key=lambda kv: kv[1]["total"], default=None)
        drinks = round(sum(v["total"] for v in known.values()), 1)
        out.append({"month": ym, "evenings": len(days), "drinks": drinks, "unknown": len(days) - len(known),
                    "per_evening": round(drinks / len(known), 1) if known else None,
                    "types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
                    "biggest": {"date": biggest[0], "total": biggest[1]["total"]} if biggest else None,
                    "dates": sorted(days), "partial": ym == today.strftime("%Y-%m")})
        first = (first - timedelta(days=1)).replace(day=1)
    return out
