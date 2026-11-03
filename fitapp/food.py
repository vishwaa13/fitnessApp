"""Food logging settings for the dashboard.

The log itself never passes through the pipeline: the site encrypts it with the
dashboard passphrase and saves it to GitHub (``store`` below). The pipeline only
publishes the meal options (and which of breakfast, lunch, dinner, snacks and
misc each belongs to), the daily targets and where the log lives, all inside
the encrypted data.
"""

from __future__ import annotations

import re
from typing import Any

SLOTS = ("breakfast", "lunch", "dinner", "snacks", "misc")


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


def settings(cfg: dict) -> dict[str, Any]:
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
    store = food.get("store") or {}
    return {
        "meals": meals,
        "targets": {"kcal": _range(targets.get("kcal")), "protein": _range(targets.get("protein"))},
        "store": {"repo": str(store.get("repo") or ""), "branch": str(store.get("branch") or "food-log"),
                  "path": str(store.get("path") or "food.enc.json")},
    }
