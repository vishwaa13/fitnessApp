"""Find out where a calendar event is, using Google's Gemini API with Google Search.

Free option: an API key from Google AI Studio (no card) in the GEMINI_API_CODE
secret. Gemini 2.5 Flash's free tier includes Google Search grounding, which
this needs; the newest Gemini models don't, so the model is pinned in config.
Free-tier requests may be used by Google to improve its products, so only the
event title, dates and calendar location are sent.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from typing import Any

import requests

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
SURFACES = {"beach", "grass", "turf", "indoor", "unknown"}
CONFIDENCE = {"high", "medium", "low"}

SYSTEM = (
    "You help an ultimate frisbee player plan their season. Given an event from their "
    "calendar, search the web to identify which ultimate frisbee event it is (tournament, "
    "hat tournament, national team tryout, club or beach championship) and where it takes "
    "place. Prefer official sources: the event's own site, the national federation, WFDF, "
    "EUF, or Ultimate Central. The calendar title is often a short nickname or misspelled. "
    "Reply with only a JSON object, no other text, with these keys: "
    '"full_name" (string), "city" (string or null), "country" (string or null), '
    '"venue" (string or null), "latitude" (number or null, city level is fine), '
    '"longitude" (number or null), "surface" ("beach", "grass", "turf", "indoor" or "unknown"), '
    '"division" (string or null, e.g. mixed, women\'s, open, hat), "website" (string or null), '
    '"summary" (one or two sentences a player would want to know), '
    '"confidence" ("high", "medium" or "low"; low if you could not tell which event it is). '
    "Use null rather than guessing a venue."
)


class GeminiError(RuntimeError):
    pass


def _prompt(title: str, start: date, end: date, calendar_location: str | None) -> str:
    when = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
    lines = [f"Calendar title: {title}", f"Dates: {when}"]
    if calendar_location:
        lines.append(f"Location field on the calendar entry: {calendar_location}")
    return "\n".join(lines)


def parse_reply(text: str) -> dict | None:
    """Pull the JSON object out of Gemini's reply and keep only well-typed fields."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or not raw.get("full_name"):
        return None

    def text_or_none(key: str) -> str | None:
        v = raw.get(key)
        return v.strip()[:200] if isinstance(v, str) and v.strip() else None

    def number_or_none(key: str, limit: float) -> float | None:
        v = raw.get(key)
        return float(v) if isinstance(v, (int, float)) and -limit <= v <= limit else None

    website = text_or_none("website")
    return {
        "full_name": text_or_none("full_name"),
        "city": text_or_none("city"),
        "country": text_or_none("country"),
        "venue": text_or_none("venue"),
        "latitude": number_or_none("latitude", 90),
        "longitude": number_or_none("longitude", 180),
        "surface": raw.get("surface") if raw.get("surface") in SURFACES else "unknown",
        "division": text_or_none("division"),
        "website": website if website and website.startswith(("https://", "http://")) else None,
        "summary": (text_or_none("summary") or "")[:400],
        "confidence": raw.get("confidence") if raw.get("confidence") in CONFIDENCE else "low",
    }


class GeminiLookup:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_CODE") or os.getenv("GEMINI_API_KEY")
        self.model = model or DEFAULT_MODEL

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def lookup(self, title: str, start: date, end: date, calendar_location: str | None = None) -> dict | None:
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": _prompt(title, start, end, calendar_location)}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2},
        }
        resp = requests.post(API.format(model=self.model), json=body, timeout=90,
                             headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        if resp.status_code != 200:
            try:
                message = resp.json().get("error", {}).get("message", "")[:160]
            except ValueError:
                message = ""
            log.error("Gemini HTTP %s: %s", resp.status_code, message)
            raise GeminiError(f"HTTP {resp.status_code}")
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            log.warning("Gemini returned no answer (%s)", (data.get("promptFeedback") or {}).get("blockReason"))
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return parse_reply("".join(p.get("text", "") for p in parts))
