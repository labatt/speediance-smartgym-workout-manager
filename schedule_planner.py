"""Recurring workout schedules.

The Speediance API has no concept of recurrence — it only stores one dated entry at a
time (`templateReservation`). So a "repeating schedule" is a *pattern* held locally and
materialised into individual dated calls. This module is that pattern logic, and it is
deliberately pure: no I/O, no API calls, no clock. Everything that decides what to write
or destroy is testable without touching a live account, which matters because applying a
schedule deletes calendar entries.

Two modes:

- ``weekly`` — a workout per weekday, repeating every week. Monday is always Workout A.
- ``cycle``  — a sequence walked from an anchor date, ignoring weekdays. A 4-day cycle
  drifts across the calendar (A, B, C, rest, A, B, C, rest, ...).

A ``None`` slot is a rest day.
"""

import datetime

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Only these calendar entries are ours to manage. See classify_entry().
MANAGED_TYPE = 3


def _as_date(value):
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def slot_for(schedule, day):
    """Which template code (or None for rest) this schedule wants on `day`."""
    day = _as_date(day)
    mode = schedule.get("mode", "weekly")

    if mode == "weekly":
        weekly = schedule.get("weekly") or {}
        return weekly.get(WEEKDAYS[day.weekday()]) or None

    if mode == "cycle":
        cycle = schedule.get("cycle") or {}
        sequence = cycle.get("sequence") or []
        anchor = cycle.get("anchor")
        if not sequence or not anchor:
            return None
        # Python's % is non-negative for a positive modulus, so dates before the
        # anchor wrap correctly rather than indexing backwards off the end.
        offset = (day - _as_date(anchor)).days % len(sequence)
        return sequence[offset] or None

    return None


def expand(schedule, start, end):
    """[(date, template_code_or_None)] for every day in [start, end] inclusive."""
    start, end = _as_date(start), _as_date(end)
    days = []
    day = start
    while day <= end:
        days.append((day, slot_for(schedule, day)))
        day += datetime.timedelta(days=1)
    return days


def classify_entry(entry):
    """What kind of calendar entry is this, and may we touch it?

    The calendar mixes four things, and only one of them is ours:

    - type 3, isFinish=1 — a COMPLETED session. This is training history. Deleting it
      would destroy a real record, so it is never touched, and it never counts as a
      collision.
    - type 3, isFinish=0, has code — a reservation this app (or the user) made. Ours.
    - type 4, no code — Speediance's own "Goal-Focused Workout" suggestions. There is no
      code to remove them by, and they are not user reservations. Ignored.
    - type 4, with code — an official course, scheduled through a different endpoint.
      Not ours to remove.
    """
    if entry.get("isFinish"):
        return "completed"
    if entry.get("type") != MANAGED_TYPE:
        return "foreign"
    if not entry.get("code"):
        return "foreign"
    return "reservation"


def existing_by_date(calendar_days):
    """{'YYYY-MM-DD': [reservation, ...]} — only entries we are allowed to manage."""
    out = {}
    for day in calendar_days or []:
        date_str = str(day.get("date"))[:10]
        for entry in day.get("trainingPlanList") or []:
            if classify_entry(entry) == "reservation":
                out.setdefault(date_str, []).append(
                    {"code": entry.get("code"), "title": entry.get("title")}
                )
    return out


def plan_changes(schedule, start, end, existing, protect_before=None):
    """Diff the pattern against the calendar. Pure — decides, never acts.

    Returns a list of per-day actions, each one of:

      noop    — the wanted workout is already there (or a rest day is already empty)
      write   — day is empty, add the workout
      replace — day holds something else; remove it, then add the workout
      clear   — rest day that currently holds a reservation; remove it

    `protect_before` (a date) forbids changes on or before it. Used to keep the automatic
    top-up from reaching back into days the user has already seen and confirmed.
    """
    start, end = _as_date(start), _as_date(end)
    protect_before = _as_date(protect_before) if protect_before else None

    changes = []
    for day, wanted in expand(schedule, start, end):
        if protect_before and day <= protect_before:
            continue

        key = day.isoformat()
        current = existing.get(key, [])
        current_codes = [c["code"] for c in current]

        if wanted:
            if wanted in current_codes and len(current) == 1:
                action = "noop"
            elif not current:
                action = "write"
            else:
                action = "replace"
        else:
            action = "clear" if current else "noop"

        changes.append(
            {
                "date": key,
                "weekday": WEEKDAYS[day.weekday()],
                "action": action,
                "wanted": wanted,
                "remove": [] if action in ("noop", "write") else current,
            }
        )
    return changes


def summarize(changes):
    counts = {"noop": 0, "write": 0, "replace": 0, "clear": 0}
    for change in changes:
        counts[change["action"]] = counts.get(change["action"], 0) + 1
    counts["destructive"] = counts["replace"] + counts["clear"]
    return counts
