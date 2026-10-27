"""Garmin Connect: read activities and daily recovery metrics, write workouts.

Auth order: tokens saved by the previous run (in the encrypted cache), then
the GARMIN_TOKENS secret, then GARMIN_EMAIL / GARMIN_PASSWORD. Garmin rotates
refresh tokens, so the current tokens are written back to the cache after
every run.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..util import parse_local
from .garmin_official import KeyRejected, PersonalApi, RateLimited

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


LIFESTYLE_VERSION = 3   # bump to re-read stored days after changing lifestyle_tags()
_NAME_KEYS = ("behaviorName", "name", "displayName", "behavior", "behaviorType", "subTypeName", "category")
_AMOUNT_KEYS = {"amount", "quantity", "count", "value", "totalamount", "servings"}
_ALCOHOL = re.compile(r"alcohol|beer|wine|spirit|liquor|cocktail|drink", re.I)


def lifestyle_tags(data: Any) -> list[str]:
    """Pull 'yes' behaviours (alcohol, caffeine, ...) out of Garmin's lifestyle log.

    The payload shape isn't documented, so walk it looking for named entries
    logged as yes (any "...status" field) or with an amount. Beer, wine and
    the like all count as alcohol."""
    tags: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            name = next((node[k] for k in _NAME_KEYS if isinstance(node.get(k), str) and node[k].strip()), None)
            status = next((str(v).upper() for k, v in node.items()
                           if k.lower().endswith("status") or k.lower() in {"answer", "logged"}), "")
            amount = next((v for k, v in node.items() if k.lower() in _AMOUNT_KEYS
                           and isinstance(v, (int, float)) and not isinstance(v, bool)), None)
            if name and (status in {"YES", "TRUE", "1", "LOGGED"} or (amount is not None and amount > 0)):
                slug = name.strip().lower().replace(" ", "_")
                tags.add("alcohol" if _ALCOHOL.search(slug) else slug)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return sorted(tags)


def _amount(node: dict) -> float | None:
    return next((float(v) for k, v in node.items() if k.lower() in _AMOUNT_KEYS
                 and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0), None)


def drinks(data: Any) -> dict[str, float] | None:
    """Drinks by type from the alcohol entry, e.g. {"beer": 2, "wine": 1}.

    {} means alcohol was logged without amounts, None that none was logged."""
    found: dict[str, float] | None = None

    def walk(node: Any) -> None:
        nonlocal found
        if isinstance(node, list):
            for v in node:
                walk(v)
            return
        if not isinstance(node, dict):
            return
        name = next((node[k] for k in _NAME_KEYS if isinstance(node.get(k), str) and node[k].strip()), None)
        details = [x for x in node.get("details") or [] if isinstance(x, dict)]
        if name and _ALCOHOL.search(name) and details is not None and not node.get("subTypeName"):
            status = next((str(v).upper() for k, v in node.items()
                           if k.lower().endswith("status") or k.lower() in {"answer", "logged"}), "")
            by_type: dict[str, float] = {}
            for det in details:
                if (amt := _amount(det)) is not None:
                    kind = str(det.get("subTypeName") or det.get("name") or "drinks").strip().lower()
                    by_type[kind] = by_type.get(kind, 0) + amt
            if not by_type and (amt := _amount(node)) is not None:
                by_type["drinks"] = amt
            if by_type or status in {"YES", "TRUE", "1", "LOGGED"}:
                found = {**(found or {}), **by_type}
            return
        for v in node.values():
            walk(v)

    walk(data)
    return found


def payload_keys(data: Any, prefix: str = "") -> set[str]:
    """Field names only (no values), to debug an unknown payload in public logs."""
    keys: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            keys.add(prefix + k)
            keys |= payload_keys(v, prefix + k + ".")
    elif isinstance(data, list):
        for v in data:
            keys |= payload_keys(v, prefix)
    return keys


def answered(data: Any) -> bool:
    """Whether you logged anything that day (Garmin's own completedTracking count; unknown counts as yes)."""
    stats = (data or {}).get("completionStats") if isinstance(data, dict) else None
    return bool(data) and (not isinstance(stats, dict) or (stats.get("completedTracking") or 0) > 0)


def _local_time(ms: Any) -> str | None:
    """Garmin's "...TimestampLocal" fields are your wall-clock time stored as epoch ms."""
    if not isinstance(ms, (int, float)) or isinstance(ms, bool) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M")


def sleep_window(sleep: Any) -> tuple[str | None, str | None]:
    """(fell asleep, woke up) as local "YYYY-MM-DDTHH:MM" for the night ending on this date."""
    dto = (sleep or {}).get("dailySleepDTO") or {}
    return _local_time(dto.get("sleepStartTimestampLocal")), _local_time(dto.get("sleepEndTimestampLocal"))


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
        "drinks": drinks(lifestyle),
        "bed": sleep_window(sleep)[0],
        "wake": sleep_window(sleep)[1],
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _complete(row: dict) -> bool:
    return row.get("hrv") is not None and row.get("sleep_score") is not None


class GarminSource:
    """Garmin data from two connections.

    ``official`` is Garmin's Personal API (GARMIN_API_KEY): activities, HRV,
    sleep and the daily summary come from it when it's set up. ``api`` is the
    unofficial garminconnect login (GARMIN_TOKENS): training readiness, the
    lifestyle log and every write (workouts, activity descriptions) need it,
    and it stands in for the official API when that isn't available. Either
    one failing leaves the other working.
    """

    def __init__(self, cache: dict, official: PersonalApi | None = None):
        self.cache = cache
        self.api = None
        self.official = official if official is not None else PersonalApi()
        self.calls = 0
        self.status = {"api": "not set up", "login": "not tried"}

    @property
    def total_calls(self) -> int:
        return self.calls + self.official.calls

    @property
    def can_write(self) -> bool:
        return self.api is not None

    def connect(self) -> None:
        """Both connections; raises only when neither works."""
        if self.official.configured:
            try:
                self.official.connect()
                self.status["api"] = "ok"
            except KeyRejected:
                self.status["api"] = "key rejected"
                log.error("Garmin Personal API key was rejected (expired or deleted?). Create a new one on "
                          "Garmin Connect Web and update the GARMIN_API_KEY secret.")
            except Exception as exc:  # noqa: BLE001
                self.status["api"] = f"error: {type(exc).__name__}"
                log.error("Garmin Personal API failed: %s", type(exc).__name__)
        try:
            self.login()
            self.status["login"] = "ok"
        except Exception as exc:  # noqa: BLE001
            self.status["login"] = f"error: {type(exc).__name__}"
            log.error("Garmin login failed: %s", type(exc).__name__)
        if self.status["api"] != "ok" and self.api is None:
            raise RuntimeError("no Garmin connection")

    def _read(self, official_fn, unofficial_fn, *args):
        """Official API first; the unofficial login when that's off or fails for this read."""
        if self.status["api"] == "ok":
            try:
                return official_fn(*args)
            except (KeyRejected, RateLimited) as exc:
                self.status["api"] = "key rejected" if isinstance(exc, KeyRejected) else "rate limited"
                log.error("Garmin Personal API stopped: %s", self.status["api"])
            except Exception as exc:  # noqa: BLE001 - one missing metric shouldn't sink the run
                log.debug("Garmin Personal API read failed: %s", type(exc).__name__)
        if self.api is not None and unofficial_fn is not None:
            return self._call(unofficial_fn, *args)
        return None

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
    def activities(self, since: date, today: date | None = None) -> dict[str, dict]:
        store: dict[str, dict] = self.cache.setdefault("activities", {})
        if self.status["api"] == "ok":
            raw = self._read(lambda: self.official.activities(since, today or date.today()), None)
            if raw is not None:
                for a in raw:
                    act = normalize_activity(a)
                    if act and act["id"] is not None:
                        store[str(act["id"])] = act
                for key in [k for k, a in store.items() if date.fromisoformat(a["date"]) < since]:
                    del store[key]
                return store
        if self.api is None:
            return store
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
        api = self.api
        official = self.official
        lifestyle: list[Any] = []
        for day in todo[:max_days]:
            ds = day.isoformat()
            old = store.get(ds) or {}
            if api is not None:
                lifestyle.append(self._call(api.get_lifestyle_logging_data, ds))
            row = normalize_day(
                day,
                self._read(official.hrv, api and api.get_hrv_data, ds),
                self._read(official.sleep, api and api.get_sleep_data, ds),
                self._call(api.get_training_readiness, ds) if api is not None else None,
                self._read(official.summary, api and api.get_user_summary, ds),
                lifestyle[-1] if api is not None else None,
            )
            if api is None:
                # Readiness and the lifestyle log only come through the login: keep what we had.
                for key in ("readiness", "readiness_level", "readiness_feedback", "lifestyle_tags", "drinks",
                            "lifestyle_version"):
                    if key in old:
                        row[key] = old[key]
                    else:
                        row.pop(key, None)
            else:
                row["lifestyle_version"] = LIFESTYLE_VERSION
            store[ds] = row
            fetched[ds] = _utcnow().isoformat()
        fresh = {x.isoformat() for x in todo[:max_days]}
        # Days stored before bedtimes were kept: read their sleep again, 40 a run, back 120 days.
        older = [k for k in sorted(store, reverse=True) if "bed" not in store[k] and k not in fresh
                 and (today - date.fromisoformat(k)).days <= 120][:40]
        for ds in older:
            store[ds]["bed"], store[ds]["wake"] = sleep_window(self._read(official.sleep, api and api.get_sleep_data, ds))
        # Days stored before drink amounts were kept (or before the parser
        # changed): read their lifestyle log again, 60 a run.
        stale = [k for k in sorted(store, reverse=True) if k not in fresh
                 and ("drinks" not in store[k] or store[k].get("lifestyle_version") != LIFESTYLE_VERSION)][:60]
        for ds in stale if api is not None else []:
            lifestyle.append(self._call(api.get_lifestyle_logging_data, ds))
            store[ds].update(lifestyle_tags=lifestyle_tags(lifestyle[-1]), drinks=drinks(lifestyle[-1]),
                             lifestyle_version=LIFESTYLE_VERSION)
        logged = [x for x in lifestyle if answered(x)]
        if logged and not any(lifestyle_tags(x) for x in logged):
            keys = set().union(*(payload_keys(x) for x in logged))
            log.info("Garmin lifestyle log: you logged something but none read as yes; fields: %s",
                     ", ".join(sorted(keys))[:900])
        for key in [k for k in store if k < since.isoformat()]:
            store.pop(key, None)
            fetched.pop(key, None)
        log.info("Garmin: refreshed %d day(s), %d still to backfill", min(len(todo), max_days),
                 max(0, len(todo) - max_days))
        return store

    def max_hr(self) -> float | None:
        if (zones := self._read(self.official.max_hr, None)) is not None:
            return zones
        if self.api is None:
            return None
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
