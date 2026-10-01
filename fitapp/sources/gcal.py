"""Google Calendar access through a service account.

Share your calendar with the service account's e-mail address ("Make changes
to events") and put the account's JSON key in GOOGLE_SERVICE_ACCOUNT_JSON.
Unlike a personal OAuth token this never expires.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
ROLE_KEY = "fitnessAppRole"

_HINTS = {
    "accessNotConfigured": "turn on the Google Calendar API for the service account's Cloud project",
    "SERVICE_DISABLED": "turn on the Google Calendar API for the service account's Cloud project",
    "notFound": "share the calendar with the service account e-mail, and check GOOGLE_CALENDAR_ID",
    "forbidden": "give the service account 'Make changes to events' on the calendar",
    "requiredAccessLevel": "give the service account 'Make changes to events' on the calendar",
    "insufficientPermissions": "give the service account 'Make changes to events' on the calendar",
}


def describe_error(exc: Exception) -> str:
    """A log-safe one-liner: HTTP status, Google's reason code and a fix hint.

    E-mail addresses (the calendar ID) are masked; nothing else personal is
    in Calendar error payloads."""
    from googleapiclient.errors import HttpError

    if isinstance(exc, json.JSONDecodeError):
        return "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON (paste the whole key file)"
    if not isinstance(exc, HttpError):
        return type(exc).__name__
    status = getattr(exc.resp, "status", "?")
    reason, message = "", ""
    try:
        err = json.loads(exc.content.decode("utf-8")).get("error", {})
        message = err.get("message", "")
        details = err.get("errors") or []
        reason = (details[0].get("reason") if details else "") or ""
        for d in err.get("details") or []:
            reason = d.get("reason") or reason
    except Exception:  # noqa: BLE001
        pass
    message = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "<calendar>", message)[:160]
    hint = _HINTS.get(reason) or ("share the calendar with the service account e-mail, and check GOOGLE_CALENDAR_ID"
                                   if status == 404 else "")
    out = f"HTTP {status} {reason}".strip()
    if message:
        out += f" ({message})"
    if hint:
        out += f". Fix: {hint}"
    return out


class CalendarSource:
    def __init__(self, calendar_id: str | None, tz: str):
        self.calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID")
        self.sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        self.tz = ZoneInfo(tz)
        self._svc = None

    @property
    def configured(self) -> bool:
        return bool(self.calendar_id and self.sa_json)

    def _service(self):
        if self._svc is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_info(
                json.loads(self.sa_json), scopes=["https://www.googleapis.com/auth/calendar.events"])
            self._svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._svc

    def _parse(self, when: dict) -> tuple[datetime | date, bool]:
        if "date" in when:
            return date.fromisoformat(when["date"]), True
        dt = datetime.fromisoformat(when["dateTime"].replace("Z", "+00:00"))
        return dt.astimezone(self.tz), False

    def events(self, start: date, days: int) -> list[dict]:
        lo = datetime.combine(start, time.min, self.tz)
        hi = lo + timedelta(days=days + 1)
        items, token = [], None
        while True:
            resp = self._service().events().list(
                calendarId=self.calendar_id, timeMin=lo.isoformat(), timeMax=hi.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=250, pageToken=token).execute()
            items += resp.get("items", [])
            token = resp.get("nextPageToken")
            if not token:
                break
        out = []
        for it in items:
            if it.get("status") == "cancelled" or "start" not in it:
                continue
            s, all_day = self._parse(it["start"])
            e, _ = self._parse(it["end"])
            role = ((it.get("extendedProperties") or {}).get("private") or {}).get(ROLE_KEY)
            out.append({"id": it["id"], "title": it.get("summary") or "", "start": s, "end": e,
                        "all_day": all_day, "role": role, "description": it.get("description") or "",
                        "location": it.get("location") or "", "type": it.get("eventType")})
        return out

    def _when(self, value: datetime | date, all_day: bool) -> dict:
        if all_day:
            return {"date": value.isoformat()}
        local = value.astimezone(self.tz).replace(tzinfo=None)
        return {"dateTime": local.isoformat(timespec="seconds"), "timeZone": str(self.tz)}

    def apply_swap(self, action: dict, reason: str) -> None:
        svc = self._service().events()
        start, end, all_day = action["start"], action["end"], action["all_day"]
        original_day = start if all_day else start.astimezone(self.tz).date()
        light = action["light"]
        if action.get("moved_to"):
            shift = timedelta(days=(action["moved_to"] - original_day).days)
            if all_day:
                new_start, new_end = start + shift, end + shift
            else:
                # Shift the wall-clock time so a DST change doesn't move the session by an hour.
                new_start = (start.astimezone(self.tz).replace(tzinfo=None) + shift).replace(tzinfo=self.tz)
                new_end = (end.astimezone(self.tz).replace(tzinfo=None) + shift).replace(tzinfo=self.tz)
            ev = svc.get(calendarId=self.calendar_id, eventId=action["event_id"]).execute()
            note = f"[Moved from {original_day:%a %d %b} by fitnessApp: {reason}]"
            svc.patch(calendarId=self.calendar_id, eventId=action["event_id"], body={
                "start": self._when(new_start, all_day), "end": self._when(new_end, all_day),
                "description": (note + "\n\n" + (ev.get("description") or "")).strip(),
                "extendedProperties": {"private": {ROLE_KEY: "moved"}},
            }).execute()
            svc.insert(calendarId=self.calendar_id, body={
                "summary": light["title"],
                "description": f"{light.get('description', '')}\n\nSwapped in for \"{action['title']}\" "
                               f"(moved to {action['moved_to']:%a %d %b}). {reason}".strip(),
                "start": self._when(start, all_day), "end": self._when(end, all_day),
                "extendedProperties": {"private": {ROLE_KEY: "light"}},
            }).execute()
        else:
            svc.patch(calendarId=self.calendar_id, eventId=action["event_id"], body={
                "summary": light["title"],
                "description": f"{light.get('description', '')}\n\nOriginally \"{action['title']}\". "
                               f"No free day in the next week to move it to. {reason}".strip(),
                "extendedProperties": {"private": {ROLE_KEY: "light"}},
            }).execute()
        log.info("Calendar: swapped one session (moved=%s)", bool(action.get("moved_to")))
