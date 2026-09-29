"""Read side of the MCP server's OAuth store, plus revoking a client.

The MCP server owns oauth.db (roadmap #23). This module reports which AI clients are
connected and can revoke one, which is the equivalent of `speediance-mcp revoke`.

Tokens are stored only as hashes, so nothing here can reveal a credential — the page
shows counts and times, never a token.
"""

import json
import os
import sqlite3
import time

DEFAULT_PATH = os.path.expanduser("~/.config/speediance-mcp/oauth.db")


def db_path(config=None, path=None):
    """Explicit path, else the `oauth_db_path` config key, else OAUTH_DB_PATH (the test
    suite uses it to stay off the real store), else DEFAULT_PATH."""
    if path:
        return path
    explicit = (config or {}).get("oauth_db_path")
    if explicit:
        return explicit
    return os.environ.get("OAUTH_DB_PATH") or DEFAULT_PATH


def _connect(target):
    return sqlite3.connect(target, timeout=5)


def list_connections(config=None, path=None, now=None):
    """One row per registered AI client, with its live and expired token counts.

    A client with no live refresh token is connected in name only: the next request will
    fail and the user must reconnect. That is reported rather than left to be discovered.
    """
    target = db_path(config, path)
    if not os.path.exists(target):
        return {"connections": [], "available": False,
                "reason": "No remote connections yet — the MCP server hasn't been set up for claude.ai."}
    now = now if now is not None else time.time()
    conn = _connect(target)
    try:
        try:
            clients = conn.execute("SELECT client_id, info_json, created_at FROM clients").fetchall()
            tokens = conn.execute("SELECT client_id, kind, expires_at, revoked FROM tokens").fetchall()
        except sqlite3.OperationalError:
            return {"connections": [], "available": False,
                    "reason": "The connection store isn't initialised yet."}
    finally:
        conn.close()

    by_client = {}
    for client_id, kind, expires_at, revoked in tokens:
        entry = by_client.setdefault(client_id, {"live": 0, "expired": 0, "revoked": 0, "latest": None})
        if revoked:
            entry["revoked"] += 1
        elif (expires_at or 0) > now:
            entry["live"] += 1
            if kind == "refresh":
                entry["latest"] = max(entry["latest"] or 0, expires_at)
        else:
            entry["expired"] += 1

    rows = []
    for client_id, info_json, created_at in clients:
        try:
            info = json.loads(info_json)
        except (TypeError, ValueError):
            info = {}
        counts = by_client.get(client_id, {"live": 0, "expired": 0, "revoked": 0, "latest": None})
        rows.append({
            "clientId": client_id,
            "name": info.get("client_name") or "Unnamed client",
            "created": _stamp(created_at),
            "liveTokens": counts["live"],
            "expiredTokens": counts["expired"],
            "revokedTokens": counts["revoked"],
            "refreshUntil": _stamp(counts["latest"]),
            "connected": counts["live"] > 0,
        })
    rows.sort(key=lambda r: (not r["connected"], r["name"].lower()))
    return {"connections": rows, "available": True, "reason": None}


def _stamp(value):
    if not value:
        return None
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))


def revoke_client(client_id, config=None, path=None):
    """Revoke every token for one client. Returns how many were revoked.

    The client registration is left in place: revoking ends the session, and the same
    client reconnecting is a normal sign-in, not a re-registration.
    """
    target = db_path(config, path)
    if not os.path.exists(target):
        return 0
    conn = _connect(target)
    try:
        with conn:
            return conn.execute(
                "UPDATE tokens SET revoked = 1 WHERE client_id = ? AND revoked = 0",
                (str(client_id),)).rowcount
    finally:
        conn.close()
