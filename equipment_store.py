"""Shared owned / unusable equipment store.

The MCP server's SQLite `preferences` table is the single source of truth for what the
athlete owns and what they own but cannot use, so the web app and claude.ai can never
disagree about it (roadmap #28). Equipment is stored BY NAME, because Speediance lists
the same physical accessory under several ids.

Two states, not one:
  owned     — the accessory is in the gym
  unusable  — it is owned but must never be planned (an injury, a bench they can't
              lie on). Unowned gear is simply absent; unusable gear is present and
              would otherwise pass every ownership filter.

Same connection discipline as avoided_store: one short-lived connection per call, with
a timeout so a momentary lock from the MCP process waits instead of failing.
"""

import json
import os
import sqlite3

from avoided_store import DEFAULT_PATH, db_path  # one shared file, one resolution rule

OWNED_KEY = "owned_equipment"
UNUSABLE_KEY = "unusable_equipment"

_DDL = "CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);"


def _connect(path):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.execute(_DDL)
    return conn


def _clean(names):
    """Trimmed, de-duplicated names, first spelling wins. Case is preserved for display
    but compared case-insensitively, since the two apps may differ on capitalisation."""
    out, seen = [], set()
    for name in names or []:
        text = str(name).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def _read_list(conn, key):
    row = conn.execute("SELECT value_json FROM preferences WHERE key = ?", (key,)).fetchone()
    if not row:
        return []
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError):
        return []
    return _clean(value) if isinstance(value, list) else []


def _write_list(conn, key, names):
    conn.execute("INSERT INTO preferences (key, value_json) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                 (key, json.dumps(_clean(names))))


def get_equipment(config=None, path=None):
    """{'owned': [names], 'unusable': [names]} from the shared store."""
    target = path or db_path(config)
    conn = _connect(target)
    try:
        return {"owned": _read_list(conn, OWNED_KEY), "unusable": _read_list(conn, UNUSABLE_KEY)}
    finally:
        conn.close()


def set_equipment(owned=None, unusable=None, config=None, path=None):
    """Replace either list. Passing None leaves that list untouched.

    Both writes commit together, so the pair can never be left half-updated with a
    name marked unusable that is no longer owned.
    """
    target = path or db_path(config)
    conn = _connect(target)
    try:
        with conn:
            if owned is not None:
                _write_list(conn, OWNED_KEY, owned)
            if unusable is not None:
                _write_list(conn, UNUSABLE_KEY, unusable)
        return {"owned": _read_list(conn, OWNED_KEY), "unusable": _read_list(conn, UNUSABLE_KEY)}
    finally:
        conn.close()


def usable_names(equipment):
    """Owned minus unusable — what may actually be planned."""
    unusable = {n.lower() for n in equipment.get("unusable", [])}
    return [n for n in equipment.get("owned", []) if n.lower() not in unusable]


def owned_ids(equipment, catalog_entries):
    """The accessory ids behind the USABLE names, for the id-based exercise filters.

    `catalog_entries` are deduped accessory entries ({'name', 'ids'}), so one usable
    name contributes every id Speediance files it under.
    """
    wanted = {n.lower() for n in usable_names(equipment)}
    ids = []
    for entry in catalog_entries or []:
        if entry["name"].lower() in wanted:
            for number in entry["ids"]:
                if number not in ids:
                    ids.append(number)
    return ids
