"""Food tab settings: meal options, targets and where the site saves the log."""

from fitapp import food
from fitapp.config import load_config


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
    assert out["store"] == {"url": ""}


def test_sheet_url_comes_from_the_secret_and_never_reaches_the_public_demo(monkeypatch):
    url = "https://script.google.com/macros/s/AKfy-test/exec"
    assert food.settings({}, f" {url}\n")["store"]["url"] == url
    assert food.settings({}, "https://evil.example/exec")["store"]["url"] == ""      # only Apps Script web apps
    from fitapp import demo
    monkeypatch.setenv("FOOD_SHEET_URL", url)
    assert demo.build(load_config())["food"]["store"]["url"] == ""


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
