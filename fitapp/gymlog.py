"""Parse free-form gym log notes (the Google Keep "gym logs" note).

People write sets in many ways, so the parser accepts all of these:

    29/09 Lower A                 <- date line, optional session title
    Squat 3x5 100kg               sets x reps weight
    Squat 3x5 @ 100 / 100kg 3x5   weight before or after
    Squat 3x5x100 / 100x5x3       triples (order inferred from the numbers)
    Bench 80x8, 80x8, 80x7        weight x reps per set
    Bench 80: 8,8,7 / 80kg 8/8/7  weight then a rep list
    Pull-ups 3x8 / Pull ups bw 8,7,6
    RDL (6-10) 3x8 70             "(6-10)" sets that lift's rep range
    3 sets of 5 at 100kg

and the stacked form where the exercise name sits on its own line followed by
one line per set. Lines it can't read are kept in ``unparsed`` so the dashboard
can show them instead of silently dropping data.

A bare "80 x 8" is ambiguous. With ``set_format="weight_x_reps"`` the first
number is always the weight (so "8 x 15" is 8 kg for 15 and "0 x 5" is
bodyweight); the default "auto" takes the larger number as the weight.

Lines that mention pain ("Left shoulder pain, stopped") are kept as notes on
the session, tied to the lift they came after, for the injury early-warning.
Milder lines ("legs sore") are kept as soreness, the same as the recovery
tags note's "24/10 shoulder 2/5, legs sore".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"]
MONTHS = {m[:3]: i for i, m in enumerate(MONTH_NAMES, 1)}
WEEKDAY = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s*"
NUM = r"\d+(?:[.,]\d+)?"
UNIT = r"(?:kgs?|k|lbs?)\b"
LB_TO_KG = 0.45359237

_ISO_RE = re.compile(r"^\s*(?:" + WEEKDAY + r")?(\d{4})-(\d{1,2})-(\d{1,2})\b(.*)$", re.I)
_NUMERIC_RE = re.compile(
    r"^\s*(?:" + WEEKDAY + r")?(\d{1,2})[./-](\d{1,2})(?:[./-](\d{4}|\d{2}))?(?![\d/x])(.*)$", re.I)
_TEXT_DM_RE = re.compile(
    r"^\s*(?:" + WEEKDAY + r")?(\d{1,2})(?:st|nd|rd|th)?\s*([a-z]{3,9})\.?,?(?:\s+(\d{4}))?\b(.*)$", re.I)
_TEXT_MD_RE = re.compile(
    r"^\s*(?:" + WEEKDAY + r")?([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?(?:\s+(\d{4}))?\b(.*)$", re.I)
_RANGE_RE = re.compile(r"\(\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*\)")
_SET_HINT_RE = re.compile(r"\d\s*[x×*]\s*\d|\d\s*(?:kg|lb)", re.I)

PAIN_RE = re.compile(r"\b(?:pain\w*|hurt\w*|injur\w*|tweak\w*|strain\w*|sprain\w*|pulled|"
                     r"twinge\w*|niggle\w*|ache|aches|aching|achy|pinched|discomfort)\b", re.I)
SORE_RE = re.compile(r"\b(?:sore\w*|stiff\w*|tight\w*|doms|tender)\b", re.I)
FINE_RE = re.compile(r"\b(?:ok|okay|fine|good|better|pain[ -]?free|no pain)\b", re.I)
# Longest first, so "lower back" wins over "back". Values are the name shown.
BODY_PARTS = [
    ("rotator cuff", "shoulder"), ("lower back", "lower back"), ("upper back", "upper back"),
    ("hip flexor", "hip flexor"), ("it band", "IT band"), ("shoulder", "shoulder"), ("knee", "knee"),
    ("hamstring", "hamstring"), ("hammy", "hamstring"), ("glute", "glute"), ("groin", "groin"),
    ("adductor", "adductor"), ("achilles", "achilles"), ("ankle", "ankle"), ("calf", "calf"),
    ("calves", "calf"), ("elbow", "elbow"), ("wrist", "wrist"), ("neck", "neck"), ("quad", "quad"),
    ("chest", "chest"), ("pec", "chest"), ("foot", "foot"), ("shin", "shin"), ("hip", "hip"),
    ("back", "back"), ("bicep", "bicep"), ("tricep", "tricep"), ("forearm", "forearm"), ("trap", "trap"),
    ("hammies", "hamstring"), ("lats", "back"), ("abs", "core"), ("core", "core"),
    ("legs", "legs"), ("leg", "legs"), ("arms", "arms"), ("arm", "arms"),
]

@dataclass
class Exercise:
    name: str
    sets: list[dict] = field(default_factory=list)   # [{"w": float | None, "r": int}]
    rep_range: list[int] | None = None
    raw: list[str] = field(default_factory=list)
    canonical: str | None = None   # set from config aliases, so renamed lifts share a history

    @property
    def key(self) -> str:
        return exercise_key(self.canonical or self.name)


@dataclass
class Session:
    date: date
    title: str | None = None
    exercises: list[Exercise] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)   # pain notes, see pain_note()
    soreness: list[dict] = field(default_factory=list)   # see soreness_entry()

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "title": self.title,
            "exercises": [{"name": e.name, "key": e.key, "sets": e.sets, "rep_range": e.rep_range}
                          for e in self.exercises],
            "unparsed": self.unparsed,
            "notes": self.notes,
            "soreness": self.soreness,
        }


def exercise_key(name: str) -> str:
    """Same key for "Pull-ups", "pull ups" and "Vertical pull cable" / "Cable vertical pull"."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    words = [w[:-1] if len(w) > 2 and w.endswith("s") and not w.endswith("ss") else w for w in words]
    return "".join(sorted(words))


def clean_name(text: str) -> str:
    return re.sub(r"^[\s\-–—:|·,]+|[\s\-–—:|·,]+$", "", text)


def body_part_of(text: str) -> str | None:
    low = text.lower()
    return next((shown for word, shown in BODY_PARTS if re.search(rf"\b{word}s?\b", low)), None)


def side_of(text: str) -> str | None:
    low = text.lower()
    return next((s for s in ("left", "right", "both") if re.search(rf"\b{s}\b", low)), None)


def pain_note(line: str, exercise: str | None) -> dict | None:
    """{"text", "body_part", "side", "exercise", "stopped"} if the line reports pain."""
    if not PAIN_RE.search(line):
        return None
    low = line.lower()
    part, side = body_part_of(line), side_of(line)
    return {"text": line.strip(), "body_part": part, "side": side, "exercise": exercise,
            "stopped": bool(re.search(r"\bstop\w*|\bquit\b|\babandon\w*|\bskipped\b", low))}


def soreness_entry(text: str) -> dict | None:
    """{"body_part", "side", "score" (0-5), "text"} for "shoulder 2/5", "legs sore",
    "left knee 3", "hamstrings ok". A body part needs a score or a word with it."""
    part = body_part_of(text)
    if not part:
        return None
    low = text.lower()
    if m := re.search(r"(\d+(?:[.,]\d)?)\s*/\s*(10|5)\b", low):
        score = float(m[1].replace(",", ".")) * 5 / int(m[2])
    elif m := re.search(r"(?<![\d./])\b([0-5])\b(?![./]\d)", low):
        score = int(m[1])
    elif FINE_RE.search(low):
        score = 0
    elif PAIN_RE.search(low):
        score = 4      # "knee pain" in the soreness note is pain
    elif re.search(r"\b(?:very|really|super|quite)\s+(?:sore|stiff|tight)", low):
        score = 3
    elif SORE_RE.search(low):
        score = 2
    else:
        return None
    return {"body_part": part, "side": side_of(text), "score": round(min(5.0, score), 1), "text": text.strip()}


def _is_month(word: str) -> bool:
    word = word.lower()
    return len(word) >= 3 and any(m.startswith(word) for m in MONTH_NAMES)


def _year_for(month: int, day: int, today: date) -> int:
    """Pick the year that puts a year-less date closest to (and not after) today."""
    year = today.year
    try:
        if date(year, month, day) > today + timedelta(days=2):
            year -= 1
    except ValueError:
        pass
    return year


def parse_date_line(line: str, today: date, order: str = "DMY") -> tuple[date, str] | None:
    """Return (date, rest-of-line) if ``line`` starts with a date."""
    text = line.strip().strip("*#_ ")
    candidates: list[tuple[int, int, int | None, str]] = []
    if m := _ISO_RE.match(text):
        candidates.append((int(m[1]), int(m[2]), int(m[3]), m[4]))
    elif m := _NUMERIC_RE.match(text):
        a, b = int(m[1]), int(m[2])
        day, month = (a, b) if order.upper() == "DMY" else (b, a)
        year = int(m[3]) if m[3] else None
        if year is not None and year < 100:
            year += 2000
        candidates.append((year, month, day, m[4]))  # type: ignore[arg-type]
    elif (m := _TEXT_DM_RE.match(text)) and _is_month(m[2]):
        candidates.append((int(m[3]) if m[3] else None, MONTHS[m[2][:3].lower()], int(m[1]), m[4]))  # type: ignore[arg-type]
    elif (m := _TEXT_MD_RE.match(text)) and _is_month(m[1]):
        candidates.append((int(m[3]) if m[3] else None, MONTHS[m[1][:3].lower()], int(m[2]), m[4]))  # type: ignore[arg-type]
    for year, month, day, rest in candidates:
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        if _SET_HINT_RE.search(rest or ""):
            continue  # "3/10 3x5 100kg" is a set line, not a header
        year = year or _year_for(month, day, today)
        try:
            when = date(year, month, day)
        except ValueError:
            continue
        if when > today + timedelta(days=2):
            continue
        title = re.sub(r"^[\s\-–—:|·,]+|[\s\-–—:|·,]+$", "", rest or "")
        return when, title
    return None


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _normalize(rest: str) -> str:
    s = rest.lower()
    s = s.replace("×", "x").replace("*", "x")
    s = re.sub(r"\bsets?\s+of\b", "x", s)
    s = re.sub(r"\s+at\s+", " @ ", s)
    s = re.sub(r"\brpe\s*\d+(?:[.,]\d)?", " ", s)
    s = re.sub(r"\b(?:reps?|sets?)\b", " ", s)
    # A comma between digits that are not a decimal (5,5,5 or 80,8) is a separator
    s = re.sub(r"(\d),(?=\d{2,}\b|\d\s*[,/]|\d\s*$)", r"\1 , ", s)
    return s


@dataclass
class _Tok:
    kind: str          # "pair" | "triple" | "weight" | "num"
    values: tuple
    units: tuple = ()
    pos: int = 0


def _to_kg(value: float, unit: str | None, target_unit: str) -> float:
    if unit and unit.startswith("lb") and target_unit == "kg":
        return round(value * LB_TO_KG, 2)
    return value


def parse_sets(rest: str, target_unit: str = "kg", set_format: str = "auto") -> tuple[list[dict], bool] | None:
    """Turn the numeric part of an exercise line into sets. None if unreadable."""
    if re.fullmatch(r"\s*\d+\s*sets?\s*", rest, re.I):
        return None  # "4 sets" with no reps: nothing to progress from
    weight_first = set_format == "weight_x_reps"
    s = _normalize(rest)
    if re.search(r"\d\s*x\s*$", s.strip()):
        return None  # "26 x" with no reps: an abandoned set
    if re.search(r"\d\s*(?:s|sec|secs|seconds|min|mins|minutes)\b", s):
        return None  # timed holds/carries aren't rep-progressed
    bodyweight = bool(re.search(r"\bbw\b|bodyweight|body weight", s))
    s = re.sub(r"\bbw\b|bodyweight|body weight", " ", s)
    toks: list[_Tok] = []
    consumed = [False] * len(s)

    def take(m: re.Match) -> None:
        for i in range(m.start(), m.end()):
            consumed[i] = True

    triple = re.compile(rf"({NUM})\s*({UNIT})?\s*x\s*({NUM})\s*({UNIT})?\s*x\s*({NUM})\s*({UNIT})?")
    for m in triple.finditer(s):
        toks.append(_Tok("triple", (_num(m[1]), _num(m[3]), _num(m[5])), (m[2], m[4], m[6]), m.start()))
        take(m)
    masked = "".join(" " if consumed[i] else ch for i, ch in enumerate(s))
    pair = re.compile(rf"({NUM})\s*({UNIT})?\s*x\s*({NUM})\s*({UNIT})?")
    for m in pair.finditer(masked):
        toks.append(_Tok("pair", (_num(m[1]), _num(m[3])), (m[2], m[4]), m.start()))
        take(m)
    masked = "".join(" " if consumed[i] else ch for i, ch in enumerate(s))
    for m in re.finditer(rf"@\s*({NUM})\s*({UNIT})?|({NUM})\s*({UNIT})", masked):
        if m[1]:
            toks.append(_Tok("weight", (_num(m[1]),), (m[2],), m.start()))
        else:
            toks.append(_Tok("weight", (_num(m[3]),), (m[4],), m.start()))
        take(m)
    masked = "".join(" " if consumed[i] else ch for i, ch in enumerate(s))
    for m in re.finditer(NUM, masked):
        toks.append(_Tok("num", (_num(m[0]),), (), m.start()))
    toks.sort(key=lambda t: t.pos)
    if not toks:
        return None

    has_weight_tok = any(t.kind == "weight" for t in toks)
    nums = [t for t in toks if t.kind == "num"]
    pairs = [t for t in toks if t.kind == "pair"]
    # No explicit weight: a bare number in front of a rep list (or next to a
    # sets x reps pair) is the weight - "80: 8,8,7", "80 8 8 7", "3x5 100".
    if not has_weight_tok and not bodyweight and nums:
        if pairs and all(max(p.values) <= 30 for p in pairs) and (
                not weight_first or min(t.values[0] for t in nums) > max(max(p.values) for p in pairs)):
            # "3x5 100" / "2x8 80, 1x6 85": the pairs are sets x reps, so
            # every bare number is a weight. (Weight-first notes only when the
            # bare numbers are bigger: "15 x 4, 8" is 15 kg x 4 then 8 reps.)
            for t in nums:
                t.kind, t.units = "weight", (None,)
            has_weight_tok = True
        elif not pairs:
            first, others = nums[0], nums[1:]
            v = first.values[0]
            if v > 30 or v % 1 != 0 or (others and v > max(t.values[0] for t in others)):
                first.kind, first.units = "weight", (None,)
                has_weight_tok = True

    sets: list[dict] = []
    weight_toks = [t for t in toks if t.kind == "weight"]

    def weight_near(pos: int) -> float | None:
        after = [t for t in weight_toks if t.pos > pos]
        before = [t for t in weight_toks if t.pos < pos]
        tok = after[0] if after else (before[-1] if before else None)
        return None if tok is None else _to_kg(tok.values[0], tok.units[0], target_unit)

    current_w: float | None = None
    for tok in toks:
        if tok.kind == "weight":
            current_w = _to_kg(tok.values[0], tok.units[0], target_unit)
        elif tok.kind == "triple":
            a, b, c = tok.values
            ua, _ub, uc = tok.units
            if ua or (a > c and c <= 10 and not uc):
                w, reps, n = _to_kg(a, ua, target_unit), b, c
            else:
                n, reps, w = a, b, _to_kg(c, uc, target_unit)
            sets += [{"w": w, "r": int(reps)} for _ in range(int(n))]
            current_w = w
        elif tok.kind == "pair":
            a, b = tok.values
            ua, ub = tok.units
            if ua:
                w, reps = _to_kg(a, ua, target_unit), b
                sets.append({"w": w, "r": int(reps)})
                current_w = w
            elif ub:
                w, reps = _to_kg(b, ub, target_unit), a
                sets.append({"w": w, "r": int(reps)})
                current_w = w
            elif has_weight_tok or bodyweight or (not weight_first and len(pairs) == 1
                                                  and 0 < a <= 6 and b <= 30 and a % 1 == 0):
                # sets x reps, weight comes from elsewhere on the line (or bodyweight)
                w = None if bodyweight else weight_near(tok.pos)
                sets += [{"w": w, "r": int(b)} for _ in range(int(a))]
            elif weight_first or a == 0:
                w, reps = a or None, b  # a weight of 0 is bodyweight
                sets.append({"w": w, "r": int(reps)})
                current_w = w
            else:
                w, reps = (a, b) if a >= b else (b, a)
                sets.append({"w": w, "r": int(reps)})
                current_w = w
        elif tok.kind == "num":
            reps = tok.values[0]
            if reps % 1 or reps > 60:
                return None
            sets.append({"w": None if bodyweight else current_w, "r": int(reps)})

    if not sets or any(st["r"] <= 0 or st["r"] > 100 for st in sets) or len(sets) > 20:
        return None
    return sets, bodyweight


def parse_exercise_line(line: str, unit: str = "kg",
                        set_format: str = "auto") -> tuple[str | None, list[dict], list[int] | None] | None:
    """Return (name or None for a continuation line, sets, rep_range)."""
    s = line.strip().lstrip("-•*·>").strip()
    rep_range = None
    if m := _RANGE_RE.search(s):
        lo, hi = sorted((int(m[1]), int(m[2])))
        rep_range = [lo, hi]
        s = (s[:m.start()] + " " + s[m.end():]).strip()
    m = re.search(r"\d|\bbw\b|\bbodyweight\b|@", s, re.I)
    if not m:
        return None
    name = clean_name(s[:m.start()]).rstrip("(").strip()
    parsed = parse_sets(s[m.start():], unit, set_format)
    if parsed is None:
        return None
    sets, _ = parsed
    return (name or None), sets, rep_range


def parse_gym_log(text: str, today: date | None = None, order: str = "DMY", unit: str = "kg",
                  set_format: str = "auto", aliases: dict[str, list[str]] | None = None) -> list[Session]:
    """``aliases`` maps a lift's name to other names you've logged it under."""
    today = today or date.today()
    canonical = {exercise_key(alt): name for name, alts in (aliases or {}).items() for alt in (alts or [])}
    sessions: list[Session] = []
    current: Session | None = None
    pending_name: str | None = None

    def exercise(name: str, sets: list[dict], rep_range: list[int] | None, line: str) -> Exercise:
        return Exercise(name, list(sets), rep_range, [line], canonical.get(exercise_key(name)))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= set("-=_*#~ "):
            continue
        hdr = parse_date_line(line, today, order)
        if hdr:
            when, title = hdr
            current = Session(date=when, title=title or None)
            sessions.append(current)
            pending_name = None
            continue
        if current is None:
            continue  # text before the first date (note intro, etc.)
        note = pain_note(line, pending_name or (current.exercises[-1].name if current.exercises else None))
        if note:
            current.notes.append(note)
            continue
        if SORE_RE.search(line) and not re.search(r"\d\s*x\s*\d", line, re.I) and (sore := soreness_entry(line)):
            current.soreness.append(sore)
            continue
        parsed = parse_exercise_line(line, unit, set_format)
        if parsed is None:
            if not re.search(r"\d", line) and len(line) <= 60:
                # A name on its own line: session title right after the date,
                # otherwise the exercise the next set lines belong to.
                name = clean_name(line)
                if not current.exercises and pending_name is None and current.title is None:
                    pending_name = name
                    continue
                if pending_name and not current.exercises and current.title is None:
                    current.title = pending_name
                pending_name = name
            else:
                bare = pending_name and re.match(r"\d", line)
                current.unparsed.append(f"{pending_name}: {line}" if bare else line)
            continue
        name, sets, rep_range = parsed
        if name is None:
            target_name = pending_name
            if target_name is None and current.exercises:
                current.exercises[-1].sets.extend(sets)
                current.exercises[-1].raw.append(line)
                continue
            if target_name is None:
                current.unparsed.append(line)
                continue
            existing = next((e for e in current.exercises if e.name == target_name), None)
            if existing:
                existing.sets.extend(sets)
                existing.raw.append(line)
            else:
                current.exercises.append(exercise(target_name, sets, rep_range, line))
            continue
        if pending_name and not current.exercises and current.title is None:
            current.title = pending_name
        pending_name = None
        current.exercises.append(exercise(name, sets, rep_range, line))
    # Same date twice (e.g. "AM"/"PM" blocks) stays as two sessions; empty headers go.
    return sorted([s for s in sessions if s.exercises or s.notes or s.soreness], key=lambda s: s.date)


_DRINK_RE = re.compile(r"\b(beer|pint|lager|ipa|wine|prosecco|champagne|cider|cocktail|shot|spirit|gin|vodka|"
                       r"whisk(?:e?y)?|rum|tequila|drink|booze|alcohol)(?:e?s)?\b")
_DRINK_KIND = {"pint": "beer", "lager": "beer", "ipa": "beer", "prosecco": "wine", "champagne": "wine",
               "shot": "spirits", "spirit": "spirits", "gin": "spirits", "vodka": "spirits", "rum": "spirits",
               "tequila": "spirits", "whisky": "spirits", "whiskey": "spirits", "whisk": "spirits",
               "drink": "drinks", "booze": "drinks", "alcohol": "drinks"}


def drink_entry(text: str) -> tuple[str, float | None] | None:
    """("beer", 3) for "3 beers", ("wine", None) for "wine", None if it isn't about drinking."""
    m = _DRINK_RE.search(text.lower())
    if not m:
        return None
    n = re.search(r"\d+(?:[.,]\d)?", text)
    return _DRINK_KIND.get(m[1], m[1]), (float(n[0].replace(",", ".")) if n else None)


def parse_drinks(text: str, today: date | None = None, order: str = "DMY") -> dict[str, dict[str, float]]:
    """Drinks with an amount from "27/10 3 beers, wine 2" lines: {"2026-10-27": {"beer": 3, "wine": 2}}."""
    today = today or date.today()
    out: dict[str, dict[str, float]] = {}
    for raw in text.splitlines():
        hdr = parse_date_line(raw, today, order)
        if not hdr:
            continue
        when, rest = hdr
        for part in re.split(r"[,;+]|\band\b", rest):
            entry = drink_entry(part)
            if entry and entry[1]:
                day = out.setdefault(when.isoformat(), {})
                day[entry[0]] = day.get(entry[0], 0) + entry[1]
    return out


def parse_tags_note(text: str, today: date | None = None, order: str = "DMY") -> dict[str, list[str]]:
    """Parse "27/09 alcohol, travel" lines into {"2026-09-27": ["alcohol", "travel"]}."""
    today = today or date.today()
    out: dict[str, list[str]] = {}
    for raw in text.splitlines():
        hdr = parse_date_line(raw, today, order)
        if not hdr:
            continue
        when, rest = hdr
        tags = []
        pieces = [x for part in re.split(r"[,;+]|\band\b", rest.lower()) if not soreness_entry(part)
                  for x in part.split("/")]
        for part in pieces:
            word = re.sub(r"[^a-z ]+", " ", part).strip()
            word = re.sub(r"\s+", "_", word)
            if drink_entry(part):
                word = "alcohol"
            if word in {"flight", "flew", "travelled", "traveled", "trip"}:
                word = "travel"
            if word:
                tags.append(word)
        for t in tags:
            day = out.setdefault(when.isoformat(), [])
            if t not in day:
                day.append(t)
    return out


def parse_soreness(text: str, today: date | None = None, order: str = "DMY") -> list[dict]:
    """Soreness from "24/10 shoulder 2/5, legs sore" lines, oldest first."""
    today = today or date.today()
    out = []
    for raw in text.splitlines():
        hdr = parse_date_line(raw, today, order)
        if not hdr:
            continue
        when, rest = hdr
        for part in re.split(r"[,;+]|\band\b", rest):
            if entry := soreness_entry(part):
                out.append({"date": when.isoformat(), **entry})
    return sorted(out, key=lambda e: e["date"])
