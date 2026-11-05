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
    by_slot = {slot: {m["name"]: m for m in out["meals"] if slot in m["slots"]} for slot in food.SLOTS}
    assert list(by_slot["breakfast"]) == ["Granola (150 g) + milk"]
    assert by_slot["dinner"] == by_slot["lunch"] and by_slot["misc"] == {}
    assert list(by_slot["snacks"]) == ["Skyr bowl (skyr + whey)", "Kakaomælk (200 ml)", "Hot chocolate (250 ml)"]
    granola, skyr = by_slot["breakfast"]["Granola (150 g) + milk"], by_slot["snacks"]["Skyr bowl (skyr + whey)"]
    thigh, breast = by_slot["lunch"]["Potato meal (chicken thigh)"], by_slot["lunch"]["Potato meal (chicken breast)"]
    # 250 g potatoes instead of 330 g: 80 g x 0.77 kcal/g ~ 62 kcal and ~1.5 g protein less per meal.
    assert (1040 - thigh["kcal"], 935 - breast["kcal"]) == (60, 60) and (58 - thigh["protein"], 67 - breast["protein"]) == (2, 2)
    thigh_day = granola["kcal"] + 2 * thigh["kcal"] + skyr["kcal"]
    breast_protein = granola["protein"] + 2 * breast["protein"] + skyr["protein"]
    assert (thigh_day, breast_protein) == (2955, 214)
    lo, hi = out["targets"]["kcal"]
    assert lo <= thigh_day <= hi


class _Resp:
    def __init__(self, body=None, text=None, status=200):
        self.body, self.status_code = body, status

    def json(self):
        if self.body is None:
            raise ValueError("not json")
        return self.body


def test_sheet_check_counts_live_rows_and_explains_failures():
    import requests
    url = "https://script.google.com/macros/s/AKfy-test/exec"
    ok = {"ok": True, "entries": {"a": {"id": "a"}, "b": {"id": "b", "deleted": True}}, "meals": {"m": {"id": "m"}}}
    assert food.check_sheet(url, get=lambda u, timeout: _Resp(ok)) == ("ok", {"entries": 1, "options": 1})
    status, counts = food.check_sheet(url, get=lambda u, timeout: _Resp(None))       # Google's sign-in page
    assert status.startswith("error: not JSON") and "Anyone" in status and counts == {}
    assert food.check_sheet(url, get=lambda u, timeout: _Resp({"ok": False, "error": "That wasn't JSON."}))[0] == "error: That wasn't JSON."

    def boom(u, timeout):
        raise requests.ConnectionError("no route")
    assert food.check_sheet(url, get=boom)[0] == "error: ConnectionError"
