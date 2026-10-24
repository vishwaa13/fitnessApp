from datetime import date

import pytest

from fitapp.gymlog import (parse_date_line, parse_exercise_line, parse_gym_log, parse_soreness,
                           parse_tags_note, soreness_entry)

TODAY = date(2026, 10, 1)


def sets(*pairs):
    return [{"w": w, "r": r} for w, r in pairs]


@pytest.mark.parametrize("line,expected", [
    ("Squat 3x5 100kg", sets((100, 5), (100, 5), (100, 5))),
    ("Squat 3x5 @ 100", sets((100, 5), (100, 5), (100, 5))),
    ("Squat 100kg 3x5", sets((100, 5), (100, 5), (100, 5))),
    ("Squat 3x5x100", sets((100, 5), (100, 5), (100, 5))),
    ("Squat 100x5x3", sets((100, 5), (100, 5), (100, 5))),
    ("Squat 3x5 100", sets((100, 5), (100, 5), (100, 5))),
    ("Squat - 3 sets of 5 at 100kg", sets((100, 5), (100, 5), (100, 5))),
    ("Bench 80x8, 80x8, 80x7", sets((80, 8), (80, 8), (80, 7))),
    ("Bench 80: 8,8,7", sets((80, 8), (80, 8), (80, 7))),
    ("Bench 80kg 8/8/7", sets((80, 8), (80, 8), (80, 7))),
    ("Bench 80 8 8 7", sets((80, 8), (80, 8), (80, 7))),
    ("Bench 2x8 80, 1x6 85", sets((80, 8), (80, 8), (85, 6))),
    ("Bench 82,5kg 3x8", sets((82.5, 8), (82.5, 8), (82.5, 8))),
    ("Squat 100kg x 5, 5, 5", sets((100, 5), (100, 5), (100, 5))),
    ("Squat 3x5 100 rpe 8", sets((100, 5), (100, 5), (100, 5))),
    ("Pull-ups 3x8", sets((None, 8), (None, 8), (None, 8))),
    ("Pull ups bw 8,7,6", sets((None, 8), (None, 7), (None, 6))),
    ("DB press 22.5kg 3x10", sets((22.5, 10), (22.5, 10), (22.5, 10))),
    ("Hip thrust 100 x 10 x 3", sets((100, 10), (100, 10), (100, 10))),
])
def test_set_formats(line, expected):
    name, got, _ = parse_exercise_line(line)
    assert name and got == expected


def test_pounds_convert_to_kg():
    _, got, _ = parse_exercise_line("Squat 225lbs 3x5")
    assert got[0]["w"] == pytest.approx(102.06, abs=0.01)


def test_rep_range_annotation():
    name, got, rng = parse_exercise_line("RDL (6-10) 3x8 70")
    assert name == "RDL" and rng == [6, 10] and len(got) == 3


def test_timed_sets_are_not_reps():
    assert parse_exercise_line("Plank 3x60s") is None


@pytest.mark.parametrize("line,expected", [
    ("29/09 Lower A", (date(2026, 9, 29), "Lower A")),
    ("Mon 29/09 - Lower A", (date(2026, 9, 29), "Lower A")),
    ("2026-09-25", (date(2026, 9, 25), "")),
    ("1 Oct 2026", (date(2026, 10, 1), "")),
    ("Sep 28: upper", (date(2026, 9, 28), "upper")),
    ("15/12", (date(2025, 12, 15), "")),  # no year and in the future -> last year
])
def test_date_lines(line, expected):
    assert parse_date_line(line, TODAY) == expected


def test_set_line_is_not_a_date():
    assert parse_date_line("3/10 3x5 100kg", TODAY) is None


def test_full_note_with_stacked_sets_and_titles():
    note = """GYM LOGS
Mon 29/09 - Lower A
Squat 3x5 100kg
Plank 3x60s

1 Oct 2026
Upper
Bench
80x8
80x7
Pull ups bw 8,7,6
"""
    sessions = parse_gym_log(note, today=TODAY)
    assert [s.date for s in sessions] == [date(2026, 9, 29), date(2026, 10, 1)]
    lower, upper = sessions
    assert lower.title == "Lower A" and lower.unparsed == ["Plank 3x60s"]
    assert upper.title == "Upper"
    assert upper.exercises[0].name == "Bench" and len(upper.exercises[0].sets) == 2
    assert upper.exercises[1].key == "pullup"


def test_tags_note():
    tags = parse_tags_note("27/09 alcohol, travel\n28 Sep beers + late dinner", today=TODAY)
    assert tags == {"2026-09-27": ["alcohol", "travel"], "2026-09-28": ["alcohol", "late_dinner"]}


@pytest.mark.parametrize("line,expected", [
    ("4sept", (date(2026, 9, 4), "")),
    ("Sept 26", (date(2026, 9, 26), "")),
    ("12 October", (date(2025, 10, 12), "")),  # TODAY is 1 Oct 2026
])
def test_more_date_lines(line, expected):
    assert parse_date_line(line, TODAY) == expected


@pytest.mark.parametrize("line", ["Decline 3x5", "5 reps", "Junk 3", "10 sec"])
def test_words_that_start_like_months_are_not_dates(line):
    assert parse_date_line(line, TODAY) is None


@pytest.mark.parametrize("line,expected", [
    ("Lateral raises 8 X 15", sets((8, 15))),
    ("Pull ups 0 X 5", sets((None, 5))),
    ("Pull ups 15 X 6, 15 X 5", sets((15, 6), (15, 5))),
    ("Chin ups 15 X 4, 8", sets((15, 4), (15, 8))),
    ("Squat 3x8 100", sets((100, 8), (100, 8), (100, 8))),   # bare number bigger than the pair: a weight
    ("Squat 3x5 100kg", sets((100, 5), (100, 5), (100, 5))),
])
def test_weight_first_notes(line, expected):
    _, got, _ = parse_exercise_line(line, set_format="weight_x_reps")
    assert got == expected


def test_auto_format_reads_zero_as_bodyweight():
    assert parse_exercise_line("Step ups 0 x 10")[1] == sets((None, 10))


@pytest.mark.parametrize("line", ["Incline press 26 X", "Nordic curls 4 sets"])
def test_abandoned_or_rep_less_sets_are_not_read(line):
    assert parse_exercise_line(line, set_format="weight_x_reps") is None


def test_stacked_log_with_pain_note():
    note = """23 October
Squats
60 X 10
100 X 4

Incline dumbbell bench press
26 X
Left shoulder pain, stopped

Pull ups -
0 X 5
15 X 6
"""
    s, = parse_gym_log(note, today=date(2026, 10, 23), set_format="weight_x_reps")
    assert [e.name for e in s.exercises] == ["Squats", "Pull ups"]
    assert s.exercises[1].sets == sets((None, 5), (15, 6))
    assert s.unparsed == ["Incline dumbbell bench press: 26 X"]
    assert s.notes == [{"text": "Left shoulder pain, stopped", "body_part": "shoulder", "side": "left",
                        "exercise": "Incline dumbbell bench press", "stopped": True}]


def test_session_with_only_a_pain_note_is_kept():
    s, = parse_gym_log("2/10\nLower back pain after cleans", today=TODAY)
    assert s.notes[0]["body_part"] == "lower back" and s.notes[0]["side"] is None


def test_sore_lines_in_the_gym_log_are_soreness_not_pain():
    s, = parse_gym_log("30/09\nSquat 3x5 100\nLegs sore from frisbee", today=TODAY)
    assert s.notes == [] and s.soreness[0]["body_part"] == "legs" and s.soreness[0]["score"] == 2


@pytest.mark.parametrize("text,part,side,score", [
    ("shoulder 2/5", "shoulder", None, 2),
    ("quads 7/10", "quad", None, 3.5),
    ("left knee 3", "knee", "left", 3),
    ("hamstrings ok", "hamstring", None, 0),
    ("shoulder very sore", "shoulder", None, 3),
    ("right knee pain", "knee", "right", 4),
])
def test_soreness_entries(text, part, side, score):
    e = soreness_entry(text)
    assert (e["body_part"], e["side"], e["score"]) == (part, side, score)


def test_soreness_note_and_tags_share_lines():
    note = "29/09 shoulder 2/5, legs sore, alcohol\n30/09 back from the airport, travel"
    sore = parse_soreness(note, today=TODAY)
    assert [(e["date"], e["body_part"]) for e in sore] == [("2026-09-29", "shoulder"), ("2026-09-29", "legs")]
    assert parse_tags_note(note, today=TODAY)["2026-09-29"] == ["alcohol"]
    assert "travel" in parse_tags_note(note, today=TODAY)["2026-09-30"]   # "back" alone isn't soreness


def test_keys_ignore_word_order_and_plurals_and_follow_aliases():
    note = "28/09\nVertical pull cable 70x8\nBarbell bench press 70x7\n30/09\nCable vertical pull 75x5\nBench press 70x8\n"
    a, b = parse_gym_log(note, today=TODAY, aliases={"Bench press": ["Barbell bench press"]})
    assert a.exercises[0].key == b.exercises[0].key
    assert a.exercises[1].key == b.exercises[1].key
    assert a.exercises[1].name == "Barbell bench press"   # the name you wrote is kept
