"""Wellness Project MCP client for the Speediance app.

WP exposes no REST API — its MCP endpoint is the API, gated by OAuth
(authorization_code + PKCE + refresh_token; no machine grant). This module
handles the OAuth lifecycle (register once, authorize once in a browser, refresh
silently forever) and the MCP JSON-RPC transport. Tokens live only in
wellness_tokens.json (chmod 600) and are never logged or rendered."""

import base64, hashlib, json, os, secrets, time
import requests

BASE = "https://wellnessproject.ai"
MCP_URL = f"{BASE}/api/mcp"
AS_METADATA_URL = f"{BASE}/.well-known/oauth-authorization-server"
SCOPE = "mcp"
CLIENT_NAME = "Speediance Backfill"
PENDING_TTL = 600  # seconds
MCP_PROTOCOL_VERSION = "2025-06-18"


class WellnessAPIError(Exception):
    """Base Wellness Project failure."""

class WellnessAuthError(WellnessAPIError):
    """Missing/expired/revoked credentials — user must (re)connect."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _parse_rpc_body(resp):
    """Return the JSON-RPC object from a raw-JSON or SSE MCP response.
    For SSE, prefer the last event carrying a result/error — MCP streamable-HTTP
    may emit notification events before the tools/call result on the same stream."""
    try:
        return resp.json()
    except ValueError:
        pass
    chosen = None      # last event with result/error
    last_any = None    # last parseable data event (fallback)
    for line in resp.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            obj = json.loads(line[len("data:"):].strip())
        except ValueError:
            continue
        last_any = obj
        if isinstance(obj, dict) and ("result" in obj or "error" in obj):
            chosen = obj
    result = chosen if chosen is not None else last_any
    if result is None:
        raise WellnessAPIError("unparseable MCP response")
    return result


def _write_secure_json(path, obj):
    """Write JSON to path with 0600 perms from creation — no window where the
    file exists world/group readable. Used for both the tokens file and the
    pending-authorization file (which holds PKCE verifiers)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)


class WellnessClient:
    def __init__(self, base_dir=None, tokens_file=None, pending_file=None):
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.tokens_file = tokens_file or os.path.join(self.base_dir, "wellness_tokens.json")
        self.pending_file = pending_file or os.path.join(self.base_dir, "wellness_pending.json")
        self.tokens = self._load_json(self.tokens_file, {})
        self._auth_meta = None

    # ---- persistence ----
    def _load_json(self, path, default):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default

    def _save_tokens(self, tokens):
        self.tokens = tokens
        _write_secure_json(self.tokens_file, tokens)

    def is_connected(self):
        return bool(self.tokens.get("refresh_token"))

    # ---- discovery ----
    def _meta(self):
        if self._auth_meta is None:
            r = requests.get(AS_METADATA_URL, timeout=20)
            if r.status_code != 200:
                raise WellnessAPIError(f"AS metadata {r.status_code}")
            self._auth_meta = r.json()
        return self._auth_meta

    def _register_client(self, redirect_uri):
        if self.tokens.get("client_id"):
            return self.tokens["client_id"]
        body = {
            "client_name": CLIENT_NAME, "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "scope": SCOPE,
        }
        r = requests.post(self._meta()["registration_endpoint"], json=body, timeout=20)
        if r.status_code not in (200, 201):
            raise WellnessAPIError(f"DCR failed {r.status_code}")
        cid = r.json()["client_id"]
        self.tokens["client_id"] = cid
        self._save_tokens(self.tokens)
        return cid

    # ---- PKCE + authorize ----
    def _pkce_pair(self):
        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        return verifier, challenge

    def begin_authorization(self, redirect_uri):
        client_id = self._register_client(redirect_uri)
        # _register_client normally persists this itself, but don't rely on that
        # alone — keep self.tokens authoritative so complete_authorization can
        # always find the client_id it needs for the token exchange.
        self.tokens["client_id"] = client_id
        verifier, challenge = self._pkce_pair()
        state = secrets.token_urlsafe(24)
        pending = self._load_json(self.pending_file, {})
        # drop expired entries, add this one
        now = time.time()
        pending = {k: v for k, v in pending.items() if now - v.get("ts", 0) < PENDING_TTL}
        pending[state] = {"verifier": verifier, "ts": now}
        # Known race: concurrent begin/complete calls (e.g. multiple worker
        # processes) can read-modify-write this file non-atomically and lose
        # an entry. Left unlocked deliberately — it fails safe, just forcing
        # the user to restart authorization, not a security issue.
        _write_secure_json(self.pending_file, pending)
        from urllib.parse import urlencode
        q = urlencode({
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "scope": SCOPE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return f"{self._meta()['authorization_endpoint']}?{q}"

    def complete_authorization(self, code, state, redirect_uri):
        pending = self._load_json(self.pending_file, {})
        entry = pending.pop(state, None)
        # Known race: see the comment in begin_authorization — unlocked, fails safe.
        _write_secure_json(self.pending_file, pending)
        if not entry or time.time() - entry.get("ts", 0) >= PENDING_TTL:
            raise WellnessAuthError("unknown or expired OAuth state")
        r = requests.post(self._meta()["token_endpoint"], data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "client_id": self.tokens["client_id"],
            "code_verifier": entry["verifier"],
        }, timeout=20)
        if r.status_code != 200:
            raise WellnessAuthError(f"token exchange failed {r.status_code}")
        self._store_token_response(r.json())

    def _store_token_response(self, body):
        toks = dict(self.tokens)
        toks["access_token"] = body["access_token"]
        if body.get("refresh_token"):
            toks["refresh_token"] = body["refresh_token"]
        toks["expires_at"] = time.time() + int(body.get("expires_in", 3600))
        self._save_tokens(toks)

    def _valid_access_token(self):
        if not self.tokens.get("refresh_token"):
            raise WellnessAuthError("not connected")
        if self.tokens.get("access_token") and time.time() < self.tokens.get("expires_at", 0) - 60:
            return self.tokens["access_token"]
        r = requests.post(self._meta()["token_endpoint"], data={
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"],
            "client_id": self.tokens["client_id"],
        }, timeout=20)
        if r.status_code != 200:
            self._save_tokens({"client_id": self.tokens.get("client_id")})  # clear creds
            raise WellnessAuthError("refresh failed — reconnect required")
        self._store_token_response(r.json())
        return self.tokens["access_token"]

    # ---- MCP transport ----
    def _call_tool(self, name, arguments):
        token = self._valid_access_token()
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments}}
        resp = requests.post(MCP_URL, json=payload, timeout=60, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        })
        if resp.status_code == 401:
            raise WellnessAuthError("Wellness Project rejected the token (401)")
        if resp.status_code != 200:
            raise WellnessAPIError(f"MCP call {name} -> {resp.status_code}")
        body = _parse_rpc_body(resp)
        if "error" in body:
            raise WellnessAPIError(f"MCP error: {body['error']}")
        parts = body.get("result", {}).get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text")

    def list_workouts(self, start_date, end_date):
        return self._call_tool("list_workouts",
                               {"start_date": start_date, "end_date": end_date})

    def get_workout(self, session_id):
        return self._call_tool("get_workout", {"session_id": session_id})

    def update_workout(self, session_id, add_exercises, notes=None):
        args = {"session_id": session_id, "add_exercises": add_exercises}
        if notes is not None:
            args["notes"] = notes
        return self._call_tool("update_workout", args)
