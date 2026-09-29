"""Dashboard derivations. No I/O, no Flask — unit-tested.

Everything here is computed from data the app already fetches: the training history,
the muscle-fatigue read, and the exercise catalog. The dashboard's job is to answer
"what should I do today, and what happened lately" without the user opening four pages.

Two rules run through it:

* Phone-health imports (walks and similar) are activity, not gym sessions. They count
  towards "you moved today" but never towards volume, streaks or muscle recovery, or a
  walk would read as a training day.
* A muscle's recovery is time since it was last loaded, weighted by how hard. Speediance
  reports per-muscle fatigue but not when it was earned, so the hours come from the
  session history and the fatigue level only sets the window.
"""

import datetime

# Hours a muscle is considered to be recovering, by the fatigue level Speediance reports
# (1 light, 2 moderate, 3 heavy). A heavier load holds the muscle out longer.
RECOVERY_WINDOW_HOURS = {1: 24, 2: 48, 3: 72}
DEFAULT_RECOVERY_HOURS = 48

BODY_PARTS = {11: "Chest", 12: "Shoulders", 13: "Back", 14: "Glutes",
              15: "Legs", 16: "Arms", 17: "Core", 18: "Full body"}


def _num(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _date_of(record):
    """A record's calendar date, or None if it carries no usable timestamp."""
    stamp = str(record.get("startTime") or "")[:10]
    try:
        return datetime.date.fromisoformat(stamp)
    except ValueError:
        return None


def _started_at(record):
    try:
        return datetime.datetime.fromisoformat(str(record.get("startTime"))[:19])
    except (TypeError, ValueError):
        return None


def is_gym_session(record):
    """A session performed on the machine, as opposed to a phone-health import."""
    return not record.get("belongUserHealth")


def streak(records, today):
    """Consecutive days up to today with at least one gym session.

    Today not being trained yet does not break a streak — it hasn't finished. The count
    therefore starts at yesterday unless today already has a session.
    """
    days = {d for d in (_date_of(r) for r in records if is_gym_session(r)) if d}
    if not days:
        return 0
    start = today if today in days else today - datetime.timedelta(days=1)
    count = 0
    while start in days:
        count += 1
        start -= datetime.timedelta(days=1)
    return count


def _window_totals(records, start, end):
    rows = [r for r in records if is_gym_session(r) and (d := _date_of(r)) and start <= d <= end]
    return {
        "sessions": len(rows),
        "volume": round(sum(_num(r.get("totalCapacity")) or 0 for r in rows), 1),
        "seconds": int(sum(_num(r.get("trainingTime")) or 0 for r in rows)),
        "calories": int(sum(_num(r.get("calorie")) or 0 for r in rows)),
    }


def _delta(now, before):
    """Percentage change, or None when there is no baseline to compare against.

    Returning 0 for "last week was empty" would read as "no change" when the honest
    answer is that the comparison cannot be made.
    """
    if not before:
        return None
    return round(100.0 * (now - before) / before)


def week_comparison(records, today):
    """This week against the previous seven days, with the deltas that have a baseline."""
    this_start = today - datetime.timedelta(days=6)
    last_end = this_start - datetime.timedelta(days=1)
    last_start = last_end - datetime.timedelta(days=6)
    now = _window_totals(records, this_start, today)
    before = _window_totals(records, last_start, last_end)
    return {
        "sessions": now["sessions"], "sessionsDelta": _delta(now["sessions"], before["sessions"]),
        "volume": now["volume"], "volumeDelta": _delta(now["volume"], before["volume"]),
        "seconds": now["seconds"], "secondsDelta": _delta(now["seconds"], before["seconds"]),
        "calories": now["calories"], "caloriesDelta": _delta(now["calories"], before["calories"]),
    }


def muscle_recovery(fatigue_rows, last_trained, now):
    """Which body parts are still recovering, and how ready training looks overall.

    Speediance's fatigue read says how hard each part was worked but NOT when, and a
    history record carries no body part at all — it names a workout, not the muscles it
    hit. So `last_trained` maps a body-part id to when it was last loaded, and the caller
    builds it from the exercises inside recent sessions. Passing an empty map used to
    make every part read as recovered, which looked perfectly healthy and meant nothing.

    A part with no recent session is treated as recovered rather than unknown — it has
    had time.
    """
    last_trained = {int(k): v for k, v in (last_trained or {}).items()}
    recovering, ready = [], 0
    rows = [r for r in (fatigue_rows or []) if isinstance(r, dict)]
    for row in rows:
        part = row.get("trainingPartId2")
        if part is None:
            continue
        level = int(_num(row.get("fatigue")) or 0)
        window = RECOVERY_WINDOW_HOURS.get(level, DEFAULT_RECOVERY_HOURS)
        trained = last_trained.get(int(part))
        if trained is None:
            ready += 1
            continue
        elapsed = (now - trained).total_seconds() / 3600.0
        if elapsed >= window:
            ready += 1
        else:
            recovering.append({
                "bodyPart": BODY_PARTS.get(int(part), f"Part {part}"),
                "hoursLeft": int(round(window - elapsed)),
                "fatigue": level,
            })
    recovering.sort(key=lambda r: -r["hoursLeft"])
    total = len(rows)
    return {
        "available": total > 0,
        "readyPercent": int(round(100.0 * ready / total)) if total else None,
        "recovering": recovering,
        "verdict": ("Ready to train" if not recovering
                    else "Train with care" if len(recovering) <= max(1, total // 3)
                    else "Mostly recovering"),
    }


def personal_records(exercise_stats, within_days=14, today=None):
    """Recent bests worth surfacing: heaviest weight, and biggest single-day volume.

    `exercise_stats` maps an exercise name to its dated rows. Only records set inside the
    window are returned — an all-time best from a year ago is not news.
    """
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=within_days)
    out = []
    for name, rows in (exercise_stats or {}).items():
        dated = []
        for row in rows or []:
            day = None
            # userActionStatPage keys its rows `dayStr`; other feeds use date/startTime.
            stamp = str(row.get("dayStr") or row.get("date") or row.get("startTime") or "")[:10]
            try:
                day = datetime.date.fromisoformat(stamp)
            except ValueError:
                continue
            dated.append((day, _num(row.get("maxWeight")) or 0, _num(row.get("totalCapacity")) or 0))
        if len(dated) < 2:
            continue                      # a first-ever entry is not a record
        dated.sort()
        best_weight = max(d[1] for d in dated)
        best_volume = max(d[2] for d in dated)
        for day, weight, volume in dated:
            if day < cutoff:
                continue
            kinds = []
            if weight and weight >= best_weight:
                kinds.append("Heaviest weight")
            if volume and volume >= best_volume:
                kinds.append("Best day volume")
            if kinds:
                out.append({"exercise": name, "kinds": kinds, "date": day.isoformat(),
                            "daysAgo": (today - day).days})
                break
    out.sort(key=lambda r: r["daysAgo"])
    return out
