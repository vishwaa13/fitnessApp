"""Injury early-warning: the load patterns that tend to come before a strain.

Checks: pain and soreness you noted, acute:chronic workload ratio (7-day load
vs 28-day weekly average), rest days, back-to-back high-load days, Foster's
training monotony, HRV sitting under baseline, gym sets per body part jumping
above their 4-week average, the first session back after a break, and alcohol.
Past injuries from config, and pain notes from the gym log, get the same scan
for the day before them, so you can see whether today looks like then.
"""

from __future__ import annotations

import dataclasses
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import gymload
from .gymlog import Session, exercise_key
from .util import d, has_keyword, rnd

LEVELS = {"ok": 0, "caution": 1, "high": 2}


@dataclass
class Signals:
    """What the gym log, soreness notes and alcohol tags add to the load scan."""
    pain: list[dict] = field(default_factory=list)            # pain_reports()
    sets: dict[str, dict[date, int]] = field(default_factory=dict)   # gymload.daily_sets()
    soreness: list[dict] = field(default_factory=list)        # gymlog.parse_soreness()
    alcohol: set[date] = field(default_factory=set)           # evenings with alcohol


def daily_load(activities: list[dict], start: date, end: date) -> dict[date, float]:
    loads = {start + timedelta(days=k): 0.0 for k in range((end - start).days + 1)}
    for a in activities:
        day = d(a["date"])
        if start <= day <= end:
            loads[day] += a.get("load") or 0
    return loads


def _label(side: str | None, part: str | None, what: str) -> str:
    where = " ".join(x for x in (side, part) if x)
    return (where[:1].upper() + where[1:] + " " + what) if where else what.capitalize()


def pain_reports(sessions: list[Session], cfg: dict, today: date, soreness: list[dict] | None = None,
                 sets: dict[str, dict[date, int]] | None = None) -> list[dict]:
    """Pain notes from the gym log, and soreness of 4/5 or more, in the last year, newest first."""
    hold = int(cfg.get("pain_hold_days", 14))
    break_days = int(cfg.get("break_days", 14))
    found = [(s.date, n) for s in sessions for n in s.notes]
    found += [(d(e["date"]), {"text": e["text"], "body_part": e["body_part"], "side": e["side"],
                              "exercise": None, "stopped": False, "score": e["score"]})
              for e in soreness or [] if e["score"] >= 4]
    out = []
    for day, n in found:
        ago = (today - day).days
        if not 0 <= ago <= 365:
            continue
        part = n.get("body_part")
        report = {**n, "date": day.isoformat(), "days_ago": ago,
                  "label": _label(n.get("side"), part, f"soreness {n['score']:g}/5" if "score" in n else "pain"),
                  "active": ago < hold, "until": (day + timedelta(days=hold)).isoformat(),
                  "affects": list((cfg.get("pain_affects") or {}).get(part or "", [])), "returning": None}
        trained = sorted(x for x in (sets or {}).get(part or "", {}) if x < day)
        if part and day in (sets or {}).get(part, {}) and trained and (day - trained[-1]).days >= break_days:
            report["returning"] = {"gap": (day - trained[-1]).days, "last": trained[-1].isoformat()}
        out.append(report)
    return sorted(out, key=lambda r: r["date"], reverse=True)


def pain_hits(name: str, reports: list[dict]) -> dict | None:
    """The newest active pain report that should hold back the lift called ``name``."""
    key = exercise_key(name)
    for r in reports:
        if r["active"] and (has_keyword(name.replace("-", " "), r["affects"])
                            or (r.get("exercise") and exercise_key(r["exercise"]) == key)):
            return r
    return None


def _ago(n: int) -> str:
    return "today" if n == 0 else "yesterday" if n == 1 else f"{n} days ago"


def _short(day: date) -> str:
    return f"{day.day} {day:%b}"


def _pain_flags(pain: list[dict], day: date, hold: int) -> list[tuple[str, str, str]]:
    flags, seen = [], set()
    for p in sorted(pain, key=lambda r: r["date"], reverse=True):
        ago = (day - d(p["date"])).days
        if not 0 <= ago < hold or p["label"] in seen:
            continue
        seen.add(p["label"])
        ex = p.get("exercise") or ""
        during = f" during {ex if ex[:2].isupper() else ex[:1].lower() + ex[1:]}" if ex else ""
        stopped = " (you stopped)" if p.get("stopped") else ""
        flags.append(("pain", "high" if ago < 7 else "caution", f"{p['label']} {_ago(ago)}{during}{stopped}"))
    return flags


def _volume_flag(sets: dict[str, dict[date, int]], day: date, cfg: dict) -> tuple[str, str, str] | None:
    first = min((x for days in sets.values() for x in days), default=None)
    if first is None or (day - first).days < 28:
        return None   # the log needs four weeks before "above your average" means anything
    worst = None
    for row in gymload.volume(sets, day):
        if row["part"] in cfg.get("volume_ignore", []):
            continue
        acute, ratio = row["acute"], row["ratio"]
        level = None
        if ratio is not None and acute >= cfg["volume_min_sets"]:
            if ratio >= cfg["volume_ratio_high"] and acute >= 1.5 * cfg["volume_min_sets"]:
                level = "high"
            elif ratio >= cfg["volume_ratio_caution"]:
                level = "caution"
        if level:
            text = f"{row['part'].capitalize()}: {acute} hard sets this week, {ratio:.1f}× your 4-week average"
        elif acute >= cfg["weekly_sets_caution"]:
            level, text = "caution", f"{row['part'].capitalize()}: {acute} hard sets this week"
        else:
            continue
        rank = (LEVELS[level], ratio or 0, acute)
        if worst is None or rank > worst[0]:
            worst = (rank, ("volume", level, text))
    return worst[1] if worst else None


def _return_flag(sets: dict[str, dict[date, int]], day: date, cfg: dict) -> tuple[str, str, str] | None:
    back = [r for r in gymload.returns(sets, day, int(cfg.get("break_days", 14)))
            if r["part"] not in cfg.get("volume_ignore", [])]
    if not back:
        return None
    latest = back[-1]["date"]
    same = [r for r in back if r["date"] == latest]
    what = "/".join(r["part"] for r in same) if len(same) <= 3 else "gym"
    gap = max(r["gap"] for r in same)
    return ("return", "caution", f"{_short(d(latest))} was your first {what} session in {gap} days: "
                                 "keep the next two sessions lighter")


def _soreness_flag(soreness: list[dict], day: date, cfg: dict) -> tuple[str, str, str] | None:
    flag_at = cfg["soreness_flag_score"]
    recent = [e for e in soreness if 0 <= (day - d(e["date"])).days <= 1 and flag_at <= e["score"] < 4]
    if recent:
        e = max(recent, key=lambda x: (x["score"], x["date"]))
        return ("soreness", "caution",
                f"{_label(e['side'], e['body_part'], 'soreness')} {e['score']:g}/5 {_ago((day - d(e['date'])).days)}")
    days_sore: dict[str, set[str]] = {}
    for e in soreness:
        if 0 <= (day - d(e["date"])).days < 5 and e["score"] >= 2:
            days_sore.setdefault(e["body_part"], set()).add(e["date"])
    part, dates = max(days_sore.items(), key=lambda kv: len(kv[1]), default=(None, set()))
    if len(dates) >= 3:
        return ("soreness", "caution", f"{part.capitalize()} sore on {len(dates)} of the last 5 days")
    return None


def _alcohol_flag(alcohol: set[date], day: date, cfg: dict) -> tuple[str, str, str] | None:
    week = sum(1 for k in range(7) if day - timedelta(days=k) in alcohol)
    last_night = (day - timedelta(days=1)) in alcohol
    if last_night and week >= cfg["alcohol_nights_caution"]:
        text = f"Alcohol last night, and on {week} of the last 7 evenings"
    elif last_night:
        text = "Alcohol last night: recovery is slower, so go easy on sprints and heavy lifts"
    elif week >= cfg["alcohol_nights_caution"]:
        text = f"Alcohol on {week} of the last 7 evenings"
    else:
        return None
    return ("alcohol", "caution", text)


def scan(loads: dict[date, float], hrv_rows: dict[date, dict], day: date, cfg: dict,
         signals: Signals | None = None) -> dict[str, Any]:
    """Risk flags as of the end of ``day``."""
    sig = signals or Signals()
    last7 = [loads.get(day - timedelta(days=k), 0.0) for k in range(7)][::-1]
    last14 = [loads.get(day - timedelta(days=k), 0.0) for k in range(14)][::-1]
    last28 = [loads.get(day - timedelta(days=k), 0.0) for k in range(28)]
    acute = sum(last7)
    chronic = sum(last28) / 4
    acwr = acute / chronic if chronic > 0 else None
    rest7 = sum(v < cfg["rest_day_load"] for v in last7)
    rest14 = sum(v < cfg["rest_day_load"] for v in last14)
    high = [v >= cfg["high_day_load"] for v in last7]
    b2b = sum(1 for i in range(1, 7) if high[i] and high[i - 1])
    three_in_row = any(high[i] and high[i - 1] and high[i - 2] for i in range(2, 7))
    sd = statistics.pstdev(last7)
    monotony = (statistics.fmean(last7) / sd) if sd > 0 else None
    low_hrv = 0
    seen = 0
    for k in range(5):
        r = hrv_rows.get(day - timedelta(days=k))
        if r and r.get("hrv") is not None and r.get("hrv_low") is not None:
            seen += 1
            low_hrv += r["hrv"] < r["hrv_low"]

    flags = _pain_flags(sig.pain, day, int(cfg.get("pain_hold_days", 14)))
    if acwr is not None and chronic >= 50:
        if acwr >= cfg["acwr_high"]:
            flags.append(("acwr", "high", f"Load spike: last 7 days are {acwr:.2f}× your 4-week average"))
        elif acwr >= cfg["acwr_caution"]:
            flags.append(("acwr", "caution", f"Load climbing: {acwr:.2f}× your 4-week average"))
    if rest7 == 0:
        flags.append(("rest", "high", "No rest day in the last 7 days"))
    elif rest14 <= 1:
        flags.append(("rest", "caution", f"Only {rest14} rest day in 14 days"))
    if three_in_row or b2b >= 2:
        flags.append(("b2b", "high", "Three high-intensity days in a row" if three_in_row
                      else f"{b2b} back-to-back high-intensity pairs this week"))
    elif b2b == 1:
        flags.append(("b2b", "caution", "Back-to-back high-intensity days this week"))
    if monotony is not None and monotony >= cfg["monotony_caution"] and acute > 0:
        flags.append(("monotony", "caution", f"Training monotony {monotony:.1f}: every day looks the same"))
    if seen >= 3 and low_hrv >= 3:
        flags.append(("hrv", "caution", f"HRV under baseline on {low_hrv} of the last {seen} mornings"))
    for extra in (_volume_flag(sig.sets, day, cfg), _return_flag(sig.sets, day, cfg),
                  _soreness_flag(sig.soreness, day, cfg), _alcohol_flag(sig.alcohol, day, cfg)):
        if extra:
            flags.append(extra)

    highs = sum(f[1] == "high" for f in flags)
    cautions = sum(f[1] == "caution" for f in flags)
    risk = "high" if highs or cautions >= 3 else "moderate" if cautions else "low"
    return {
        "date": day.isoformat(), "risk": risk,
        "flags": [{"key": k, "level": lvl, "text": txt} for k, lvl, txt in flags],
        "acute": rnd(acute, 0), "chronic": rnd(chronic, 0), "acwr": rnd(acwr, 2),
        "rest_days_7": rest7, "rest_days_14": rest14, "back_to_back": b2b,
        "monotony": rnd(monotony, 2),
        "alcohol_7": sum(1 for k in range(7) if day - timedelta(days=k) in sig.alcohol),
    }


def soreness_grid(soreness: list[dict], today: date, days: int = 14) -> dict[str, Any]:
    """Highest score per body part per day for the last ``days`` days."""
    dates = [today - timedelta(days=k) for k in range(days - 1, -1, -1)]
    grid: dict[str, list] = {}
    for e in soreness:
        day = d(e["date"])
        if dates[0] <= day <= today:
            row = grid.setdefault(e["body_part"], [None] * days)
            i = (day - dates[0]).days
            row[i] = e["score"] if row[i] is None else max(row[i], e["score"])
    order = gymload.ORDER
    rows = [{"part": p, "scores": grid[p]} for p in sorted(grid, key=lambda p: order.index(p) if p in order else 99)]
    return {"dates": [x.isoformat() for x in dates], "rows": rows}


def build(activities: list[dict], daily: list[dict], cfg: dict, today: date,
          signals: Signals | None = None) -> dict[str, Any]:
    start = today - timedelta(days=400)
    loads = daily_load(activities, start, today)
    hrv_rows = {d(r["date"]): r for r in daily}
    sig = signals or Signals()
    current = scan(loads, hrv_rows, today, cfg, sig)

    weeks = []
    for w in range(11, -1, -1):
        end = today - timedelta(days=7 * w)
        s = scan(loads, hrv_rows, end, cfg, sig)
        weeks.append({"week_ending": end.isoformat(), "load": s["acute"], "acwr": s["acwr"],
                      "rest_days": s["rest_days_7"], "back_to_back": s["back_to_back"],
                      "monotony": s["monotony"], "risk": s["risk"], "flags": [f["key"] for f in s["flags"]]})

    # Past injuries from config, plus the first day of each pain in the gym log.
    past = [(d(inj["date"]), inj.get("label", "Injury"), "config") for inj in cfg.get("history") or []]
    for p in sorted(sig.pain, key=lambda r: r["date"]):
        when = d(p["date"])
        if not any(lbl == p["label"] and 0 <= (when - w).days < 21 for w, lbl, _ in past):
            past.append((when, p["label"], "gym log"))
    no_pain = dataclasses.replace(sig, pain=[])
    history = []
    for when, label, source in sorted(past):
        if when < start:
            continue
        before = scan(loads, hrv_rows, when - timedelta(days=1), cfg, no_pain)
        history.append({"date": when.isoformat(), "label": label, "source": source, "scan": before})
    shared = []
    now_keys = {f["key"] for f in current["flags"]} - {"pain"}
    for h in history:
        if (today - d(h["date"])).days < 14:
            continue  # still inside that injury's own window
        common = now_keys & {f["key"] for f in h["scan"]["flags"]}
        if common:
            shared.append({"label": h["label"], "date": h["date"], "shared": sorted(common)})

    series = [{"date": day.isoformat(), "load": rnd(v, 0)}
              for day, v in sorted(loads.items()) if day >= today - timedelta(days=84)]
    acwr_series = []
    for day in sorted(loads):
        if day >= today - timedelta(days=84):
            s = scan(loads, hrv_rows, day, cfg)
            acwr_series.append({"date": day.isoformat(), "acwr": s["acwr"]})
    break_days = int(cfg.get("break_days", 14))
    vol = {r["part"]: r for r in gymload.volume(sig.sets, today)}
    # Body parts rested long enough that the next session should start lighter.
    coming_back = sorted(({"part": r["part"], "days": (today - d(r["last"])).days, "last": r["last"]}
                          for r in gymload.weekly_table(sig.sets, today)["rows"]
                          if r["last"] and r["part"] not in cfg.get("volume_ignore", [])
                          and break_days <= (today - d(r["last"])).days <= 60), key=lambda r: -r["days"])
    table = gymload.weekly_table(sig.sets, today)
    for row in table["rows"]:
        row.update({k: vol[row["part"]][k] for k in ("acute", "chronic", "ratio")})
    return {"current": current, "weeks": weeks, "history": history, "matches_past": shared, "pain": sig.pain,
            "body_parts": table, "returns": gymload.returns(sig.sets, today, break_days, 14),
            "coming_back": coming_back,
            "soreness": soreness_grid(sig.soreness, today), "soreness_logged": bool(sig.soreness),
            "daily_load": series, "acwr_series": acwr_series,
            "thresholds": {k: cfg[k] for k in ("acwr_caution", "acwr_high", "rest_day_load", "high_day_load",
                                               "volume_ratio_caution", "break_days")}}
