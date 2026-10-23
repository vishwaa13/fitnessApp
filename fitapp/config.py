"""Load config.yml on top of built-in defaults."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

# Lifts to back off when a gym-log note reports pain there (matched on the lift's name).
PAIN_AFFECTS = {
    "shoulder": ["bench", "press", "incline", "ohp", "dip", "push up", "lateral raise", "front raise", "fly",
                 "pull up", "chin up", "pulldown", "vertical"],
    "chest": ["bench", "press", "incline", "dip", "push up", "fly"],
    "elbow": ["bench", "press", "dip", "push up", "bicep", "biceps", "hammer curl", "barbell curl", "extension",
              "pull up", "chin up", "pulldown", "vertical", "row"],
    "wrist": ["bench", "press", "dip", "push up", "bicep", "biceps", "hammer curl", "barbell curl", "clean"],
    "knee": ["squat", "lunge", "split squat", "step up", "leg extension", "leg press", "jump", "clean"],
    "hamstring": ["deadlift", "dl", "rdl", "nordic", "hamstring curl", "leg curl", "hip thrust", "clean",
                  "good morning"],
    "glute": ["hip thrust", "squat", "deadlift", "dl", "rdl", "lunge", "split squat", "step up"],
    "lower back": ["deadlift", "dl", "rdl", "squat", "clean", "row", "good morning", "hip thrust"],
    "back": ["deadlift", "dl", "rdl", "squat", "clean", "row", "good morning", "hip thrust"],
    "hip": ["squat", "lunge", "split squat", "step up", "deadlift", "dl", "hip thrust"],
    "hip flexor": ["leg raise", "dragon flag", "squat", "lunge", "split squat"],
    "groin": ["squat", "lunge", "split squat", "sumo", "step up"],
    "adductor": ["squat", "lunge", "split squat", "sumo", "step up"],
    "calf": ["calf raise", "jump", "step up", "lunge", "split squat"],
    "achilles": ["calf raise", "jump", "step up", "lunge", "split squat"],
    "ankle": ["calf raise", "jump", "step up", "lunge", "split squat", "squat"],
    "neck": ["shoulder press", "ohp", "shrug", "deadlift"],
    "trap": ["shoulder press", "ohp", "shrug", "deadlift"],
}

DEFAULTS: dict[str, Any] = {
    "timezone": "Europe/Rome",
    "athlete": {"max_hr": None, "home": None},
    "history_days": 180,
    "readiness": {
        "mode": "apply",
        "swap_when": "red",
        "calendar_id": None,
        "look_ahead_days": 7,
        "thresholds": {
            "readiness_red": 40,
            "readiness_amber": 60,
            "sleep_score_red": 50,
            "sleep_score_amber": 65,
            "sleep_hours_red": 5.5,
            "sleep_hours_amber": 6.5,
            "rhr_amber_bpm": 5,
            "rhr_red_bpm": 8,
        },
        "hard_keywords": ["interval", "intervals", "tempo", "threshold", "track", "vo2",
                          "sprint", "sprints", "heavy", "strength", "gym"],
        "protected_keywords": ["tournament", "game", "match", "tryout", "tryouts", "race"],
        "light_versions": [],
        "default_light": {"title": "Easy Z1–Z2 session · 30 min",
                          "description": "Keep it genuinely easy. Today is for recovery."},
    },
    "tournaments": {
        "game_types": ["ultimate_disc", "ultimate", "other"],
        "game_keywords": ["game", "match", "ultimate", "tournament"],
        "names_by_location": {},
        "manual": [],
        "hrv_rebound_tolerance": 0.05,
    },
    "overload": {
        "keep_note_title": "gym logs",
        "date_order": "DMY",
        "weight_unit": "kg",
        "set_format": "auto",
        "aliases": {},
        "upload_to_garmin": True,
        "schedule_on_calendar": True,
        "write_activity_descriptions": True,
        "rest_seconds": 120,
        "default_increment": 2.5,
        "default_rep_range": [8, 12],
        "rules": [],
        "garmin_exercise_overrides": {},
    },
    "events": {
        "keywords": ["tryout", "tryouts", "tournament", "hat", "championship"],
        "look_ahead_days": 365,
        "gemini_models": ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"],
    },
    "recovery": {
        "keep_tags_note_title": "recovery tags",
        "late_training_hour": 20,
        "travel_km": 150,
        "window_days": 180,
    },
    "injury": {
        "rest_day_load": 25,
        "high_day_load": 180,
        "acwr_caution": 1.3,
        "acwr_high": 1.5,
        "monotony_caution": 2.0,
        "pain_hold_days": 14,
        "pain_affects": PAIN_AFFECTS,
        "history": [],
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else Path(__file__).resolve().parent.parent / "config.yml"
    user: dict[str, Any] = {}
    if path.exists():
        user = yaml.safe_load(path.read_text()) or {}
    return _merge(DEFAULTS, user)
