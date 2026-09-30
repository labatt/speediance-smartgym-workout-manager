"""Per-session exercise stats, cached locally so personal bests are fast and all-time.

WHY THIS EXISTS. Speediance's per-movement stat feed (`userActionStatPage`) buckets by
WEEK — every `dayStr` is the Monday of a Sunday-to-Saturday week — so it cannot answer
what a single day held. The only true daily source is each session's own detail, and
fetching all of it on every dashboard load cost ~15 API calls and about three seconds.
Worse, it bounded personal bests to whatever window we were willing to pay for.

So each session's per-exercise numbers are derived once and kept. After the first
backfill a load costs one call (the history list), and volume records become all-time
rather than "best in the last 30 days".

THIS IS A DERIVED CACHE, NOT A SOURCE OF TRUTH. Every row is recomputable from
Speediance, which is what makes it safe: a bad row is always fixable by rebuilding.
That is the opposite of offmachine_sets, which holds the ONLY copy of its data. Nothing
here may be the last copy of anything.

Two rules keep it honest:

* `derived_version` is stamped on every row. The numbers are DERIVED, and the derivation
  has real traps — two-cable sets sum both sides, a pinned side is that side alone, and
  `weights` is derived force telemetry rather than resistance on dual-cable movements.
  Fixing any of that must invalidate what was cached under the old logic, or the old
  mistake survives silently forever. Bump DERIVED_VERSION and stale rows are ignored and
  re-derived.
* Every scanned session is recorded in `session_stats_scanned`, INCLUDING ones that
  parsed to no exercises (cardio, rowing, an unreadable payload). Without that marker a
  session with nothing in it would be re-fetched on every single reconcile, forever.

Same shared-file discipline as the other stores: short-lived connections with a timeout,
path resolved by avoided_store.db_path so the test suite's isolation applies here too.
"""

import datetime
import sqlite3

from avoided_store import DEFAULT_PATH, db_path  # noqa: F401  (one shared file, one rule)

# Bump this whenever the volume / max-weight derivation changes. Rows stamped with an
# older version are treated as absent, so they are re-fetched and re-derived rather than
# quietly serving numbers computed by code that has since been corrected.
DERIVED_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS session_exercise_stats (
  training_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  group_id INTEGER,
  day TEXT NOT NULL,
  volume REAL NOT NULL DEFAULT 0,
  max_weight REAL NOT NULL DEFAULT 0,
  sets INTEGER NOT NULL DEFAULT 0,
  reps INTEGER NOT NULL DEFAULT 0,
  derived_version INTEGER NOT NULL,
  cached_at TEXT NOT NULL,
  PRIMARY KEY (training_id, name)
);
CREATE INDEX IF NOT EXISTS session_exercise_stats_day ON session_exercise_stats (day);
CREATE TABLE IF NOT EXISTS session_stats_scanned (
  training_id INTEGER PRIMARY KEY,
  day TEXT NOT NULL,
  session_type INTEGER,
  exercise_count INTEGER NOT NULL DEFAULT 0,
  unreadable TEXT NOT NULL DEFAULT '',
  derived_version INTEGER NOT NULL,
  cached_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS session_stats_scanned_day ON session_stats_scanned (day);
"""


# Columns added after the table first shipped. CREATE TABLE IF NOT EXISTS silently does
# nothing when the table already exists, so a new column has to be added explicitly or
# every write fails with "no such column" on any database created before the change.
# Same pattern avoided_store uses for exercise_marks.reason.
_MIGRATIONS = (
    ("session_stats_scanned", "unreadable", "ALTER TABLE session_stats_scanned "
                                            "ADD COLUMN unreadable TEXT NOT NULL DEFAULT ''"),
)


def _connect(path):
    conn = sqlite3.connect(path, timeout=5)
    conn.executescript(_DDL)
    for table, column, statement in _MIGRATIONS:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            with conn:
                conn.execute(statement)
    return conn


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(value):
    text = str(value or "")[:10]
    datetime.date.fromisoformat(text)   # ValueError on anything malformed
    return text


def scanned_ids(config, path=None):
    """Training ids already derived AT THE CURRENT VERSION.

    Rows from an older derivation are deliberately excluded, so bumping DERIVED_VERSION
    makes the next reconcile re-fetch them instead of trusting superseded logic.
    """
    conn = _connect(path or db_path(config))
    try:
        return {row[0] for row in conn.execute(
            "SELECT training_id FROM session_stats_scanned WHERE derived_version = ?",
            (DERIVED_VERSION,))}
    finally:
        conn.close()


def store_session(config, training_id, day, exercises, session_type=None, unreadable="",
                  path=None):
    """Cache one session's per-exercise numbers, replacing anything held for it.

    `exercises` are session-detail rows already reduced to
    {name, groupId, volume, maxWeight, sets, reps}. A session with none is still recorded
    as scanned — see the module note.

    `unreadable` records why a session has no detail and never will: Speediance refuses
    detail for a session whose custom template was later deleted ("Template has been
    deleted"), which is permanent. Marking it stops a weekly retry forever, and keeps the
    reason visible instead of leaving it indistinguishable from a genuinely empty session.
    """
    training_id, day = int(training_id), _day(day)
    now = _now_iso()
    rows = []
    for ex in exercises or []:
        name = str(ex.get("name") or "").strip()
        if not name:
            continue
        rows.append((training_id, name,
                     int(ex["groupId"]) if ex.get("groupId") is not None else None, day,
                     round(float(ex.get("volume") or 0), 1),
                     round(float(ex.get("maxWeight") or 0), 2),
                     int(ex.get("sets") or 0), int(ex.get("reps") or 0),
                     DERIVED_VERSION, now))
    conn = _connect(path or db_path(config))
    try:
        with conn:
            conn.execute("DELETE FROM session_exercise_stats WHERE training_id = ?", (training_id,))
            if rows:
                conn.executemany(
                    "INSERT INTO session_exercise_stats (training_id, name, group_id, day, volume, "
                    "max_weight, sets, reps, derived_version, cached_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.execute(
                "INSERT INTO session_stats_scanned (training_id, day, session_type, exercise_count, "
                "unreadable, derived_version, cached_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(training_id) DO UPDATE SET day = excluded.day, "
                "session_type = excluded.session_type, exercise_count = excluded.exercise_count, "
                "unreadable = excluded.unreadable, "
                "derived_version = excluded.derived_version, cached_at = excluded.cached_at",
                (training_id, day, session_type, len(rows), str(unreadable or "")[:200],
                 DERIVED_VERSION, now))
        return len(rows)
    finally:
        conn.close()


def forget_sessions(config, training_ids, path=None):
    """Drop cached sessions — used when Speediance no longer lists them (deleted in the
    app). Leaving them would let a workout the user removed keep setting personal bests."""
    ids = [(int(i),) for i in training_ids or []]
    if not ids:
        return 0
    conn = _connect(path or db_path(config))
    try:
        with conn:
            conn.executemany("DELETE FROM session_exercise_stats WHERE training_id = ?", ids)
            cursor = conn.executemany("DELETE FROM session_stats_scanned WHERE training_id = ?", ids)
        return len(ids)
    finally:
        conn.close()


def cached_days(config, start=None, end=None, path=None):
    """{training id: day} for scanned sessions, optionally bounded to a window.

    The bound matters: a reconcile may only judge a session "deleted in the app" when it
    lies inside the range Speediance was actually asked about.
    """
    where, params = ["1 = 1"], []
    if start:
        where.append("day >= ?")
        params.append(_day(start))
    if end:
        where.append("day <= ?")
        params.append(_day(end))
    conn = _connect(path or db_path(config))
    try:
        return {int(tid): day for tid, day in conn.execute(
            f"SELECT training_id, day FROM session_stats_scanned WHERE {' AND '.join(where)}",
            params)}
    finally:
        conn.close()


def daily_rows(config, start=None, end=None, path=None):
    """Cached stats as {exercise name: [{dayStr, maxWeight, totalCapacity, source}]}.

    One row per exercise per DAY: two sessions on the same day are summed, because a
    day's volume is a day's volume however many times the machine was switched on. This
    is the shape dashboard.personal_records reads.
    """
    where, params = ["derived_version = ?"], [DERIVED_VERSION]
    if start:
        where.append("day >= ?")
        params.append(_day(start))
    if end:
        where.append("day <= ?")
        params.append(_day(end))
    conn = _connect(path or db_path(config))
    try:
        rows = conn.execute(
            "SELECT name, day, SUM(volume) AS volume, MAX(max_weight) AS max_weight "
            f"FROM session_exercise_stats WHERE {' AND '.join(where)} "
            "GROUP BY name, day ORDER BY name, day", params).fetchall()
    finally:
        conn.close()
    out = {}
    for name, day, volume, max_weight in rows:
        out.setdefault(name, []).append({
            "dayStr": day, "totalCapacity": round(volume or 0, 1),
            "maxWeight": round(max_weight or 0, 2), "source": "machine"})
    return out


def group_ids(config, path=None):
    """{exercise name: group id} from the cache, newest session wins where they differ."""
    conn = _connect(path or db_path(config))
    try:
        rows = conn.execute(
            "SELECT name, group_id FROM session_exercise_stats "
            "WHERE group_id IS NOT NULL AND derived_version = ? ORDER BY day",
            (DERIVED_VERSION,)).fetchall()
    finally:
        conn.close()
    return {name: int(gid) for name, gid in rows}


def summary(config, path=None):
    """What the cache holds — for the reconcile report and the settings page."""
    conn = _connect(path or db_path(config))
    try:
        sessions, first, last = conn.execute(
            "SELECT COUNT(*), MIN(day), MAX(day) FROM session_stats_scanned "
            "WHERE derived_version = ?", (DERIVED_VERSION,)).fetchone()
        exercises, = conn.execute(
            "SELECT COUNT(*) FROM session_exercise_stats WHERE derived_version = ?",
            (DERIVED_VERSION,)).fetchone()
        stale, = conn.execute(
            "SELECT COUNT(*) FROM session_stats_scanned WHERE derived_version <> ?",
            (DERIVED_VERSION,)).fetchone()
        unreadable, = conn.execute(
            "SELECT COUNT(*) FROM session_stats_scanned WHERE unreadable <> '' "
            "AND derived_version = ?", (DERIVED_VERSION,)).fetchone()
        return {"sessions": sessions or 0, "exerciseRows": exercises or 0,
                "firstDay": first, "lastDay": last, "staleSessions": stale or 0,
                "unreadableSessions": unreadable or 0, "derivedVersion": DERIVED_VERSION}
    finally:
        conn.close()
