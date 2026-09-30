"""Deriving per-session exercise stats, and keeping the cache honest against Speediance.

Split from session_stats_store.py so the interesting logic is testable without SQLite and
the store stays a thin persistence layer.

`reduce_exercises` is the derivation the cache's `derived_version` protects: if anything
here changes, bump DERIVED_VERSION or the old numbers survive.

`plan_reconcile` is pure — it decides what to fetch and what to drop given what Speediance
lists and what we already hold. `reconcile` is the thin I/O loop around it, so the policy
(which sessions, how many per run, what counts as gone) is unit-tested rather than tangled
with API calls.
"""

import datetime

from dashboard import _set_load, is_gym_session

# How many session details one reconcile run may fetch. The first backfill is bounded so a
# scheduled run can never turn into a hundred-call stampede; it simply resumes next time,
# oldest-missing first. A weekly run has nothing to do once caught up.
DEFAULT_MAX_FETCH = 40

# Failures that will never resolve, so the session is marked scanned instead of retried
# every week for the life of the account. Speediance refuses detail for a session whose
# custom template was later deleted — the workout happened, but its breakdown is gone and
# no amount of asking brings it back. Matched case-insensitively as a substring; anything
# NOT listed here is treated as transient and retried, which is the safe default.
PERMANENT_DETAIL_ERRORS = ("template has been deleted", "template not found")


def is_permanent_failure(message):
    text = str(message or "").lower()
    return any(marker in text for marker in PERMANENT_DETAIL_ERRORS)


def reduce_exercises(exercises):
    """Session-detail exercises -> [{name, groupId, volume, maxWeight, sets, reps}].

    Volume is reps x resistance summed over worked sets, and resistance comes from
    dashboard._set_load, which is where the real traps live: a pinned side is that side
    alone, two populated sides BOTH carry load and sum, and `weights` is only a fallback
    because on dual-cable movements it is derived force telemetry rather than the
    resistance setting.

    Movements appearing twice in one session are combined — the machine splits a movement
    across blocks sometimes, and two entries for one exercise would otherwise be stored
    under one primary key and silently lose the first.
    """
    combined = {}
    for exercise in exercises or []:
        name = str(exercise.get("actionLibraryName") or "").strip()
        if not name:
            continue
        entry = combined.setdefault(name, {
            "name": name, "groupId": exercise.get("actionLibraryGroupId"),
            "volume": 0.0, "maxWeight": 0.0, "sets": 0, "reps": 0})
        if entry["groupId"] is None and exercise.get("actionLibraryGroupId") is not None:
            entry["groupId"] = exercise.get("actionLibraryGroupId")
        for st in exercise.get("finishedReps") or []:
            reps = int(st.get("finishedCount") or 0)
            load = _set_load(st.get("trainingInfoDetail") or {}, st.get("leftRight") or None)
            if reps <= 0:
                continue                      # a skipped set is not a set that happened
            entry["sets"] += 1
            entry["reps"] += reps
            if load:
                entry["volume"] += float(reps) * float(load)
                entry["maxWeight"] = max(entry["maxWeight"], float(load))
    for entry in combined.values():
        entry["volume"] = round(entry["volume"], 1)
        entry["maxWeight"] = round(entry["maxWeight"], 2)
    return list(combined.values())


def _day_of(record):
    return str(record.get("startTime") or "")[:10]


def plan_reconcile(records, cached, max_fetch=DEFAULT_MAX_FETCH):
    """What to fetch and what to drop. Pure — no I/O.

    `records` is Speediance's history for the window it covers; `cached` the training ids
    already derived at the current version.

    Sessions are fetched OLDEST first so an interrupted backfill makes forward progress
    from a stable end rather than re-walking the newest each run.

    `drop` is only ever computed from ids that fall inside the window `records` covers.
    A session outside that range is absent because it was not asked for, not because it
    was deleted — dropping on that basis would erase the whole cache on a narrow read.
    """
    gym = [r for r in records or [] if is_gym_session(r) and r.get("trainingId")]
    listed = {int(r["trainingId"]): _day_of(r) for r in gym}
    missing = sorted((day, tid) for tid, day in listed.items() if tid not in cached)
    fetch = [tid for _, tid in missing[:max_fetch]]
    return {"fetch": fetch, "listed": listed,
            "remaining": max(0, len(missing) - len(fetch)),
            # Nothing was missing when the plan was made. reconcile() reports a different
            # upToDate: whether the cache is current AFTER its run.
            "nothingMissing": not missing}


def stale_ids(cached_days, listed_ids, start, end):
    """Cached sessions inside [start, end] that Speediance no longer lists.

    `cached_days` maps training id -> its cached day. Bounding by the window is the whole
    point: only ids we KNOW were in the range Speediance just reported on can be judged
    missing from it.
    """
    start, end = str(start)[:10], str(end)[:10]
    return sorted(tid for tid, day in (cached_days or {}).items()
                  if tid not in listed_ids and day and start <= day <= end)


def reconcile(client, store, config, start, end, fetch_detail, max_fetch=DEFAULT_MAX_FETCH):
    """Bring the cache in line with Speediance for [start, end]. Returns a report.

    `fetch_detail(record) -> exercises` is injected so this is testable without the app's
    session-detail plumbing, and so one unreadable session cannot abort the run.
    """
    records = client.get_training_records(start, end) or []
    cached = store.scanned_ids(config)
    plan = plan_reconcile(records, cached, max_fetch=max_fetch)

    added, failed, unreadable = 0, [], []
    for training_id in plan["fetch"]:
        record = next((r for r in records if int(r.get("trainingId") or 0) == training_id), None)
        if record is None:
            continue
        try:
            exercises = fetch_detail(record) or []
        except Exception as exc:                      # noqa: BLE001 — reported, not swallowed
            if is_permanent_failure(exc):
                # Record it as scanned-with-nothing so the weekly run stops asking. The
                # day still counts as trained: that comes from the history record, not
                # from here.
                store.store_session(config, training_id, _day_of(record), [],
                                    session_type=record.get("type"), unreadable=str(exc)[:200])
                unreadable.append({"trainingId": training_id, "reason": str(exc)})
                continue
            failed.append({"trainingId": training_id, "error": str(exc)})
            continue
        store.store_session(config, training_id, _day_of(record),
                            reduce_exercises(exercises), session_type=record.get("type"))
        added += 1

    # Sessions deleted in the Speediance app must stop setting personal bests.
    cached_days = store.cached_days(config, start, end)
    gone = stale_ids(cached_days, plan["listed"], start, end)
    if gone:
        store.forget_sessions(config, gone)

    return {"start": start, "end": end, "sessionsListed": len(plan["listed"]),
            "sessionsAdded": added, "sessionsDropped": len(gone), "remaining": plan["remaining"],
            # "Is the cache current NOW" — not "was it current when we started". A run that
            # fetched everything it found ends up-to-date; one that hit its budget or lost a
            # session to an error does not, and the caller should come back.
            "upToDate": plan["remaining"] == 0 and not failed, "failed": failed,
            # Permanently unreadable sessions are not failures to retry — they are a
            # settled fact, reported once and then left alone.
            "unreadable": unreadable, "cache": store.summary(config)}


def full_history_start(records, fallback_days=400):
    """The earliest day worth reconciling, from whatever history we can see."""
    days = [d for d in (_day_of(r) for r in records or []) if d]
    if days:
        return min(days)
    return (datetime.date.today() - datetime.timedelta(days=fallback_days)).isoformat()
