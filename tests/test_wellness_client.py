import base64, hashlib, json, os, tempfile, unittest
from unittest import mock
import wellness_client as wc

AUTH_META = {
    "authorization_endpoint": "https://wellnessproject.ai/api/oauth/authorize",
    "token_endpoint": "https://wellnessproject.ai/api/oauth/token",
    "registration_endpoint": "https://wellnessproject.ai/api/oauth/register",
}

def _resp(json_body=None, status=200, text=""):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.text = text or json.dumps(json_body or {})
    return r

class TestOAuth(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.c = wc.WellnessClient(
            base_dir=self.d,
            tokens_file=os.path.join(self.d, "wellness_tokens.json"),
            pending_file=os.path.join(self.d, "wellness_pending.json"))
        self.c._auth_meta = dict(AUTH_META)  # skip discovery in tests

    def test_pkce_challenge_is_sha256_of_verifier(self):
        v, ch = self.c._pkce_pair()
        expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(ch, expect)
        self.assertNotIn("=", v)

    def test_begin_then_complete_persists_tokens(self):
        redirect = "https://speediance.labattsimon.com/wp/callback"
        with mock.patch.object(self.c, "_register_client", return_value="client-123"):
            url = self.c.begin_authorization(redirect)
        self.assertIn("code_challenge=", url)
        self.assertIn("client_id=client-123", url)
        # recover the state we just stored
        pending = json.load(open(self.c.pending_file))
        state = next(iter(pending))
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp({"access_token": "AT", "refresh_token": "RT",
                                            "expires_in": 3600})):
            self.c.complete_authorization("the-code", state, redirect)
        self.assertTrue(self.c.is_connected())
        saved = json.load(open(self.c.tokens_file))
        self.assertEqual(saved["refresh_token"], "RT")

    def test_complete_rejects_unknown_state(self):
        with self.assertRaises(wc.WellnessAuthError):
            self.c.complete_authorization("code", "bogus-state",
                                          "https://x/wp/callback")

    def test_refresh_rotation_persists_new_refresh_token(self):
        self.c._save_tokens({"client_id": "c", "access_token": "old",
                             "refresh_token": "RT1", "expires_at": 0})  # expired
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp({"access_token": "AT2", "refresh_token": "RT2",
                                            "expires_in": 3600})):
            tok = self.c._valid_access_token()
        self.assertEqual(tok, "AT2")
        self.assertEqual(json.load(open(self.c.tokens_file))["refresh_token"], "RT2")

    def test_invalid_grant_clears_and_raises(self):
        self.c._save_tokens({"client_id": "c", "access_token": "old",
                             "refresh_token": "RT1", "expires_at": 0})
        with mock.patch("wellness_client.requests.post",
                        return_value=_resp({"error": "invalid_grant"}, status=400)):
            with self.assertRaises(wc.WellnessAuthError):
                self.c._valid_access_token()
        self.assertFalse(self.c.is_connected())
