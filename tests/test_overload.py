from datetime import date

from fitapp.config import load_config
from fitapp.gymlog import parse_gym_log
from fitapp.overload import (activity_description, build_garmin_workout, build_plan, garmin_exercise,
                             is_ours, progress)

CFG = load_config()["overload"]


def h(*sessions):
    return [{"date": f"2026-09-{i + 1:02d}", "sets": [{"w": w, "r": r} for w, r in s]} for i, s in enumerate(sessions)]


def test_all_sets_at_top_adds_weight():
    nxt = progress(h([(100, 8), (100, 8), (100, 8)]), [5, 8], 5)
    assert nxt["action"] == "add_weight" and nxt["weight"] == 105 and nxt["reps"] == [5, 5, 5]


def test_within_range_adds_a_rep_per_set():
    nxt = progress(h([(100, 6), (100, 7), (100, 8)]), [5, 8], 5)
    assert nxt["action"] == "add_reps" and nxt["weight"] == 100 and nxt["reps"] == [7, 8, 8]


def test_one_miss_holds_then_two_misses_deload():
    assert progress(h([(100, 4), (100, 5)]), [5, 8], 5)["action"] == "hold"
    nxt = progress(h([(100, 4), (100, 5)], [(100, 4), (100, 4)]), [5, 8], 5)
    assert nxt["action"] == "deload" and nxt["weight"] == 90


def test_bodyweight_progression():
    nxt = progress(h([(None, 10), (None, 10)]), [6, 10], 2.5)
    assert nxt["action"] == "add_load" and nxt["weight"] is None


def test_only_top_weight_sets_count_as_working_sets():
    nxt = progress(h([(60, 8), (100, 8), (100, 8)]), [5, 8], 5)
    assert nxt["sets"] == 2 and nxt["weight"] == 105


def test_plan_from_log_rotates_templates_and_uses_rules():
    note = """
22/09 Lower A
Squat 3x8 100
Bulgarian split squat 3x12 16
24/09 Upper A
Bench 80: 8,8,7
29/09 Lower A
Squat 3x8 100
Bulgarian split squat 3x12 16
"""
    plan = build_plan(parse_gym_log(note, today=date(2026, 10, 1)), CFG, date(2026, 10, 1))
    names = [t["name"] for t in plan["templates"]]
    assert names == ["Upper A", "Lower A"] and plan["templates"][0]["up_next"]
    lower = plan["templates"][1]["exercises"]
    squat = next(e for e in lower if e["name"] == "Squat")
    bss = next(e for e in lower if e["name"] == "Bulgarian split squat")
    assert squat["next"]["weight"] == 105          # squat rule: 5-8 reps, +5 kg
    assert bss["rep_range"] == [8, 12] and bss["next"]["weight"] == 18  # dumbbell rule: +2 kg
    assert squat["garmin"] == {"category": "SQUAT", "name": "BARBELL_BACK_SQUAT"}


def test_garmin_mapping_prefers_specific_variants():
    assert garmin_exercise("Front squat")["name"] == "BARBELL_FRONT_SQUAT"
    assert garmin_exercise("RDL")["name"] == "BARBELL_STRAIGHT_LEG_DEADLIFT"
    assert garmin_exercise("Pull-ups")["name"] == "PULL_UP"
    assert garmin_exercise("Cossack squat thing", {"cossack": {"category": "LUNGE", "name": None}})["category"] == "LUNGE"
    assert garmin_exercise("Landmine twist") is None


def test_garmin_workout_shape():
    template = {"name": "Lower A", "exercises": [
        {"name": "Squat", "garmin": {"category": "SQUAT", "name": "BARBELL_BACK_SQUAT"},
         "next": {"weight": 100.0, "reps": [5, 5, 5]}},
        {"name": "Mystery lift", "garmin": None, "next": {"weight": None, "reps": [8, 7]}},
    ]}
    w = build_garmin_workout(template, rest_seconds=90)
    assert w["sportType"]["sportTypeKey"] == "strength_training"
    steps = w["workoutSegments"][0]["workoutSteps"]
    assert [s["numberOfIterations"] for s in steps] == [3, 1, 1]
    squat = steps[0]["workoutSteps"][0]
    assert squat["endCondition"]["conditionTypeKey"] == "reps" and squat["endConditionValue"] == 5
    assert squat["weightValue"] == 100.0 and squat["weightUnit"]["unitKey"] == "kilogram"
    assert squat["exerciseName"] == "BARBELL_BACK_SQUAT"
    mystery = steps[1]["workoutSteps"][0]
    assert "category" not in mystery and "weightValue" not in mystery and "Mystery lift" in mystery["description"]
    assert steps[0]["workoutSteps"][1]["stepType"]["stepTypeKey"] == "rest"
    orders = [steps[0]["stepOrder"]] + [s["stepOrder"] for s in steps[0]["workoutSteps"]] + [steps[1]["stepOrder"]]
    assert orders == sorted(set(orders))


def test_activity_description_marker():
    s = parse_gym_log("29/09\nSquat 3x5 100\nPull-ups 3x8", today=date(2026, 10, 1))[0]
    text = activity_description(s)
    assert text.startswith("Squat: 100×5, 100×5, 100×5\nPull-ups: BW×8")
    assert is_ours(text) and not is_ours("felt strong today")
