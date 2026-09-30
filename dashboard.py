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


def _iso_days(values):
    """A set of dates from ISO strings, ignoring anything unparseable."""
    out = set()
    for value in values or []:
        try:
            out.add(datetime.date.fromisoformat(str(value)[:10]))
        except ValueError:
            continue
    return out


def streak(records, today, other_days=None):
    """Consecutive days up to today with at least one training session.

    Today not being trained yet does not break a streak — it hasn't finished. The count
    therefore starts at yesterday unless today already has a session.

    `other_days` carries training Speediance does not know about: off-machine days logged
    in our own store. Without them a hotel workout breaks the streak, which is the exact
    thing the off-machine log exists to prevent. Speediance's own manual entry (type 10)
    already arrives as a record, so a day logged BOTH ways counts once either way.
    """
    days = {d for d in (_date_of(r) for r in records if is_gym_session(r)) if d}
    days |= _iso_days(other_days)
    if not days:
        return 0
    start = today if today in days else today - datetime.timedelta(days=1)
    count = 0
    while start in days:
        count += 1
        start -= datetime.timedelta(days=1)
    return count


def _window_totals(records, start, end, offmachine=None):
    """Totals for one window. `offmachine` maps ISO day -> that day's off-machine volume.

    An off-machine day counts as a session and contributes its volume: it is training,
    and leaving it out would make "2 sessions this week" contradict a 3-day streak. It
    adds no seconds or calories — Speediance's own manual entry holds those when the user
    made one, and inventing a second figure would put two numbers on one workout.
    """
    rows = [r for r in records if is_gym_session(r) and (d := _date_of(r)) and start <= d <= end]
    machine_days = {d for r in rows if (d := _date_of(r))}
    extra_sessions, extra_volume = 0, 0.0
    for day, volume in (offmachine or {}).items():
        try:
            parsed = datetime.date.fromisoformat(str(day)[:10])
        except ValueError:
            continue
        if not (start <= parsed <= end):
            continue
        extra_volume += float(volume or 0)
        if parsed not in machine_days:
            extra_sessions += 1      # a day trained both ways is still one training day
    return {
        "sessions": len(rows) + extra_sessions,
        "volume": round(sum(_num(r.get("totalCapacity")) or 0 for r in rows) + extra_volume, 1),
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


def week_comparison(records, today, offmachine=None):
    """This week against the previous seven days, with the deltas that have a baseline.

    `offmachine` maps ISO day -> off-machine volume; both windows see it, so a week with
    hotel training is not compared against one where it was ignored.
    """
    this_start = today - datetime.timedelta(days=6)
    last_end = this_start - datetime.timedelta(days=1)
    last_start = last_end - datetime.timedelta(days=6)
    now = _window_totals(records, this_start, today, offmachine)
    before = _window_totals(records, last_start, last_end, offmachine)
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


def activity_strip(records, today, days=14, offmachine_days=None):
    """One entry per day for the last `days`, newest last.

    A rest day is not an absence of data — it is part of the pattern — so every day in
    the window appears, with `trained` saying which kind of day it was. Phone-health
    activity is marked separately: it is movement, but not a training day.

    `offmachine_days` maps an ISO day to that day's off-machine volume. Those days are
    trained days and must show as such, or the strip contradicts the streak.
    """
    by_day = {}
    for record in records or []:
        day = _date_of(record)
        if day is None or day > today or (today - day).days >= days:
            continue
        entry = by_day.setdefault(day, {"volume": 0.0, "seconds": 0, "gym": False, "health": False})
        if is_gym_session(record):
            entry["gym"] = True
            entry["volume"] += _num(record.get("totalCapacity")) or 0
            entry["seconds"] += int(_num(record.get("trainingTime")) or 0)
        else:
            entry["health"] = True
            entry["seconds"] += int(_num(record.get("trainingTime")) or 0)

    for day, volume in (offmachine_days or {}).items():
        try:
            parsed = datetime.date.fromisoformat(str(day)[:10])
        except ValueError:
            continue
        if parsed > today or (today - parsed).days >= days:
            continue
        entry = by_day.setdefault(parsed, {"volume": 0.0, "seconds": 0, "gym": False,
                                           "health": False})
        entry["gym"] = True                 # trained is trained, machine or not
        entry["offMachine"] = True
        entry["volume"] += float(volume or 0)

    peak = max((e["volume"] for e in by_day.values()), default=0)
    out = []
    for back in range(days - 1, -1, -1):
        day = today - datetime.timedelta(days=back)
        entry = by_day.get(day)
        kind = "rest"
        if entry and entry["gym"]:
            kind = "gym"
        elif entry and entry["health"]:
            kind = "health"
        out.append({
            "date": day.isoformat(),
            "weekday": day.strftime("%a")[0],
            "kind": kind,
            "volume": round(entry["volume"], 1) if entry else 0.0,
            "seconds": entry["seconds"] if entry else 0,
            # Height as a share of the window's biggest day, so the strip is readable
            # regardless of whether someone lifts hundreds or thousands of pounds.
            "share": round(entry["volume"] / peak, 3) if entry and peak else 0.0,
            "offMachine": bool(entry and entry.get("offMachine")),
            "isToday": day == today,
        })
    return out


def daily_exercise_stats(day_exercises, source="machine"):
    """Per-exercise, per-DAY rows from parsed session detail.

    `day_exercises` is a list of (day, exercises) — one entry per session, exercises in
    the session-detail shape. Returns {name: [{dayStr, maxWeight, totalCapacity, source}]},
    the same shape personal_records reads.

    This exists because Speediance's own per-movement stat feed
    (`userActionStatPage`) is NOT daily: every row it returns is keyed to a MONDAY, so a
    row is a whole week's bucket. Feeding that to personal_records made a week's total
    read as one day's — two sessions in the same week summed into a single number and
    reported as "yesterday". Session detail is the only true daily source; there is no
    daily variant of the stat route.

    Two sessions on the same day are combined into one row, because a day's volume is a
    day's volume regardless of how many times the machine was switched on.
    """
    by_name = {}
    for day, exercises in day_exercises or []:
        stamp = str(day or "")[:10]
        try:
            datetime.date.fromisoformat(stamp)
        except ValueError:
            continue
        for exercise in exercises or []:
            name = exercise.get("actionLibraryName")
            if not name:
                continue
            volume, top = 0.0, None
            for st in exercise.get("finishedReps") or []:
                reps = st.get("finishedCount") or 0
                load = _set_load(st.get("trainingInfoDetail") or {}, st.get("leftRight") or None)
                if load is not None and (top is None or load > top):
                    top = load
                if reps and load:
                    volume += float(reps) * float(load)
            rows = by_name.setdefault(name, {})
            row = rows.setdefault(stamp, {"dayStr": stamp, "maxWeight": 0.0,
                                          "totalCapacity": 0.0, "source": source})
            row["totalCapacity"] = round(row["totalCapacity"] + volume, 1)
            if top is not None:
                row["maxWeight"] = max(row["maxWeight"], round(float(top), 2))
    return {name: sorted(rows.values(), key=lambda r: r["dayStr"])
            for name, rows in by_name.items()}


def _set_load(detail, side):
    """One set's resistance. Mirrors muscle_balance.set_load — see its note: a pinned
    side is that side alone, two populated sides BOTH carry load and sum, and `weights`
    is only a fallback (on dual-cable movements it is derived force telemetry, not the
    resistance setting)."""
    def nums(value):
        out = []
        for item in value or []:
            try:
                out.append(float(item))
            except (TypeError, ValueError):
                continue
        return out

    left, right = nums(detail.get("leftWeights")), nums(detail.get("rightWeights"))
    if side == 1 and left:
        return max(left)
    if side == 2 and right:
        return max(right)
    if left and right:
        return max(left) + max(right)
    if left or right:
        return max(left or right)
    weights = nums(detail.get("weights"))
    return max(weights) if weights else None


def personal_records(exercise_stats, within_days=14, today=None):
    """Recent bests, with the number that made each one a record and what it beat.

    `exercise_stats` maps an exercise name to DAILY rows (`dayStr`, `maxWeight`,
    `totalCapacity`, optional `source`). They must be one row per DAY — see
    daily_exercise_stats: Speediance's own stat feed buckets by week, and feeding those
    rows here makes a week's total read as a single day's. A record is reported for the LATEST day that
    achieved the best, so repeating a best reads as today's news rather than the first
    time it happened. `previous` is the best before that day, which is what makes the
    record meaningful — "1,210 lbs" alone says nothing about whether it was hard-won.
    """
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=within_days)
    out = []
    for name, rows in (exercise_stats or {}).items():
        dated = []
        for row in rows or []:
            # userActionStatPage keys its rows `dayStr`; other feeds use date/startTime.
            stamp = str(row.get("dayStr") or row.get("date") or row.get("startTime") or "")[:10]
            try:
                day = datetime.date.fromisoformat(stamp)
            except ValueError:
                continue
            dated.append((day, _num(row.get("maxWeight")) or 0, _num(row.get("totalCapacity")) or 0,
                          row.get("source") or "machine"))
        if len(dated) < 2:
            continue                      # a first-ever entry is not a record
        dated.sort()

        kinds = []
        for label, index in (("Heaviest weight", 1), ("Best day volume", 2)):
            values = [d[index] for d in dated]
            best = max(values)
            if not best:
                continue
            # The most recent day that reached the best, so a repeat counts as news.
            day = max(d[0] for d in dated if d[index] >= best)
            # Where THAT day's work came from — not whether this movement has ever been
            # done off the machine, which would mislabel a machine PR on any movement
            # that also appears in the off-machine log.
            source = next((d[3] for d in dated if d[0] == day), "machine")
            if day < cutoff:
                continue
            # A zero is a day the movement carried no weight (bodyweight or timed), not a
            # previous best — "+40 vs 0" would read as progress that never happened.
            earlier = [d[index] for d in dated if d[0] < day and d[index] > 0]
            previous = max(earlier) if earlier else None
            if previous is not None and best <= previous:
                continue                  # tied an older best rather than beating it
            kinds.append({
                "kind": label,
                "value": round(best, 1),
                "previous": round(previous, 1) if previous is not None else None,
                "gain": round(best - previous, 1) if previous is not None else None,
                "gainPercent": (round(100.0 * (best - previous) / previous)
                                if previous else None),
                "date": day.isoformat(),
                "daysAgo": (today - day).days,
                "source": source,
            })
        if kinds:
            newest = min(k["daysAgo"] for k in kinds)
            out.append({"exercise": name, "kinds": kinds,
                        "date": min(k["date"] for k in kinds), "daysAgo": newest})
    out.sort(key=lambda r: r["daysAgo"])
    return out
