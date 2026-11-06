"""Food logging settings for the dashboard.

The log lives in a Google Sheet behind the Apps Script web app in
``apps-script/food-log.gs``; the site reads and writes it directly. The pipeline
publishes the meal options (and which of breakfast, lunch, dinner, snacks and
misc each belongs to), the daily targets, and the web app's URL from the
FOOD_SHEET_URL secret, which only ever goes into the encrypted data.
"""

from __future__ import annotations

import re
from typing import Any

import requests

SLOTS = ("breakfast", "lunch", "dinner", "snacks", "alcohol", "misc")

# A drink's name -> the type the alcohol stats count it as (Garmin's beer/wine/spirit, plus cocktail and cider).
_DRINK_TYPES = [
    ("beer", r"beer|\bøl\b|lager|pils|\bale\b|\bipa\b|stout|porter|weiss|weizen"),
    ("cider", r"cider"),
    ("wine", r"wine|\bvin\b|ros[eé]|prosecco|champagne|cava|cremant|crémant|sangria"),
    ("cocktail", r"cocktail|mojito|margarita|spritz|negroni|martini|daiquiri|g&t|gin ?(?:and|&|og) ?tonic|long ?island|mule"),
    ("spirit", r"spirit|\bshots?\b|vodka|\bgin\b|whisk(?:e)?y|\brum\b|tequila|snaps|akvavit|jäger|jager|liqueur|brandy|cognac"),
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _range(value: Any) -> list[float] | None:
    """A target as [low, high]; a single number means exactly that."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo, hi = _num(value[0]), _num(value[1])
        return sorted([lo, hi]) if lo is not None and hi is not None else None
    n = _num(value)
    return [n, n] if n is not None else None


def check_sheet(url: str, get=requests.get) -> tuple[str, dict[str, int], dict[str, Any]]:
    """Read the food sheet's log through its web app: ("ok", counts, log), or why not.

    Only counts go into the (public) run log, never the URL: it is the key to the sheet."""
    try:
        resp = get(url, timeout=30)
    except requests.RequestException as exc:
        return f"error: {type(exc).__name__}", {}, {}
    try:
        body = resp.json()
    except ValueError:
        return "error: not JSON (deploy the script as a Web app with Who has access: Anyone)", {}, {}
    if not isinstance(body, dict) or not body.get("ok"):
        why = body.get("error") if isinstance(body, dict) else None
        return "error: " + str(why or f"HTTP {getattr(resp, 'status_code', '?')}")[:80], {}, {}
    live = lambda tab: sum(1 for x in (body.get(tab) or {}).values() if isinstance(x, dict) and not x.get("deleted"))  # noqa: E731
    return "ok", {"entries": live("entries"), "options": live("meals")}, body


def drink_type(name: str) -> str:
    low = (name or "").lower()
    return next((t for t, pattern in _DRINK_TYPES if re.search(pattern, low)), "other")


def drinks_by_day(log: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Drinks logged under Alcohol on the Food tab, by day and type: {"2026-11-06": {"beer": 3}}.

    The site saves one row per drink; a row with a "drinks" count counts that many."""
    out: dict[str, dict[str, float]] = {}
    for e in (log.get("entries") or {}).values():
        if not isinstance(e, dict) or e.get("deleted") or e.get("slot") != "alcohol" or not e.get("date"):
            continue
        n = _num(e.get("drinks")) or 1
        kind = drink_type(str(e.get("name") or ""))
        day = out.setdefault(str(e["date"])[:10], {})
        day[kind] = day.get(kind, 0) + n
    return out


def settings(cfg: dict, url: str | None = None) -> dict[str, Any]:
    food = cfg.get("food") or {}
    meals, seen = [], set()
    for m in food.get("meals") or []:
        name = str((m or {}).get("name") or "").strip()
        kcal = _num((m or {}).get("kcal"))
        if not name or kcal is None:
            continue
        mid = "d-" + _slug(name)
        if mid in seen:
            continue
        seen.add(mid)
        slots = [x for x in (m.get("slots") or []) if x in SLOTS] or ["misc"]
        meals.append({"id": mid, "name": name, "kcal": kcal, "protein": _num(m.get("protein")) or 0, "slots": slots})
    targets = food.get("targets") or {}
    url = (url or "").strip()
    return {
        "meals": meals,
        "targets": {"kcal": _range(targets.get("kcal")), "protein": _range(targets.get("protein"))},
        "store": {"url": url if url.startswith("https://script.google.com/") else ""},
    }
