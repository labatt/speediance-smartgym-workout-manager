"""Read side of the shared curated fact store, plus archiving.

The MCP server's `curated_facts` table is the source of truth (roadmap #30). This module
READS it for the Memory page and can ARCHIVE a row, which is the one write that needs no
validation. Creating and superseding facts stay in the MCP server, where the length
limit, near-duplicate check and supersede transaction live — duplicating those here would
mean two rule sets that could drift apart.

A fact's status is derived, not stored: it is archived if it was superseded, explicitly
archived, or has expired.
"""

import datetime
import json
import sqlite3

from avoided_store import db_path  # one shared file, one resolution rule

KIND_GROUPS = ("constraint", "preference", "goal", "observation")
RECENT_OBSERVATIONS = 10

_COLUMNS = ("id, text, kind, severity, category, scope, supersedes_json, superseded_by, "
            "source, created_at, expires_at, archived_at, legacy")


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(path):
    return sqlite3.connect(path, timeout=5)


def _row(record, now):
    (fact_id, text, kind, severity, category, scope, supersedes_json, superseded_by,
     source, created_at, expires_at, archived_at, legacy) = record
    expired = bool(expires_at and str(expires_at) <= now)
    try:
        supersedes = json.loads(supersedes_json or "[]")
    except (TypeError, ValueError):
        supersedes = []
    return {
        "id": fact_id, "text": text, "kind": kind, "severity": severity, "category": category,
        "scope": scope, "supersedes": supersedes, "supersededBy": superseded_by,
        "source": source, "created": str(created_at)[:10], "expiresAt": expires_at,
        "legacy": bool(legacy),
        "archived": bool(superseded_by or archived_at or expired),
        "archivedReason": ("superseded by #%s" % superseded_by if superseded_by
                           else "expired" if expired else "archived" if archived_at else None),
    }


def list_facts(config=None, path=None, include_archived=False):
    """Facts grouped for display.

    Returns constraints split hard/soft, preferences, goals, the most recent
    observations, everything still awaiting curation, and the counts behind them.
    """
    target = path or db_path(config)
    conn = _connect(target)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS curated_facts (id INTEGER PRIMARY KEY)")
        try:
            records = conn.execute(f"SELECT {_COLUMNS} FROM curated_facts ORDER BY id").fetchall()
        except sqlite3.OperationalError:
            return _empty()          # the MCP server has not created the table yet
    finally:
        conn.close()

    now = _now_iso()
    rows = [_row(r, now) for r in records]
    live = [r for r in rows if not r["archived"]]
    shown = rows if include_archived else live
    legacy = [r for r in live if r["legacy"]]
    grouped = {
        "hard": [r for r in shown if r["kind"] == "constraint" and r["severity"] == "hard"],
        "soft": [r for r in shown if r["kind"] == "constraint" and r["severity"] == "soft"],
        "preferences": [r for r in shown if r["kind"] == "preference"],
        "goals": [r for r in shown if r["kind"] == "goal"],
        # Observations are dated findings with no forward authority, so only the newest matter.
        "observations": [r for r in shown if r["kind"] == "observation"][-RECENT_OBSERVATIONS:][::-1],
    }
    return {**grouped, "legacy": legacy, "archived": [r for r in rows if r["archived"]],
            "total": len(rows), "activeTotal": len(live), "legacyTotal": len(legacy)}


def _empty():
    return {"hard": [], "soft": [], "preferences": [], "goals": [], "observations": [],
            "legacy": [], "archived": [], "total": 0, "activeTotal": 0, "legacyTotal": 0}


def archive_fact(fact_id, config=None, path=None):
    """Archive one fact. Archived facts stay queryable but leave every default read.

    Returns True if a live fact was archived, False if the id is unknown or already
    archived — so the caller can tell 'done' from 'nothing to do'.
    """
    target = path or db_path(config)
    conn = _connect(target)
    try:
        with conn:
            changed = conn.execute(
                "UPDATE curated_facts SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
                (_now_iso(), int(fact_id))).rowcount
        return bool(changed)
    finally:
        conn.close()
