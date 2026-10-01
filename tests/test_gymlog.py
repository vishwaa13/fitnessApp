from datetime import date

import pytest

from fitapp.gymlog import parse_date_line, parse_exercise_line, parse_gym_log, parse_tags_note

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
