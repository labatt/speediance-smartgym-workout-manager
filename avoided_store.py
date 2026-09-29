"""Shared 'avoided exercises' store.

This SQLite table is owned jointly with the speediance-mcp project's memory.py — both
processes read and write the same file (see the shared-schema contract). This module
only ever creates/reads/writes 'avoided' rows: it never deletes or overwrites a
'preferred' mark, except that explicitly marking a movement avoided replaces whatever
mark it had before (a movement is one or the other, never both).

Pure-ish: no Flask, no app state. Each function opens one short-lived sqlite3
connection, runs its query, and closes it — the MCP server may hold a connection open
longer, so `timeout=5` on connect lets a momentary lock wait instead of failing.
"""

import datetime
import os
import sqlite3

DEFAULT_PATH = os.path.expanduser("~/.config/speediance-mcp/speediance-mcp.db")

MAX_REASON_LEN = 200

_DDL = """
CREATE TABLE IF NOT EXISTS exercise_marks (
  group_id INTEGER PRIMARY KEY,
  mark TEXT NOT NULL CHECK (mark IN ('preferred', 'avoided')),
  name TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT ''
);
"""


def db_path(config):
    """Resolve the shared store path from a config/credentials dict: the
    `avoided_db_path` key when set, else the `AVOIDED_DB_PATH` env var when set
    (the test suite uses this to keep every test off the real, shared DB file even
    when a caller forgets to pass an explicit path), else DEFAULT_PATH."""
    config = config or {}
    explicit = config.get("avoided_db_path")
    if explicit:
        return explicit
    env = os.environ.get("AVOIDED_DB_PATH")
    if env:
        return env
    return DEFAULT_PATH


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path):
    """Open a short-lived connection, creating the parent dir (mode 0700) and the
    table/migration if missing. Caller is responsible for closing it."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute(_DDL)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(exercise_marks)").fetchall()}
    if "reason" not in cols:
        try:
            conn.execute("ALTER TABLE exercise_marks ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            # Another process (this app's other worker, or speediance-mcp) may have run the
            # same migration between our PRAGMA check and this ALTER. Re-check rather than
            # assume that's what happened: only swallow the error if the column is now
            # actually there; otherwise it was a real failure and must surface.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(exercise_marks)").fetchall()}
            if "reason" not in cols:
                raise
    conn.commit()
    return conn


def list_avoided(path):
    """[{group_id, name, reason, updated_at}, ...] for every 'avoided' row, sorted by
    name case-insensitively."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT group_id, name, reason, updated_at FROM exercise_marks "
            "WHERE mark = 'avoided'"
        ).fetchall()
    finally:
        conn.close()
    out = [
        {"group_id": r[0], "name": r[1], "reason": r[2], "updated_at": r[3]}
        for r in rows
    ]
    out.sort(key=lambda e: (e["name"] or "").casefold())
    return out


def avoided_ids(path):
    """set[int] of every avoided group_id."""
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT group_id FROM exercise_marks WHERE mark = 'avoided'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def set_avoided(path, group_id, name, reason=""):
    """Mark `group_id` avoided (upsert), replacing any prior mark (including
    'preferred') on that row. `reason` is stripped and capped at MAX_REASON_LEN."""
    group_id = int(group_id)
    reason = (reason or "").strip()
    if len(reason) > MAX_REASON_LEN:
        raise ValueError(f"reason must be {MAX_REASON_LEN} characters or fewer")
    name = (name or "").strip()
    conn = _connect(path)
    try:
        conn.execute(
            "INSERT INTO exercise_marks (group_id, mark, name, updated_at, reason) "
            "VALUES (?, 'avoided', ?, ?, ?) "
            "ON CONFLICT(group_id) DO UPDATE SET "
            "mark = 'avoided', name = excluded.name, "
            "updated_at = excluded.updated_at, reason = excluded.reason",
            (group_id, name, _now_iso(), reason),
        )
        conn.commit()
    finally:
        conn.close()


def clear_avoided(path, group_id):
    """Delete the row for `group_id` ONLY if it is currently marked 'avoided' — a
    'preferred' row is never touched. Returns True if a row was removed."""
    group_id = int(group_id)
    conn = _connect(path)
    try:
        cur = conn.execute(
            "DELETE FROM exercise_marks WHERE group_id = ? AND mark = 'avoided'",
            (group_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
