"""Fetch → analyse → act → publish."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import cache as cache_mod
from . import injury, overload, readiness, recovery, tournaments
from .crypto import encrypt_json
from .gymlog import Session, parse_gym_log, parse_tags_note
from .util import d, has_keyword

log = logging.getLogger(__name__)


def detect_home(activities: list[dict], cfg: dict) -> tuple[float, float] | None:
    home = (cfg.get("athlete") or {}).get("home")
    if home and home.get("lat") is not None:
        return (float(home["lat"]), float(home["lon"]))
    pts = Counter((round(a["lat"], 1), round(a["lon"], 1)) for a in activities
                  if a.get("lat") is not None and a.get("lon") is not None)
    return pts.most_common(1)[0][0] if pts else None


def resolve_max_hr(cfg: dict, activities: list[dict], profile_max: float | None = None) -> float | None:
    configured = (cfg.get("athlete") or {}).get("max_hr")
    if configured:
        return float(configured)
    observed = max((a.get("max_hr") or 0 for a in activities), default=0)
    return float(max(observed, profile_max or 0)) or None


def protected_days(cfg: dict, upcoming_events: list[dict] | None = None) -> set[date]:
    """Days of upcoming events (config and calendar): never swap a hard session onto them."""
    ranges = [(m["start"], m.get("end") or m["start"]) for m in cfg["tournaments"].get("manual") or []]
    ranges += [(e["start"], e["end"]) for e in upcoming_events or []]
    days = set()
    for start, end in ranges:
        day = d(start)
        while day <= d(end):
            days.add(day)
            day += timedelta(days=1)
    return days


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, set):
        return sorted(_jsonable(v) for v in value)
    return value


def analyze(*, activities: list[dict], daily: list[dict], gym_text: str | None,
            manual_tags: dict[str, list[str]], cfg: dict, now: datetime,
            calendar_events: list[dict] | None, sources: dict[str, str],
            profile_max_hr: float | None = None,
            upcoming_events: list[dict] | None = None) -> dict[str, Any]:
    today = now.date()
    activities = sorted((dict(a) for a in activities), key=lambda a: a["start"])
    daily = sorted(daily, key=lambda r: r["date"])
    home = detect_home(activities, cfg)
    max_hr = resolve_max_hr(cfg, activities, profile_max_hr)

    # Fill in a load for activities Garmin didn't score, so load totals add up.
    from .sources.garmin import estimate_load
    for a in activities:
        if a.get("load") is None:
            est = estimate_load(a.get("duration_min") or 0, a.get("avg_hr"), max_hr)
            if est is not None:
                a["load"], a["load_estimated"] = round(est), True

    tourneys = tournaments.build(activities, daily, cfg["tournaments"], home, max_hr, today)

    ov = cfg["overload"]
    sessions: list[Session] = parse_gym_log(gym_text or "", today, ov["date_order"], ov["weight_unit"]) if gym_text else []
    plan = overload.build_plan(sessions, ov, today)
    plan["unparsed"] = [{"date": s.date.isoformat(), "lines": s.unparsed} for s in sessions[-10:] if s.unparsed]
    plan["recent_sessions"] = [s.to_dict() for s in sessions[-8:]][::-1]

    tags = recovery.evening_tags(daily, activities, tourneys, manual_tags, cfg["recovery"], home,
                                 cfg["injury"]["high_day_load"])
    rec = recovery.analyse(daily, tags, int(cfg["recovery"]["window_days"]), today)

    inj = injury.build(activities, daily, cfg["injury"], today)

    by_date = {r["date"]: r for r in daily}
    today_row = by_date.get(today.isoformat())
    previous = [r for r in daily if r["date"] < today.isoformat()]
    verdict = readiness.assess(today_row, previous, cfg["readiness"]["thresholds"])
    strip = []
    for k in range(13, -1, -1):
        day = (today - timedelta(days=k)).isoformat()
        v = readiness.assess(by_date.get(day), [r for r in daily if r["date"] < day], cfg["readiness"]["thresholds"])
        strip.append({"date": day, "status": v["status"]})

    protected = protected_days(cfg, upcoming_events)
    swaps: list[dict] = []
    week: list[dict] = []
    if calendar_events is not None:
        swaps = readiness.plan_swaps(calendar_events, verdict["status"], cfg["readiness"], now, protected)
        for ev in sorted(calendar_events, key=lambda e: str(e["start"])):
            kind = readiness.classify(ev, cfg["readiness"])
            if kind in {"hard", "protected", "light"} or ev.get("role"):
                week.append({"title": ev["title"], "start": ev["start"], "all_day": ev.get("all_day", False),
                             "kind": kind, "role": ev.get("role")})
    for a in swaps:
        a["status"] = "planned"

    recent = [{k: a.get(k) for k in ("id", "name", "type", "date", "start", "duration_min", "distance_km",
                                     "avg_hr", "max_hr", "load", "aerobic_te", "anaerobic_te")}
              for a in activities if d(a["date"]) >= today - timedelta(days=28)][::-1]

    return _jsonable({
        "generated_at": now.isoformat(timespec="minutes"),
        "today_date": today.isoformat(),
        "timezone": cfg["timezone"],
        "sources": sources,
        "athlete": {"max_hr": max_hr, "home_known": home is not None},
        "today": {**verdict, "date": today.isoformat(), "row": today_row, "strip": strip,
                  "mode": cfg["readiness"]["mode"], "calendar": calendar_events is not None,
                  "actions": swaps, "week": week},
        "tournaments": tourneys,
        "overload": plan,
        "recovery": rec,
        "injury": inj,
        "recent_activities": recent,
        "events": upcoming_events or [],
    })


# --------------------------------------------------------------------------
# Real run
# --------------------------------------------------------------------------

def _write_outputs(data: dict, out_dir: Path, passphrase: str | None, plain_path: Path | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if passphrase:
        (out_dir / "data.enc.json").write_text(json.dumps(encrypt_json(data, passphrase)))
    if plain_path:
        plain_path.parent.mkdir(parents=True, exist_ok=True)
        plain_path.write_text(json.dumps(data, indent=1))


def run(cfg: dict, out_dir: Path, cache_path: Path, *, dry_run: bool = False,
        plain_path: Path | None = None, now: datetime | None = None) -> dict:
    from .sources.garmin import GarminSource
    from .sources.gcal import CalendarSource
    from .sources.keep import KeepSource

    tz = ZoneInfo(cfg["timezone"])
    now = now or datetime.now(tz)
    today = now.date()
    passphrase = os.getenv("DASHBOARD_PASSPHRASE")
    if not passphrase and not plain_path:
        raise SystemExit("DASHBOARD_PASSPHRASE is not set. Refusing to publish unencrypted health data.")
    state = cache_mod.load(cache_path, passphrase) if passphrase else {}
    sources: dict[str, str] = {}

    # --- Garmin -----------------------------------------------------------
    garmin = GarminSource(state)
    since = today - timedelta(days=int(cfg["history_days"]))
    profile_max = None
    try:
        garmin.login()
        garmin.activities(since - timedelta(days=60))  # extra margin for chronic load
        garmin.daily(since, today)
        profile_max = garmin.max_hr()
        sources["garmin"] = "ok"
    except Exception as exc:  # noqa: BLE001
        log.error("Garmin failed: %s", type(exc).__name__)
        sources["garmin"] = f"error: {type(exc).__name__}"
        if not state.get("activities"):
            garmin = None
    activities = list((state.get("activities") or {}).values())
    daily = list((state.get("daily") or {}).values())

    # --- Keep ---------------------------------------------------------------
    gym_text, manual_tags = None, {}
    keep = KeepSource()
    if keep.configured:
        try:
            gym_text = keep.notes_text(cfg["overload"]["keep_note_title"])
            tags_text = keep.notes_text(cfg["recovery"]["keep_tags_note_title"])
            manual_tags = parse_tags_note(tags_text, today, cfg["overload"]["date_order"]) if tags_text else {}
            sources["keep"] = "ok" if gym_text else "note not found"
        except Exception as exc:  # noqa: BLE001
            log.error("Keep failed: %s", type(exc).__name__)
            sources["keep"] = f"error: {type(exc).__name__}"
    else:
        sources["keep"] = "not configured"

    # --- Calendar -------------------------------------------------------------
    cal = CalendarSource(cfg["readiness"].get("calendar_id"), cfg["timezone"])
    events = None
    if cal.configured:
        try:
            events = cal.events(today, int(cfg["readiness"]["look_ahead_days"]) + 1)
            sources["calendar"] = "ok"
        except Exception as exc:  # noqa: BLE001
            from .sources.gcal import describe_error
            reason = describe_error(exc)
            log.error("Calendar failed: %s", reason)
            sources["calendar"] = f"error: {reason}"
    else:
        sources["calendar"] = "not configured"

    # --- Upcoming events and flights, located with Gemini (or Claude) + web search -
    from .events import attach_flights, enrich, flights, select
    from .sources.event_lookup import EventLookup
    from .sources.gemini_lookup import GeminiLookup

    horizon: list[dict] = []
    if events is not None:
        try:
            horizon = cal.events(today, int(cfg["events"]["look_ahead_days"]))
        except Exception as exc:  # noqa: BLE001
            from .sources.gcal import describe_error
            log.error("Calendar (events) failed: %s", describe_error(exc))
            horizon = events
    chosen = select(horizon, cfg["events"]["keywords"], cfg["tournaments"].get("manual"), today)
    # Free Gemini (GEMINI_API_CODE) first; Claude only if its key is set instead.
    finder = None
    for name, candidate in (("gemini", GeminiLookup(model=cfg["events"].get("gemini_model"))),
                            ("claude", EventLookup())):
        if candidate.configured:
            finder = candidate
            sources["event_lookup"] = name
            break
    upcoming = enrich(chosen, state.setdefault("event_info", {}),
                      finder.lookup if finder else None, detect_home(activities, cfg), today)
    upcoming, other_flights = attach_flights(upcoming, flights(horizon, today))
    log.info("Events: %d upcoming", len(upcoming))

    data = analyze(activities=activities, daily=daily, gym_text=gym_text, manual_tags=manual_tags,
                   cfg=cfg, now=now, calendar_events=events, sources=sources, profile_max_hr=profile_max,
                   upcoming_events=upcoming)
    data["travel"] = other_flights

    # --- Act: calendar swaps ------------------------------------------------
    mode = cfg["readiness"]["mode"]
    done_today = (state.get("swaps") or {}).get(today.isoformat())
    actions = data["today"]["actions"]
    if done_today:
        data["today"]["actions"] = done_today
    elif actions and mode == "apply" and not dry_run and events is not None:
        reason = "; ".join(f"{s['label']} {s['display']}" for s in data["today"]["signals"] if s["level"] == "red")
        raw = readiness.plan_swaps(events, data["today"]["status"], cfg["readiness"], now,
                                   protected_days(cfg, upcoming))
        for plan_item, shown in zip(raw, actions):
            try:
                cal.apply_swap(plan_item, f"Readiness red ({reason})")
                shown["status"] = "applied"
            except Exception as exc:  # noqa: BLE001
                log.error("Swap failed: %s", type(exc).__name__)
                shown["status"] = f"failed: {type(exc).__name__}"
        state.setdefault("swaps", {})[today.isoformat()] = actions
    elif actions:
        for a in actions:
            a["status"] = "suggested"

    # --- Act: Garmin workouts and activity descriptions -----------------------
    ov = cfg["overload"]
    gstate = state.setdefault("workouts", {})
    for t in data["overload"]["templates"]:
        t["garmin_status"] = "not uploaded"
    if garmin and garmin.api and sources.get("garmin") == "ok" and not dry_run:
        if ov["upload_to_garmin"]:
            next_gym_day = _next_gym_day(events, cfg, today)
            for t in data["overload"]["templates"]:
                workout = overload.build_garmin_workout(t, int(ov["rest_seconds"]))
                h = overload.workout_hash(workout)
                prev = gstate.get(t["id"]) or {}
                try:
                    if prev.get("hash") != h or not prev.get("workout_id"):
                        wid = garmin.replace_workout(workout)
                        prev = {"workout_id": wid, "hash": h}
                    t["garmin_status"] = "uploaded"
                    t["garmin_workout_id"] = prev.get("workout_id")
                    if (t["up_next"] and ov["schedule_on_calendar"] and next_gym_day and prev.get("workout_id")
                            and prev.get("scheduled") != next_gym_day.isoformat()):
                        garmin.schedule(prev["workout_id"], next_gym_day)
                        prev["scheduled"] = next_gym_day.isoformat()
                    t["scheduled_for"] = prev.get("scheduled")
                    gstate[t["id"]] = prev
                except Exception as exc:  # noqa: BLE001
                    log.error("Workout upload failed: %s", type(exc).__name__)
                    t["garmin_status"] = f"failed: {type(exc).__name__}"
        if ov["write_activity_descriptions"] and gym_text:
            data["overload"]["descriptions_written"] = _write_descriptions(garmin, activities, gym_text, cfg, today, state)
        garmin.save_tokens()

    _write_outputs(data, out_dir, passphrase, plain_path)
    if passphrase:
        cache_mod.save(cache_path, state, passphrase)
    log.info("Done: %s, %d Garmin calls", ", ".join(f"{k}={v}" for k, v in sources.items()),
             garmin.calls if garmin else 0)
    return data


def _next_gym_day(events: list[dict] | None, cfg: dict, today: date) -> date | None:
    if not events:
        return None
    for ev in sorted(events, key=lambda e: str(e["start"])):
        start = ev["start"]
        day = start.date() if isinstance(start, datetime) else start
        if day >= today and has_keyword(ev["title"], ["gym", "strength", "lift", "lifting", "weights",
                                                       "lower", "upper", "legs", "push", "pull"]):
            return day
    return None


def _write_descriptions(garmin, activities: list[dict], gym_text: str, cfg: dict, today: date,
                        state: dict) -> int:
    ov = cfg["overload"]
    sessions = parse_gym_log(gym_text, today, ov["date_order"], ov["weight_unit"])
    by_date: dict[str, list[Session]] = {}
    for s in sessions:
        by_date.setdefault(s.date.isoformat(), []).append(s)
    written = state.setdefault("descriptions", {})
    count = 0
    for a in activities:
        if a.get("type") not in {"strength_training", "indoor_cardio", "hiit"}:
            continue
        if d(a["date"]) < today - timedelta(days=10) or a["date"] not in by_date:
            continue
        session = by_date[a["date"]][-1]
        text = overload.activity_description(session)
        if written.get(str(a["id"])) == text:
            continue
        current = garmin.activity_description(a["id"])
        if current and not overload.is_ours(current):
            written[str(a["id"])] = text  # you wrote your own description; leave it alone
            continue
        try:
            garmin.set_description(a["id"], text)
            written[str(a["id"])] = text
            count += 1
        except Exception as exc:  # noqa: BLE001
            log.error("Description write failed: %s", type(exc).__name__)
    return count
