"""Off-machine training sets — the exercise detail Speediance cannot hold.

Speediance's own manual log (session type 10) fixes the things that depend only on a
day having happened: streaks, days-exercised, training minutes, calories. What it does
NOT store is what you actually did — `freeTrainingDetail` for a manual session returns
`[]`. And there is no way to put that detail into Speediance from outside: the
`app/freetraining/save` route is an UPDATE into a session row the machine itself
created (asking `getFreeTrainingId` for a client-invented uuid returns null), so a
session that never ran on the hardware cannot be written at all.

So the detail lives here, next to the machine's data rather than pretending to be it:

  Speediance  — the day happened, for how long, how many calories  (authoritative)
  this table  — which movements, how many sets and reps, at what load

Rows are keyed by Speediance exercise GROUP id, which is what makes this worth doing:
a group id resolves through the exercise library to muscles and a body part, so a
hotel dumbbell row counts towards volume-by-muscle and can set a personal best exactly
like a machine set. A set whose movement has no Speediance equivalent is still worth
recording, and carries group_id NULL — it counts towards the log and the day, but not
towards per-muscle attribution, because there is nothing to attribute it to.

WEIGHT UNITS: stored in the account's DISPLAY unit, the same convention Speediance
itself uses on both read and write paths (it applies no conversion in either
direction). Never convert on the way in or out — a number in this table means the same
thing as the number on the Speediance set beside it.

Connection discipline matches avoided_store: one short-lived connection per call with a
timeout, because the MCP process may hold the same file open. The path comes from
avoided_store.db_path so there is exactly one rule for locating the shared store — and
so the test suite's AVOIDED_DB_PATH isolation covers this table too.
"""

import datetime
import sqlite3

from avoided_store import DEFAULT_PATH, db_path, _connect as _base_connect  # noqa: F401

MAX_NAME_LEN = 120
MAX_NOTE_LEN = 300
MAX_LOCATION_LEN = 60

SIDES = ("both", "left", "right")

# leftRight codes, matching the machine's own vocabulary so the adapters can hand
# muscle_balance.set_load a set it already knows how to read: 1 = left only,
# 2 = right only, 0/None = both sides together.
SIDE_CODES = {"left": 1, "right": 2, "both": 0}

_DDL = """
CREATE TABLE IF NOT EXISTS offmachine_sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  training_id INTEGER,
  group_id INTEGER,
  name TEXT NOT NULL,
  set_index INTEGER NOT NULL,
  reps INTEGER NOT NULL,
  weight REAL NOT NULL DEFAULT 0,
  side TEXT NOT NULL DEFAULT 'both' CHECK (side IN ('both', 'left', 'right')),
  location TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS offmachine_sets_day ON offmachine_sets (day);
"""


def _connect(path):
    """Short-lived connection with the table present.

    avoided_store._connect is reused for the directory creation and timeout, then the
    off-machine DDL is applied on top: the two projects share one file, and each module
    is responsible for its own tables existing.
    """
    conn = sqlite3.connect(path, timeout=5)
    conn.executescript(_DDL)
    return conn


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(value):
    """A YYYY-MM-DD string, or ValueError. Accepts a date/datetime or an ISO string."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()[:10]
    datetime.date.fromisoformat(text)  # raises ValueError on anything malformed
    return text


def _positive_int(value, field):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number, got {value!r}")
    if number <= 0:
        raise ValueError(f"{field} must be greater than zero, got {number}")
    return number


def _weight(value):
    """Load for one set. Zero is legitimate — a bodyweight movement is not an error."""
    if value in (None, ""):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"weight must be a number, got {value!r}")
    if number < 0:
        raise ValueError(f"weight cannot be negative, got {number}")
    return round(number, 2)


def _side(value):
    text = str(value or "both").strip().lower()
    if text not in SIDES:
        raise ValueError(f"side must be one of {SIDES}, got {value!r}")
    return text


def _row(record):
    return {"id": record["id"], "day": record["day"], "trainingId": record["training_id"],
            "groupId": record["group_id"], "name": record["name"],
            "setIndex": record["set_index"], "reps": record["reps"],
            "weight": record["weight"], "side": record["side"],
            "location": record["location"], "note": record["note"]}


def add_sets(config, day, sets, training_id=None, location="", path=None):
    """Record the sets of one off-machine session. Returns the stored rows.

    `sets` is a list of dicts: name (required), groupId, reps, weight, side, note.
    set_index is assigned per exercise in the order given, so "3 sets of 10" arrives as
    three entries and reads back as sets 1, 2, 3 of that movement.

    Validation is strict and raises ValueError rather than storing a half-understood
    set: a silently-dropped rep count would quietly corrupt a personal best.
    """
    day = _day(day)
    if not sets:
        raise ValueError("no sets given")
    location = str(location or "").strip()[:MAX_LOCATION_LEN]
    training_id = int(training_id) if training_id not in (None, "") else None

    prepared, counters = [], {}
    for entry in sets:
        entry = entry or {}
        name = str(entry.get("name") or "").strip()[:MAX_NAME_LEN]
        if not name:
            raise ValueError("every set needs an exercise name")
        group_id = entry.get("groupId")
        group_id = int(group_id) if group_id not in (None, "") else None
        # Sets of the same movement number consecutively; a set index is per exercise,
        # not per session, so "set 2" always means the second set of THAT movement.
        key = (group_id, name.lower())
        counters[key] = counters.get(key, 0) + 1
        prepared.append((day, training_id, group_id, name, counters[key],
                         _positive_int(entry.get("reps"), "reps"),
                         _weight(entry.get("weight")), _side(entry.get("side")),
                         location, str(entry.get("note") or "").strip()[:MAX_NOTE_LEN],
                         _now_iso()))

    conn = _connect(path or db_path(config))
    try:
        with conn:
            conn.executemany(
                "INSERT INTO offmachine_sets (day, training_id, group_id, name, set_index, "
                "reps, weight, side, location, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", prepared)
        return list_sets(config, day, day, path=path or db_path(config))
    finally:
        conn.close()


def list_sets(config, start, end, path=None):
    """Every off-machine set between two dates, inclusive, oldest first."""
    start, end = _day(start), _day(end)
    conn = _connect(path or db_path(config))
    conn.row_factory = sqlite3.Row
    try:
        # Ordered by id, which is INSERTION order and therefore the order the exercises
        # were actually performed. Ordering by name instead sorted a session alphabetically
        # and silently rewrote the workout: a chest press done first appeared after a
        # biceps curl. set_index already orders the sets within one movement.
        rows = conn.execute(
            "SELECT * FROM offmachine_sets WHERE day >= ? AND day <= ? "
            "ORDER BY day, id", (start, end)).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def days_logged(config, start, end, path=None):
    """The distinct days in range that have off-machine sets."""
    return sorted({row["day"] for row in list_sets(config, start, end, path=path)})


def list_for_session(config, training_id=None, day=None, path=None):
    """Sets belonging to one Speediance manual session.

    Two ways in, because a set may have been logged before its Speediance manual record
    existed (or without anyone linking the two): by explicit training_id when it was
    linked, otherwise by the session's calendar day. The training_id match wins when
    both are possible, so an explicitly linked set is never mixed with unrelated work
    that happens to share the date.
    """
    conn = _connect(path or db_path(config))
    conn.row_factory = sqlite3.Row
    try:
        if training_id not in (None, ""):
            rows = conn.execute(
                "SELECT * FROM offmachine_sets WHERE training_id = ? ORDER BY id",
                (int(training_id),)).fetchall()
            if rows:
                return [_row(r) for r in rows]
        if day in (None, ""):
            return []
        rows = conn.execute(
            "SELECT * FROM offmachine_sets WHERE day = ? ORDER BY id",
            (_day(day),)).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()


def delete_day(config, day, path=None):
    """Remove every set logged for one day. Returns how many rows went."""
    day = _day(day)
    conn = _connect(path or db_path(config))
    try:
        with conn:
            cursor = conn.execute("DELETE FROM offmachine_sets WHERE day = ?", (day,))
        return cursor.rowcount
    finally:
        conn.close()


def delete_set(config, set_id, path=None):
    """Remove one set by id. Returns True when a row was actually removed."""
    conn = _connect(path or db_path(config))
    try:
        with conn:
            cursor = conn.execute("DELETE FROM offmachine_sets WHERE id = ?", (int(set_id),))
        return cursor.rowcount > 0
    finally:
        conn.close()
