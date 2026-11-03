"""Food tab settings: meal options, targets and where the site saves the log."""

from fitapp import food
from fitapp.config import load_config
from fitapp.crypto import decrypt_json, encrypt_json


def test_meals_get_stable_ids_and_bad_rows_are_dropped():
    cfg = {"food": {"meals": [{"name": "Skyr + whey", "kcal": 245, "protein": 44, "slots": ["snacks", "brunch"]},
                              {"name": "Skyr + whey", "kcal": 300},          # same id: first wins
                              {"name": "", "kcal": 100}, {"name": "No kcal"},
                              {"name": "Toast", "kcal": "180"}],
                    "targets": {"kcal": [3100, 2850], "protein": 200}}}
    out = food.settings(cfg)
    assert [(m["id"], m["kcal"], m["protein"], m["slots"]) for m in out["meals"]] == [
        ("d-skyr-whey", 245, 44, ["snacks"]), ("d-toast", 180, 0, ["misc"])]   # unknown slot dropped; none -> misc
    assert out["targets"] == {"kcal": [2850, 3100], "protein": [200, 200]}
    assert out["store"] == {"repo": "", "branch": "food-log", "path": "food.enc.json"}


def test_config_defaults_add_up_to_the_planned_day():
    out = food.settings(load_config())
    by_slot = {slot: [m for m in out["meals"] if slot in m["slots"]] for slot in food.SLOTS}
    (granola,), (skyr,) = by_slot["breakfast"], by_slot["snacks"]
    thigh, breast = sorted(by_slot["lunch"], key=lambda m: -m["kcal"])
    assert by_slot["dinner"] == by_slot["lunch"] and by_slot["misc"] == []
    thigh_day = granola["kcal"] + 2 * thigh["kcal"] + skyr["kcal"]
    breast_protein = granola["protein"] + 2 * breast["protein"] + skyr["protein"]
    assert thigh_day == 3075 and breast_protein == 218
    lo, hi = out["targets"]["kcal"]
    assert lo <= thigh_day <= hi


def test_the_site_envelope_format_round_trips():
    # The site seals the log in the same envelope the pipeline uses, so either side can read it.
    log = {"v": 1, "entries": {"a1": {"id": "a1", "date": "2026-11-03", "name": "Skyr + whey", "kcal": 245}}, "meals": {}}
    env = encrypt_json(log, "pass")
    assert set(env) == {"v", "kdf", "iter", "salt", "iv", "ct"} and decrypt_json(env, "pass") == log
