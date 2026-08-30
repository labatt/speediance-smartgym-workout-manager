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


class WellnessAPIError(Exception):
    """Base Wellness Project failure."""

class WellnessAuthError(WellnessAPIError):
    """Missing/expired/revoked credentials — user must (re)connect."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


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
        with open(self.tokens_file, "w") as f:
            json.dump(tokens, f)
        try:
            os.chmod(self.tokens_file, 0o600)
        except OSError:
            pass

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
        with open(self.pending_file, "w") as f:
            json.dump(pending, f)
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
        with open(self.pending_file, "w") as f:
            json.dump(pending, f)
        if not entry:
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
