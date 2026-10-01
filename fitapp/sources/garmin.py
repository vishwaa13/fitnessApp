"""Garmin Connect: read activities and daily recovery metrics, write workouts.

Auth order: tokens saved by the previous run (in the encrypted cache), then
the GARMIN_TOKENS secret, then GARMIN_EMAIL / GARMIN_PASSWORD. Garmin rotates
refresh tokens, so the current tokens are written back to the cache after
every run.
"""

from __future__ import annotations

import logging
import re
import os
import shutil
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..util import parse_local

log = logging.getLogger(__name__)

EDWARDS_ZONES = [(0.9, 5), (0.8, 4), (0.7, 3), (0.6, 2), (0.0, 1)]


def estimate_load(duration_min: float, avg_hr: float | None, max_hr: float | None) -> float | None:
    """Edwards TRIMP when Garmin didn't compute a training load."""
    if not (duration_min and avg_hr and max_hr):
        return None
    frac = avg_hr / max_hr
    weight = next(w for lo, w in EDWARDS_ZONES if frac >= lo)
    return duration_min * weight


def normalize_activity(a: dict) -> dict | None:
    start = parse_local(a.get("startTimeLocal"))
    if not start:
        return None
    duration = a.get("duration") or a.get("movingDuration") or 0
    elapsed = a.get("elapsedDuration") or duration
    end = start + timedelta(seconds=elapsed or 0)
    return {
        "id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": (a.get("activityType") or {}).get("typeKey"),
        "date": start.date().isoformat(),
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
        "duration_min": round(duration / 60, 1) if duration else None,
        "distance_km": round(a["distance"] / 1000, 2) if a.get("distance") else None,
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "load": a.get("activityTrainingLoad"),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "anaerobic_te": a.get("anaerobicTrainingEffect"),
        "location": a.get("locationName"),
        "lat": a.get("startLatitude"),
        "lon": a.get("startLongitude"),
        "description": a.get("description"),
    }


def _morning_readiness(data: Any) -> dict:
    if isinstance(data, list):
        if not data:
            return {}
        return next((e for e in data if e.get("inputContext") == "AFTER_WAKEUP_RESET"), data[-1])
    return data or {}


def _humanize(code: str | None) -> str:
    if not code:
        return ""
    text = code.replace("_", " ").capitalize()
    return re.sub(r"\bhrv\b", "HRV", text, flags=re.I)


def lifestyle_tags(data: Any) -> list[str]:
    """Pull 'yes' behaviours (alcohol, caffeine, ...) out of Garmin's lifestyle log.

    The payload shape isn't documented, so walk it looking for named entries
    that were logged as yes / with an amount."""
    tags: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = node.get("name") or node.get("behaviorName") or node.get("behavior") or node.get("category")
            status = str(node.get("status") or node.get("answer") or node.get("value") or "").upper()
            amount = node.get("amount") or node.get("quantity") or node.get("count")
            if isinstance(name, str) and (status in {"YES", "TRUE", "1"} or (isinstance(amount, (int, float)) and amount > 0)):
                slug = name.strip().lower().replace(" ", "_")
                tags.add("alcohol" if "alcohol" in slug else slug)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return sorted(tags)


def normalize_day(day: date, hrv: Any, sleep: Any, readiness: Any, summary: Any, lifestyle: Any) -> dict:
    hs = (hrv or {}).get("hrvSummary") or {}
    base = hs.get("baselineDTO") or hs.get("baseline") or {}
    dto = (sleep or {}).get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    overall = (scores.get("overall") or {}).get("value")
    tr = _morning_readiness(readiness)
    summary = summary or {}
    seconds = dto.get("sleepTimeSeconds")
    return {
        "date": day.isoformat(),
        "hrv": hs.get("lastNightAvg"),
        "hrv_weekly": hs.get("weeklyAvg"),
        "hrv_low": base.get("balancedLow"),
        "hrv_high": base.get("balancedUpper"),
        "hrv_status": hs.get("status"),
        "sleep_score": overall,
        "sleep_hours": round(seconds / 3600, 2) if seconds else None,
        "rhr": summary.get("restingHeartRate") or (sleep or {}).get("restingHeartRate"),
        "readiness": tr.get("score"),
        "readiness_level": tr.get("level"),
        "readiness_feedback": _humanize(tr.get("feedbackShort")),
        "bb_high": summary.get("bodyBatteryHighestValue"),
        "bb_wake": summary.get("bodyBatteryAtWakeTime"),
        "stress": summary.get("averageStressLevel"),
        "lifestyle_tags": lifestyle_tags(lifestyle),
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _complete(row: dict) -> bool:
    return row.get("hrv") is not None and row.get("sleep_score") is not None


class GarminSource:
    def __init__(self, cache: dict):
        self.cache = cache
        self.api = None
        self.calls = 0

    def login(self) -> None:
        from garminconnect import Garmin

        api = Garmin(os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))
        tmp = Path(tempfile.mkdtemp())
        token_file = tmp / "garmin_tokens.json"
        try:
            for source in (self.cache.get("garmin_tokens"), os.getenv("GARMIN_TOKENS")):
                if not source:
                    continue
                token_file.write_text(source)
                try:
                    api.login(tokenstore=str(tmp))
                    break
                except Exception as exc:  # noqa: BLE001 - try the next credential source
                    log.warning("Garmin token login failed (%s); trying next option", type(exc).__name__)
            else:
                if not (os.getenv("GARMIN_EMAIL") and os.getenv("GARMIN_PASSWORD")):
                    raise RuntimeError("No usable Garmin tokens and no GARMIN_EMAIL/GARMIN_PASSWORD")
                api.login()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            api.client._tokenstore_path = None  # tokens go back into the encrypted cache instead
        self.api = api
        self.save_tokens()

    def save_tokens(self) -> None:
        if self.api is not None:
            self.cache["garmin_tokens"] = self.api.client.dumps()

    def _call(self, fn, *args, default=None):
        self.calls += 1
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - one missing metric shouldn't sink the run
            name = type(exc).__name__
            if "TooManyRequests" in name:
                raise
            log.debug("Garmin call %s failed: %s", getattr(fn, "__name__", fn), name)
            return default
        finally:
            time.sleep(0.25)

    # -- reads ---------------------------------------------------------------
    def activities(self, since: date) -> dict[str, dict]:
        store: dict[str, dict] = self.cache.setdefault("activities", {})
        known = set(store)
        start = 0
        for _ in range(10):
            page = self._call(self.api.get_activities, start, 100, default=[]) or []
            if not page:
                break
            stop = False
            for raw in page:
                act = normalize_activity(raw)
                if not act or act["id"] is None:
                    continue
                if date.fromisoformat(act["date"]) < since:
                    stop = True
                    continue
                store[str(act["id"])] = act
            oldest_ids = {str(r.get("activityId")) for r in page[-5:]}
            if stop or oldest_ids <= known:
                break
            start += 100
        for key in [k for k, a in store.items() if date.fromisoformat(a["date"]) < since]:
            del store[key]
        return store

    def daily(self, since: date, today: date, max_days: int = 45) -> dict[str, dict]:
        store: dict[str, dict] = self.cache.setdefault("daily", {})
        fetched: dict[str, str] = self.cache.setdefault("daily_fetched", {})
        todo = []
        day = today
        while day >= since:
            key = day.isoformat()
            row = store.get(key)
            age = (today - day).days
            last = fetched.get(key)
            stale = last is None or (age <= 2) or (not (row and _complete(row)) and age <= 7
                                                      and last < (_utcnow() - timedelta(hours=6)).isoformat())
            if stale:
                todo.append(day)
            day -= timedelta(days=1)
        for day in todo[:max_days]:
            ds = day.isoformat()
            store[ds] = normalize_day(
                day,
                self._call(self.api.get_hrv_data, ds),
                self._call(self.api.get_sleep_data, ds),
                self._call(self.api.get_training_readiness, ds),
                self._call(self.api.get_user_summary, ds),
                self._call(self.api.get_lifestyle_logging_data, ds),
            )
            fetched[ds] = _utcnow().isoformat()
        for key in [k for k in store if k < since.isoformat()]:
            store.pop(key, None)
            fetched.pop(key, None)
        log.info("Garmin: refreshed %d day(s), %d still to backfill", min(len(todo), max_days),
                 max(0, len(todo) - max_days))
        return store

    def max_hr(self) -> float | None:
        profile = self._call(self.api.get_user_profile, default={}) or {}
        user = profile.get("userData") or {}
        return user.get("maxHeartRate") or None

    def activity_description(self, activity_id: int | str) -> str | None:
        data = self._call(self.api.get_activity, activity_id, default={}) or {}
        return data.get("description") or (data.get("summaryDTO") or {}).get("description")

    # -- writes --------------------------------------------------------------
    def set_description(self, activity_id: int | str, text: str) -> None:
        self.api.client.put("connectapi", f"/activity-service/activity/{activity_id}",
                            json={"activityId": int(activity_id), "description": text}, api=True)

    def replace_workout(self, workout: dict) -> int | None:
        """Upload ``workout``, deleting any older copy with the same name first."""
        existing = self._call(self.api.get_workouts, 0, 200, default=[]) or []
        for w in existing:
            if w.get("workoutName") == workout["workoutName"]:
                self._call(self.api.delete_workout, w["workoutId"])
        resp = self.api.upload_workout(workout)
        return (resp or {}).get("workoutId")

    def schedule(self, workout_id: int, day: date) -> None:
        self.api.schedule_workout(workout_id, day.isoformat())
