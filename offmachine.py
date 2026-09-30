"""Adapters that let off-machine sets flow through the machine's own derivations.

No I/O, no Flask — every function here is a pure transform, so the whole module is
unit-testable and the interesting decisions are visible in one place.

The point of this module is that NOTHING downstream needs to learn about off-machine
training. Two shapes already carry a workout through this codebase:

  session-detail shape  `{actionLibraryGroupId, actionLibraryName, finishedReps[...]}`
                        consumed by muscle_balance.attribute / exercise_volume and by
                        the session-detail template
  stats shape           `{dayStr, maxWeight, totalCapacity}` rows per exercise name,
                        consumed by dashboard.personal_records

So rather than teaching volume-by-muscle and personal-bests about a second data source,
we emit the shapes they already read. A hotel dumbbell press becomes a set like any
other, and every derivation downstream is unchanged.

What stays honest: `source` is stamped on each adapted exercise and each merged stats
row, so the UI can mark off-machine work rather than passing it off as machine data.
Volume totals that mix the two say so.
"""

from offmachine_store import SIDE_CODES

SOURCE = "offmachine"


def _by_exercise(sets):
    """Group sets by the movement they belong to, preserving first-seen order.

    Keyed on (groupId, lowercased name) so the same movement logged twice in a day
    collects into one exercise, while two genuinely different movements that happen to
    share a group id of None stay apart.
    """
    grouped = {}
    for row in sets or []:
        key = (row.get("groupId"), str(row.get("name") or "").strip().lower())
        grouped.setdefault(key, []).append(row)
    return grouped


def _set_detail(row):
    """One set in the machine's `finishedReps` shape.

    The load goes into the side array that matches how the set was performed, so
    muscle_balance.set_load reads it through its intended path: a single-arm row is
    that arm's load (not doubled), while a two-handed lift lands in `weights`. Off-
    machine work has no cable telemetry, so each array holds exactly one number —
    which is all set_load needs, since it takes the max.
    """
    weight = float(row.get("weight") or 0)
    side = str(row.get("side") or "both").lower()
    detail = {"weights": [], "leftWeights": [], "rightWeights": []}
    if weight:
        if side == "left":
            detail["leftWeights"] = [weight]
        elif side == "right":
            detail["rightWeights"] = [weight]
        else:
            detail["weights"] = [weight]
    reps = int(row.get("reps") or 0)
    return {
        "finishedCount": reps,
        # Per-set volume, which the session-detail view renders directly. Without it the
        # table showed a blank where every machine set shows a number.
        "capacity": round(reps * weight, 1),
        # Nothing prescribed these reps, so what was done is also what was targeted —
        # the same convention free_training_to_detail uses for Free Lift.
        "targetCount": reps,
        "time": 0,
        "leftRight": SIDE_CODES.get(side, 0),
        "maxHeartRate": None,
        "trainingInfoDetail": detail,
        "source": SOURCE,
    }


def as_exercises(sets):
    """Off-machine sets -> session-detail shape, ready for muscle_balance.attribute.

    A set whose movement has no Speediance group id keeps groupId None. attribute()
    will list it under exercisesNotInLibrary rather than silently dropping it, which is
    the correct outcome: we know it was trained, but not which muscles it worked.
    """
    out = []
    for (group_id, _), rows in _by_exercise(sets).items():
        ordered = sorted(rows, key=lambda r: (r.get("setIndex") or 0, r.get("id") or 0))
        set_rows = [_set_detail(r) for r in ordered]   # not `sets`: that is the parameter
        # The detail view only reads leftWeights/rightWeights when the EXERCISE is flagged
        # unilateral; without this flag a single-arm set's load fell through to the empty
        # `weights` array and rendered as "-".
        unilateral = any(st["leftRight"] in (1, 2) for st in set_rows)
        out.append({
            "actionLibraryName": ordered[0].get("name"),
            "actionLibraryGroupId": group_id,
            "completionMethod": None,
            "trainingPartId2": None,
            "isLeftRight": 1 if unilateral else 0,
            "totalCapacity": round(sum(st["capacity"] for st in set_rows), 1),
            "finishedReps": set_rows,
            "source": SOURCE,
            "location": ordered[0].get("location") or "",
            "notes": [r["note"] for r in ordered if r.get("note")],
        })
    return out


def _day_stats(rows):
    """maxWeight / totalCapacity for one movement on one day.

    totalCapacity is reps x load summed over the day's sets — the same definition
    Speediance uses for a session's totalCapacity, so the two are comparable and a
    merged personal-best scan is not comparing different quantities.
    """
    max_weight = max((float(r.get("weight") or 0) for r in rows), default=0.0)
    volume = sum(float(r.get("weight") or 0) * int(r.get("reps") or 0) for r in rows)
    return round(max_weight, 2), round(volume, 1)


def stat_rows(sets):
    """Off-machine sets -> {exercise name: [stats rows]} for dashboard.personal_records.

    Rows carry `dayStr`, which is the key userActionStatPage uses and which
    personal_records already reads. Sets with no group id are included: a personal best
    on a movement Speediance doesn't stock is still a personal best.
    """
    by_name = {}
    for (_, _), rows in _by_exercise(sets).items():
        name = rows[0].get("name")
        if not name:
            continue
        by_day = {}
        for row in rows:
            by_day.setdefault(row.get("day"), []).append(row)
        out = by_name.setdefault(name, [])
        for day, day_rows in by_day.items():
            max_weight, volume = _day_stats(day_rows)
            out.append({"dayStr": day, "maxWeight": max_weight,
                        "totalCapacity": volume, "source": SOURCE})
    for rows in by_name.values():
        rows.sort(key=lambda r: r["dayStr"])
    return by_name


def group_ids(sets):
    """{exercise name: Speediance group id} for the sets that have one.

    Lets a caller fetch the machine's own history for a movement that was logged off the
    machine — without it, a merged personal-best scan compares an off-machine best
    against off-machine history alone and can report a record the machine data disproves.
    Names with no group id are omitted: there is nothing to look up.
    """
    out = {}
    for row in sets or []:
        name, group_id = row.get("name"), row.get("groupId")
        if name and group_id is not None and name not in out:
            out[name] = int(group_id)
    return out


def merge_stats(machine_stats, local_stats):
    """Combine Speediance's per-exercise stats with off-machine ones.

    Matched by exercise NAME, because that is the only identifier the two sources share
    at this point (the machine's stats feed is fetched per group id, but keyed into the
    caller's dict by name).

    A day present in both sources is COMBINED, not duplicated: volume adds, and
    maxWeight takes the higher of the two. Someone who benched on the machine in the
    morning and with dumbbells that evening trained once that day, and their day volume
    is the sum. Leaving both rows in place would let personal_records see the same day
    twice and report a 'previous best' that was really the same session.
    """
    merged = {name: list(rows or []) for name, rows in (machine_stats or {}).items()}
    for name, rows in (local_stats or {}).items():
        existing = merged.setdefault(name, [])
        by_day = {}
        for index, row in enumerate(existing):
            day = str(row.get("dayStr") or row.get("date") or row.get("startTime") or "")[:10]
            if day:
                by_day[day] = index
        for row in rows:
            day = row["dayStr"]
            if day in by_day:
                target = dict(existing[by_day[day]])
                target["maxWeight"] = max(float(target.get("maxWeight") or 0),
                                          float(row.get("maxWeight") or 0))
                target["totalCapacity"] = round(float(target.get("totalCapacity") or 0)
                                                + float(row.get("totalCapacity") or 0), 1)
                # The day now contains both, so it is no longer purely either.
                target["source"] = "mixed"
                existing[by_day[day]] = target
            else:
                existing.append(dict(row))
        existing.sort(key=lambda r: str(r.get("dayStr") or r.get("date") or "")[:10])
    return merged


def sessions(sets):
    """One summary per day that has off-machine sets, newest first.

    This is what the history and calendar views list. Duration and calories are
    deliberately absent: Speediance's own manual record holds those, and inventing a
    second answer would put two numbers on one workout.
    """
    by_day = {}
    for row in sets or []:
        by_day.setdefault(row.get("day"), []).append(row)
    out = []
    for day in sorted(by_day, reverse=True):
        rows = by_day[day]
        exercises = as_exercises(rows)
        volume = sum(float(r.get("weight") or 0) * int(r.get("reps") or 0) for r in rows)
        locations = [loc for loc in {r.get("location") or "" for r in rows} if loc]
        out.append({
            "day": day,
            "trainingId": next((r["trainingId"] for r in rows if r.get("trainingId")), None),
            "exercises": exercises,
            "exerciseCount": len(exercises),
            "setCount": len(rows),
            "volume": round(volume, 1),
            "location": locations[0] if len(locations) == 1 else "",
            "source": SOURCE,
        })
    return out
