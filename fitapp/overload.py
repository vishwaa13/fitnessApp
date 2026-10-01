"""Double progression and Garmin strength workout building.

Double progression: each lift has a rep range (say 6-10). Keep the weight
until every working set reaches the top of the range, then add weight and
drop back to the bottom. Two sessions in a row below the bottom of the range
at the same weight trigger a 10% deload.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from .gymlog import Session, exercise_key
from .util import has_keyword

# (keywords, Garmin category, Garmin exerciseName). First match wins, so the
# specific variants come before the generic ones. Only pairs that exist in
# Garmin's exercise library are listed; anything else uploads without a
# category and carries its name in the step note.
GARMIN_EXERCISES: list[tuple[list[str], str, str]] = [
    (["front squat"], "SQUAT", "BARBELL_FRONT_SQUAT"),
    (["goblet squat"], "SQUAT", "GOBLET_SQUAT"),
    (["leg press"], "SQUAT", "LEG_PRESS"),
    (["back squat", "squat", "squats"], "SQUAT", "BARBELL_BACK_SQUAT"),
    (["trap bar", "hex bar"], "DEADLIFT", "TRAP_BAR_DEADLIFT"),
    (["sumo"], "DEADLIFT", "SUMO_DEADLIFT"),
    (["rdl", "romanian", "stiff leg", "straight leg", "sldl"], "DEADLIFT", "BARBELL_STRAIGHT_LEG_DEADLIFT"),
    (["deadlift", "deadlifts", "dl"], "DEADLIFT", "BARBELL_DEADLIFT"),
    (["incline db", "incline dumbbell"], "BENCH_PRESS", "INCLINE_DUMBBELL_BENCH_PRESS"),
    (["db bench", "dumbbell bench"], "BENCH_PRESS", "DUMBBELL_BENCH_PRESS"),
    (["bench", "bench press"], "BENCH_PRESS", "BARBELL_BENCH_PRESS"),
    (["ohp", "overhead press", "military press", "shoulder press"], "SHOULDER_PRESS", "OVERHEAD_BARBELL_PRESS"),
    (["hip thrust", "hip thrusts"], "HIP_RAISE", "BARBELL_HIP_THRUST_WITH_BENCH"),
    (["chin up", "chin-up", "chinup", "chin ups", "chin-ups", "chins"], "PULL_UP", "CHIN_UP"),
    (["weighted pull up", "weighted pull-up", "weighted pullup"], "PULL_UP", "WEIGHTED_PULL_UP"),
    (["pull up", "pull-up", "pullup", "pull ups", "pull-ups", "pullups"], "PULL_UP", "PULL_UP"),
    (["lat pulldown", "pulldown", "pull down"], "PULL_UP", "LAT_PULLDOWN"),
    (["push up", "push-up", "pushup", "push ups", "push-ups", "pushups"], "PUSH_UP", "PUSH_UP"),
    (["leg curl", "hamstring curl", "leg curls"], "LEG_CURL", "LEG_CURL"),
    (["barbell curl", "bb curl"], "CURL", "BARBELL_BICEPS_CURL"),
    (["dumbbell row", "db row"], "ROW", "DUMBBELL_ROW"),
    (["seated cable row", "cable row"], "ROW", "SEATED_CABLE_ROW"),
    (["face pull", "face pulls"], "ROW", "FACE_PULL"),
    (["t-bar", "t bar"], "ROW", "T_BAR_ROW"),
]


def garmin_exercise(name: str, overrides: dict[str, dict] | None = None) -> dict | None:
    for key, value in (overrides or {}).items():
        if has_keyword(name, [key]):
            return {"category": value["category"], "name": value.get("name")}
    for keywords, category, ex_name in GARMIN_EXERCISES:
        if has_keyword(name, keywords):
            return {"category": category, "name": ex_name}
    return None


def lift_rule(name: str, cfg: dict) -> tuple[list[int], float]:
    for rule in cfg.get("rules", []):
        if has_keyword(name, rule.get("match", [])):
            return list(rule.get("rep_range", cfg["default_rep_range"])), float(rule.get("increment", cfg["default_increment"]))
    return list(cfg["default_rep_range"]), float(cfg["default_increment"])


def e1rm(weight: float | None, reps: int) -> float | None:
    if not weight:
        return None
    return round(weight * (1 + reps / 30), 1)


def _round_to(value: float, step: float) -> float:
    step = step if step > 0 else 1.25
    return round(round(value / step) * step, 2)


def _working_sets(sets: list[dict]) -> list[dict]:
    weights = [s["w"] for s in sets if s["w"]]
    if not weights:
        return list(sets)
    top = max(weights)
    return [s for s in sets if s["w"] == top]


def progress(history: list[dict], rep_range: list[int], increment: float) -> dict[str, Any]:
    """Next target from a lift's history (oldest first), each {"date", "sets"}."""
    last = history[-1]
    work = _working_sets(last["sets"])
    lo, hi = rep_range
    weight = work[0]["w"]
    reps = [s["r"] for s in work]
    n = len(work)
    bodyweight = not weight

    if all(r >= hi for r in reps):
        if bodyweight:
            return {"weight": None, "sets": n, "reps": [hi] * n, "action": "add_load",
                    "note": f"Hit {hi} on every set. Add reps beyond the range, or hold a {increment:g} kg plate."}
        new_w = round(weight + increment, 2)
        return {"weight": new_w, "sets": n, "reps": [lo] * n, "action": "add_weight",
                "note": f"All sets hit {hi}. +{increment:g} kg, back to {lo} reps."}

    if any(r < lo for r in reps):
        stalled = False
        if len(history) >= 2:
            prev = _working_sets(history[-2]["sets"])
            stalled = prev[0]["w"] == weight and any(s["r"] < lo for s in prev)
        if stalled and not bodyweight:
            new_w = _round_to(weight * 0.9, increment / 2 if increment <= 2.5 else 2.5)
            return {"weight": new_w, "sets": n, "reps": [lo] * n, "action": "deload",
                    "note": f"Two sessions under {lo} reps at {weight:g} kg. Deload 10% and build back."}
        return {"weight": weight, "sets": n, "reps": [lo] * n, "action": "hold",
                "note": f"Some sets fell under {lo}. Same weight, aim for {lo} on every set."}

    targets = [min(hi, r + 1) for r in reps]
    return {"weight": weight, "sets": n, "reps": targets, "action": "add_reps",
            "note": "Same weight, one more rep on each set."}


def _signature(session: Session) -> set[str]:
    return {e.key for e in session.exercises}


def group_templates(sessions: list[Session]) -> dict[str, list[Session]]:
    """Group sessions into recurring workouts: by title, else by exercise overlap."""
    groups: dict[str, list[Session]] = {}
    for s in sessions:
        if s.title:
            key = "t:" + exercise_key(s.title)
        else:
            sig = _signature(s)
            key = None
            for gk, members in groups.items():
                if gk.startswith("t:"):
                    continue
                other = _signature(members[-1])
                if sig and other and len(sig & other) / len(sig | other) >= 0.5:
                    key = gk
                    break
            key = key or "s:" + "+".join(sorted(sig))[:80]
        groups.setdefault(key, []).append(s)
    return groups


def template_name(members: list[Session]) -> str:
    latest = members[-1]
    if latest.title:
        return latest.title
    names = [e.name for e in latest.exercises[:2]]
    return " + ".join(names) if names else "Session"


def build_plan(sessions: list[Session], cfg: dict, today: date) -> dict[str, Any]:
    """Next-session targets for every recently used workout template."""
    by_lift: dict[str, list[dict]] = {}
    display: dict[str, str] = {}
    for s in sessions:
        for e in s.exercises:
            if e.sets:
                by_lift.setdefault(e.key, []).append({"date": s.date.isoformat(), "sets": e.sets,
                                                      "rep_range": e.rep_range})
                display[e.key] = e.name

    lifts: dict[str, dict] = {}
    for key, hist in by_lift.items():
        name = display[key]
        rep_range, increment = lift_rule(name, cfg)
        explicit = next((h["rep_range"] for h in reversed(hist) if h["rep_range"]), None)
        if explicit:
            rep_range = explicit
        lifts[key] = {
            "name": name,
            "key": key,
            "rep_range": rep_range,
            "increment": increment,
            "history": [{"date": h["date"], "best_e1rm": max((e1rm(st["w"], st["r"]) or 0) for st in h["sets"]) or None,
                         "top_weight": max((st["w"] or 0) for st in h["sets"]) or None,
                         "total_reps": sum(st["r"] for st in h["sets"])} for h in hist],
            "garmin": garmin_exercise(name, cfg.get("garmin_exercise_overrides")),
            "_hist": hist,
        }

    templates = []
    recent_cutoff = today - timedelta(days=42)
    for gk, members in group_templates(sessions).items():
        latest = members[-1]
        if latest.date < recent_cutoff:
            continue
        exercises = []
        for e in latest.exercises:
            lift = lifts.get(e.key)
            if not lift:
                continue
            # Progress from this template's own history of the lift when it has one.
            own = [{"date": m.date.isoformat(), "sets": x.sets}
                   for m in members for x in m.exercises if x.key == e.key and x.sets]
            hist = own or lift["_hist"]
            nxt = progress(hist, lift["rep_range"], lift["increment"])
            exercises.append({
                "name": lift["name"], "key": e.key, "rep_range": lift["rep_range"],
                "last": {"date": hist[-1]["date"], "sets": hist[-1]["sets"]},
                "next": nxt, "garmin": lift["garmin"],
            })
        if exercises:
            templates.append({"id": gk, "name": template_name(members), "last_date": latest.date.isoformat(),
                              "times_done": len(members), "exercises": exercises})

    # Rotation guess: the template you did least recently is up next.
    templates.sort(key=lambda t: t["last_date"])
    for i, t in enumerate(templates):
        t["up_next"] = i == 0
    for lift in lifts.values():
        lift.pop("_hist", None)
    # Stalled = the last session didn't beat any of the three before it
    # (heavier weight wins; at equal weight, more total reps wins).
    def score(h: dict) -> tuple:
        return (h["top_weight"] or 0, h["total_reps"])
    stalls = [l["name"] for l in lifts.values()
              if len(l["history"]) >= 4 and score(l["history"][-1]) <= max(score(h) for h in l["history"][-4:-1])]
    return {"templates": templates, "lifts": sorted(lifts.values(), key=lambda l: l["name"].lower()),
            "stalled": stalls, "sessions_logged": len(sessions),
            "last_session": sessions[-1].date.isoformat() if sessions else None}


# --------------------------------------------------------------------------
# Garmin workout JSON
# --------------------------------------------------------------------------
_STRENGTH = {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5}
_REPS = {"conditionTypeId": 10, "conditionTypeKey": "reps", "displayOrder": 10, "displayable": True}
_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
_ITER = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}
_KG = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}
_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}

WORKOUT_PREFIX = "FA ·"


def workout_name(template: dict) -> str:
    return f"{WORKOUT_PREFIX} {template['name']}"[:60]


def build_garmin_workout(template: dict, rest_seconds: int = 120) -> dict[str, Any]:
    steps: list[dict] = []
    order = 0
    est = 0
    for ex in template["exercises"]:
        nxt = ex["next"]
        g = ex.get("garmin") or {}
        reps_list = nxt["reps"]
        weight = nxt["weight"]
        label = f"{ex['name']}: {weight:g} kg" if weight else f"{ex['name']}: bodyweight"
        # One repeat group per lift when every set has the same target, else one step per set.
        same = len(set(reps_list)) == 1
        groups = [(len(reps_list), reps_list[0])] if same else [(1, r) for r in reps_list]
        for iterations, reps in groups:
            order += 1
            group_order = order
            order += 1
            exercise_step = {
                "type": "ExecutableStepDTO", "stepOrder": order,
                "stepType": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
                "endCondition": _REPS, "endConditionValue": float(reps),
                "targetType": _NO_TARGET,
                "description": f"{label} × {reps}",
            }
            if g.get("category"):
                exercise_step["category"] = g["category"]
                if g.get("name"):
                    exercise_step["exerciseName"] = g["name"]
            if weight:
                exercise_step["weightValue"] = float(weight)
                exercise_step["weightUnit"] = _KG
            order += 1
            rest_step = {
                "type": "ExecutableStepDTO", "stepOrder": order,
                "stepType": {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
                "endCondition": _TIME, "endConditionValue": float(rest_seconds),
                "targetType": _NO_TARGET,
            }
            steps.append({
                "type": "RepeatGroupDTO", "stepOrder": group_order,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                "numberOfIterations": iterations, "smartRepeat": False,
                "endCondition": _ITER, "endConditionValue": float(iterations),
                "workoutSteps": [exercise_step, rest_step],
            })
            est += iterations * (40 + rest_seconds)
    lines = []
    for ex in template["exercises"]:
        nxt = ex["next"]
        w = f"{nxt['weight']:g} kg" if nxt["weight"] else "BW"
        lines.append(f"{ex['name']}: {w} × {'/'.join(str(r) for r in nxt['reps'])}")
    return {
        "workoutName": workout_name(template),
        "description": ("Double progression targets from your gym log.\n" + "\n".join(lines))[:1000],
        "sportType": _STRENGTH,
        "estimatedDurationInSecs": est,
        "workoutSegments": [{"segmentOrder": 1, "sportType": _STRENGTH, "workoutSteps": steps}],
    }


def workout_hash(workout: dict) -> str:
    return hashlib.sha1(json.dumps(workout, sort_keys=True).encode()).hexdigest()[:12]


DESCRIPTION_MARKER = "— lifts logged by fitnessApp"


def activity_description(session: Session) -> str:
    lines = []
    for e in session.exercises:
        sets = ", ".join(f"{s['w']:g}×{s['r']}" if s["w"] else f"BW×{s['r']}" for s in e.sets)
        lines.append(f"{e.name}: {sets}")
    return "\n".join(lines + [DESCRIPTION_MARKER])


def is_ours(description: str | None) -> bool:
    return bool(description) and DESCRIPTION_MARKER in description  # type: ignore[operator]


def session_volume(session: Session) -> float:
    return sum((s["w"] or 0) * s["r"] for e in session.exercises for s in e.sets)

