"""Garmin Connect Personal API: Garmin's official, read-only access to your own data.

You create a personal API key on Garmin Connect Web (it expires after 30 days
to a year) and store it as the GARMIN_API_KEY secret. Each run swaps it for a
24-hour OAuth2 access token; there are no refresh tokens. The API covers
activities, HRV, sleep and the daily summary. Training readiness, the
lifestyle log and anything that writes (workouts, activity descriptions)
aren't in it, so those stay on the unofficial connection in garmin.py.

Docs: https://developer.garmin.com/gc-developer-program/personal/swagger-docs/
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"


class KeyRejected(RuntimeError):
    """The key was refused: expired, deleted, or mistyped."""


class RateLimited(RuntimeError):
    pass


def clean_key(raw: str | None) -> str:
    """Tolerate a key pasted with the docs' wrapping: quotes, [brackets], an "ApiKey " prefix."""
    key = (raw or "").strip().strip('"').strip("'").strip()
    if key.lower().startswith("apikey "):
        key = key[7:].strip()
    return key.strip("[]<>").strip()


def _token_from(resp: requests.Response) -> str | None:
    """The token endpoint's body isn't documented: accept the usual OAuth2 shapes or plain text."""
    try:
        body = resp.json()
    except ValueError:
        text = resp.text.strip().strip('"')
        return text or None
    if isinstance(body, str):
        return body or None
    if isinstance(body, dict):
        for key in ("access_token", "accessToken", "token", "value"):
            if isinstance(body.get(key), str) and body[key]:
                return body[key]
        for nested in body.values():
            if isinstance(nested, dict):
                for key in ("access_token", "accessToken", "token"):
                    if isinstance(nested.get(key), str) and nested[key]:
                        return nested[key]
        log.error("Garmin API token response had no token field; fields: %s", ", ".join(sorted(body)))
    return None


class PersonalApi:
    def __init__(self, key: str | None = None, session: requests.Session | None = None, pause: float = 0.2):
        self.key = clean_key(key or os.getenv("GARMIN_API_KEY"))
        self.session = session or requests.Session()
        self.token: str | None = None
        self.calls = 0
        self.pause = pause

    @property
    def configured(self) -> bool:
        return bool(self.key)

    def _why(self, resp: requests.Response) -> str:
        """Status and Garmin's message, with the key and any token blanked, for the (public) log."""
        text = (getattr(resp, "text", "") or "").replace(self.key, "<key>") if self.key else ""
        text = " ".join(text.split())[:200]
        return f"HTTP {resp.status_code}" + (f": {text}" if text else "")

    def connect(self) -> None:
        # Exactly the documented request: POST, no body, only the Authorization header.
        resp = self.session.post(BASE + TOKEN_PATH, headers={"Authorization": f"ApiKey {self.key}"}, timeout=30)
        self.calls += 1
        if resp.status_code in (401, 403):
            raise KeyRejected(self._why(resp))
        if resp.status_code >= 400:
            log.error("Garmin Personal API token request failed: %s", self._why(resp))
            raise RuntimeError(f"HTTP {resp.status_code}")
        self.token = _token_from(resp)
        if not self.token:
            raise RuntimeError("no access token in the response")

    def get(self, path: str, **params: Any) -> Any:
        """GET a Personal API path; None when Garmin has nothing for it (404/204)."""
        if not self.token:
            raise RuntimeError("connect() first")
        resp = self.session.get(BASE + path, params={k: v for k, v in params.items() if v is not None},
                                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                                timeout=60)
        self.calls += 1
        time.sleep(self.pause)
        if resp.status_code in (204, 404):
            return None
        if resp.status_code in (401, 403):
            raise KeyRejected(f"HTTP {resp.status_code}")
        if resp.status_code == 429:
            raise RateLimited("HTTP 429")
        resp.raise_for_status()
        return resp.json() if resp.content else None

    # -- the reads the dashboard needs, shaped like the unofficial library's ----
    def activities(self, since: date, until: date) -> list[dict]:
        out: list[dict] = []
        start = 0
        while True:
            page = self.get("/activitylist-service/activities/search/activities", start=start, limit=99,
                            startDate=since.isoformat(), endDate=until.isoformat(), sortOrder="desc") or []
            out += page
            if len(page) < 99 or start > 2000:
                return out
            start += 99

    def hrv(self, day: str) -> Any:
        return self.get(f"/hrv-service/hrv/{day}")

    def sleep(self, day: str) -> Any:
        """Wrapped like the unofficial library's {"dailySleepDTO": {...}} so one parser reads both."""
        dto = self.get("/sleep-service/sleep/dailySleep", date=day)
        return {"dailySleepDTO": dto} if dto else None

    def summary(self, day: str) -> Any:
        return self.get("/usersummary-service/usersummary/daily", calendarDate=day)

    def max_hr(self) -> float | None:
        zones = self.get("/biometric-service/heartRateZones/v2") or []
        values = [z.get("maxHeartRateUsed") for z in zones if isinstance(z, dict) and z.get("maxHeartRateUsed")]
        return max(values) if values else None
