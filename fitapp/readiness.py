"""Morning readiness verdict and the calendar swap plan.

The verdict combines Garmin training readiness, last night's HRV against your
baseline band, sleep and resting HR. If the day comes out red, today's hard
calendar sessions are swapped for a light version and the hard session moves
to the next day that has no other hard session and isn't the eve of a
tournament. Tomorrow's run re-checks, so a session that lands on another red
day simply moves again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .util import has_keyword, mean

LEVEL_RANK = {"green": 0, "amber": 1, "red": 2}


def _signal(key: str, label: str, level: str, value: Any, display: str, detail: str) -> dict:
    return {"key": key, "label": label, "level": level, "value": value, "display": display, "detail": detail}


def assess(today: dict | None, previous: list[dict], th: dict) -> dict[str, Any]:
    """Score this morning. ``previous`` = earlier daily rows, oldest first."""
    signals: list[dict] = []
    if not today:
        return {"status": "unknown", "signals": [], "summary": "No data for this morning yet. Sync your watch."}

    score = today.get("readiness")
    if score is not None:
        lvl = "red" if score < th["readiness_red"] else "amber" if score < th["readiness_amber"] else "green"
        level_txt = (today.get("readiness_level") or "").title()
        signals.append(_signal("readiness", "Training readiness", lvl, score,
                               f"{score}" + (f" · {level_txt}" if level_txt else ""),
                               today.get("readiness_feedback") or ""))

    hrv, low, high = today.get("hrv"), today.get("hrv_low"), today.get("hrv_high")
    if hrv is not None:
        status = (today.get("hrv_status") or "").upper()
        if low is not None and hrv < low:
            lvl = "red" if status in {"UNBALANCED", "LOW", "POOR"} else "amber"
            detail = f"Below your baseline band ({low:.0f}–{high:.0f} ms)" if high else "Below your baseline"
        elif status in {"LOW", "POOR"}:
            lvl, detail = "amber", f"Weekly HRV status is {status.lower()}"
        else:
            lvl = "green"
            detail = f"Inside your baseline band ({low:.0f}–{high:.0f} ms)" if low and high else "Normal"
        signals.append(_signal("hrv", "HRV last night", lvl, hrv, f"{hrv:.0f} ms", detail))

    sleep_score, hours = today.get("sleep_score"), today.get("sleep_hours")
    if sleep_score is not None or hours is not None:
        red = (sleep_score is not None and sleep_score < th["sleep_score_red"]) or (hours is not None and hours < th["sleep_hours_red"])
        amber = (sleep_score is not None and sleep_score < th["sleep_score_amber"]) or (hours is not None and hours < th["sleep_hours_amber"])
        lvl = "red" if red else "amber" if amber else "green"
        parts = []
        if sleep_score is not None:
            parts.append(f"{sleep_score}")
        if hours is not None:
            parts.append(f"{int(hours)}h{round((hours % 1) * 60):02d}")
        signals.append(_signal("sleep", "Sleep score · time", lvl, sleep_score, " · ".join(parts), ""))

    rhr = today.get("rhr")
    base = mean(r.get("rhr") for r in previous[-7:])
    if rhr is not None and base is not None:
        diff = rhr - base
        lvl = "red" if diff >= th["rhr_red_bpm"] else "amber" if diff >= th["rhr_amber_bpm"] else "green"
        signals.append(_signal("rhr", "Resting HR", lvl, rhr, f"{rhr:.0f} bpm",
                               f"{diff:+.0f} vs 7-day average"))

    if not signals:
        return {"status": "unknown", "signals": [], "summary": "No data for this morning yet. Sync your watch."}

    reds = sum(s["level"] == "red" for s in signals)
    ambers = sum(s["level"] == "amber" for s in signals)
    readiness_red = any(s["key"] == "readiness" and s["level"] == "red" for s in signals)
    if readiness_red or reds >= 2 or (reds == 1 and ambers >= 1):
        status = "red"
        summary = "Recovery is low. Keep today easy and save the hard work for a green day."
    elif reds == 1 or ambers >= 2:
        status = "amber"
        summary = "Mixed signals. Train, but cap the intensity and skip anything maximal."
    else:
        status = "green"
        summary = "Good to go. Hard training is fine today."
    return {"status": status, "signals": signals, "summary": summary}


# --------------------------------------------------------------------------
# Calendar swap planning (pure: works on normalised event dicts)
#   event = {"id", "title", "start": datetime|date, "end": datetime|date,
#            "all_day": bool, "role": None|"moved"|"light"}
# --------------------------------------------------------------------------

def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def classify(event: dict, cfg: dict) -> str:
    title = event.get("title") or ""
    if has_keyword(title, cfg["protected_keywords"]):
        return "protected"
    if event.get("role") == "light":
        return "light"
    if has_keyword(title, cfg["hard_keywords"]):
        return "hard"
    return "other"


def light_version(title: str, cfg: dict) -> dict:
    for option in cfg.get("light_versions", []):
        if has_keyword(title, option.get("match", [])):
            return {"title": option["title"], "description": option.get("description", "")}
    return dict(cfg["default_light"])


def plan_swaps(events: list[dict], status: str, cfg: dict, now: datetime,
               extra_protected_days: set[date] | None = None) -> list[dict]:
    trigger = {"red"} if cfg.get("swap_when", "red") == "red" else {"red", "amber"}
    if status not in trigger:
        return []
    today = now.date()
    by_day: dict[date, list[dict]] = {}
    for ev in events:
        by_day.setdefault(_day(ev["start"]), []).append(ev)
    protected_days = set(extra_protected_days or set())
    for day, evs in by_day.items():
        if any(classify(e, cfg) == "protected" for e in evs):
            protected_days.add(day)

    def is_good(day: date, taken: set[date]) -> bool:
        if day in taken or day in protected_days or (day + timedelta(days=1)) in protected_days:
            return False
        return not any(classify(e, cfg) == "hard" for e in by_day.get(day, []))

    actions: list[dict] = []
    taken: set[date] = set()
    for ev in sorted(by_day.get(today, []), key=lambda e: str(e["start"])):
        # A session moved here earlier is fair game again: if today is red too, it moves on.
        if classify(ev, cfg) != "hard":
            continue
        start = ev["start"]
        if isinstance(start, datetime) and start.replace(tzinfo=None) <= now.replace(tzinfo=None):
            continue  # already started or done
        target = None
        for k in range(1, int(cfg.get("look_ahead_days", 7)) + 1):
            candidate = today + timedelta(days=k)
            if is_good(candidate, taken):
                target = candidate
                break
        if target:
            taken.add(target)
        light = light_version(ev["title"], cfg)
        actions.append({
            "type": "swap",
            "event_id": ev["id"],
            "title": ev["title"],
            "start": ev["start"],
            "end": ev["end"],
            "all_day": ev.get("all_day", False),
            "moved_to": target,
            "light": light,
        })
    return actions
