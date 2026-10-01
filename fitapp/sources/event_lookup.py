"""Find out where a calendar event actually is, using Claude with web search.

A calendar entry like "Pesca Disco" or "Gurls hat" says nothing about the
venue. Claude searches the web for the ultimate frisbee event that matches
the title and dates, then reports what it found through a strict tool call.
Each event is looked up once and cached in the encrypted state.

Needs ANTHROPIC_API_KEY.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 4

SAVE_TOOL: dict[str, Any] = {
    "name": "save_event",
    "description": "Record what you found out about the event. Call exactly once, after searching.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["full_name", "city", "country", "venue", "latitude", "longitude",
                     "surface", "division", "website", "summary", "confidence"],
        "properties": {
            "full_name": {"type": "string", "description": "Official event name"},
            "city": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "country": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "venue": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Beach, park or sports centre, if known"},
            "latitude": {"anyOf": [{"type": "number"}, {"type": "null"}], "description": "Approximate, city level is fine"},
            "longitude": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "surface": {"type": "string", "enum": ["beach", "grass", "turf", "indoor", "unknown"]},
            "division": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "e.g. mixed, women's, open, hat (random teams)"},
            "website": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Official page or registration link"},
            "summary": {"type": "string", "description": "One or two sentences a player would want to know"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"],
                           "description": "low if you could not tell which event this is"},
        },
    },
}

SYSTEM = (
    "You help an ultimate frisbee player plan their season. Given an event from their "
    "calendar, use web search to identify which ultimate frisbee event it is (tournament, "
    "hat tournament, national team tryout, club or beach championship) and where it takes "
    "place. Prefer official sources: the event's own site, the national federation, WFDF "
    "or EUF, or Ultimate Central / leaguevine pages. The calendar title is often a short "
    "nickname. Then call save_event once. If nothing matches the title and dates, call "
    "save_event with confidence low and null for anything you couldn't confirm; don't guess "
    "a venue."
)


def _prompt(title: str, start: date, end: date, calendar_location: str | None) -> str:
    when = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
    lines = [f"Calendar title: {title}", f"Dates: {when}"]
    if calendar_location:
        lines.append(f"Location field on the calendar entry: {calendar_location}")
    return "\n".join(lines)


class EventLookup:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _anthropic(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def lookup(self, title: str, start: date, end: date, calendar_location: str | None = None) -> dict | None:
        """Return the save_event fields, or None if Claude couldn't (or wouldn't) answer."""
        client = self._anthropic()
        messages: list[dict] = [{"role": "user", "content": _prompt(title, start, end, calendar_location)}]
        for _ in range(MAX_CONTINUATIONS + 1):
            response = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}, SAVE_TOOL],
                tool_choice={"type": "auto"},
                output_config={"effort": "medium"},
                # On a safety decline, re-run on Anthropic's recommended fallback model.
                fallbacks="default",
                betas=["server-side-fallback-2026-07-01"],
            )
            if response.stop_reason == "refusal":
                log.warning("Event lookup declined")
                return None
            for block in response.content:
                if block.type == "tool_use" and block.name == "save_event":
                    return dict(block.input)
            if response.stop_reason != "pause_turn":
                return None
            # Long web search: send the paused turn back and the server resumes it.
            messages.append({"role": "assistant", "content": response.content})
        return None
