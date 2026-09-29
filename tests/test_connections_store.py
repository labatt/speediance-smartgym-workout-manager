"""Connect AI page: reading the MCP server's OAuth store, and revoking a client.

Tokens live in that store only as hashes, so nothing here can surface a credential.
Tests run against a temp DB, never the real oauth.db.
"""
import json, os, sqlite3, sys, tempfile, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import connections_store  # noqa: E402
import app as app_module  # noqa: E402

DDL = """
CREATE TABLE clients (client_id TEXT PRIMARY KEY, info_json TEXT NOT NULL, created_at REAL);
CREATE TABLE tokens (token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
  family TEXT NOT NULL, scopes_json TEXT NOT NULL, resource TEXT, expires_at REAL NOT NULL,
  used INTEGER NOT NULL DEFAULT 0, revoked INTEGER NOT NULL DEFAULT 0);
"""
NOW = 1_800_000_000.0


class TestListConnections(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(DDL)
        self.addCleanup(self.conn.close)

    def client_row(self, client_id="c1", name="Claude"):
        self.conn.execute("INSERT INTO clients VALUES (?,?,?)",
                          (client_id, json.dumps({"client_name": name}), NOW - 3600))

    def token(self, client_id="c1", kind="access", expires=NOW + 600, revoked=0, tag=None):
        self.conn.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?)",
                          (tag or f"h{time.time_ns()}", kind, client_id, "fam", "[]", None,
                           expires, 0, revoked))

    def test_a_client_with_live_tokens_reads_as_connected(self):
        self.client_row(); self.token(); self.token(kind="refresh", expires=NOW + 86400)
        self.conn.commit()
        row = connections_store.list_connections(path=self.path, now=NOW)["connections"][0]
        self.assertEqual(row["name"], "Claude")
        self.assertTrue(row["connected"])
        self.assertEqual(row["liveTokens"], 2)
        self.assertIsNotNone(row["refreshUntil"])

    def test_expired_and_revoked_tokens_are_counted_separately(self):
        self.client_row(); self.token(expires=NOW - 10); self.token(revoked=1)
        self.conn.commit()
        row = connections_store.list_connections(path=self.path, now=NOW)["connections"][0]
        self.assertEqual((row["liveTokens"], row["expiredTokens"], row["revokedTokens"]), (0, 1, 1))
        # Registered but with nothing live: the next request fails, so say so.
        self.assertFalse(row["connected"])

    def test_a_client_with_no_tokens_at_all_is_listed_as_needing_reconnection(self):
        self.client_row(); self.conn.commit()
        row = connections_store.list_connections(path=self.path, now=NOW)["connections"][0]
        self.assertFalse(row["connected"])
        self.assertEqual(row["liveTokens"], 0)

    def test_connected_clients_sort_first(self):
        self.client_row("c1", "Zed"); self.client_row("c2", "Alpha")
        self.token("c1"); self.conn.commit()
        names = [r["name"] for r in connections_store.list_connections(path=self.path, now=NOW)["connections"]]
        self.assertEqual(names, ["Zed", "Alpha"])

    def test_no_token_material_is_ever_returned(self):
        self.client_row(); self.token(tag="secret-hash"); self.conn.commit()
        blob = json.dumps(connections_store.list_connections(path=self.path, now=NOW))
        self.assertNotIn("secret-hash", blob)

    def test_a_missing_store_is_reported_not_raised(self):
        got = connections_store.list_connections(path="/nonexistent/oauth.db")
        self.assertFalse(got["available"])
        self.assertIn("hasn't been set up", got["reason"])


class TestRevoke(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        conn = sqlite3.connect(self.path)
        conn.executescript(DDL)
        conn.execute("INSERT INTO clients VALUES ('c1', '{}', 0)")
        for n in range(3):
            conn.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?)",
                         (f"h{n}", "access", "c1", "f", "[]", None, NOW + 600, 0, 0))
        conn.execute("INSERT INTO tokens VALUES ('other','access','c2','f','[]',NULL,?,0,0)", (NOW + 600,))
        conn.commit(); conn.close()

    def test_it_revokes_only_that_clients_tokens(self):
        self.assertEqual(connections_store.revoke_client("c1", path=self.path), 3)
        rows = connections_store.list_connections(path=self.path, now=NOW)["connections"]
        self.assertEqual(rows[0]["revokedTokens"], 3)
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute("SELECT revoked FROM tokens WHERE token_hash='other'").fetchone()[0], 0)
        conn.close()

    def test_revoking_twice_reports_nothing_left(self):
        connections_store.revoke_client("c1", path=self.path)
        self.assertEqual(connections_store.revoke_client("c1", path=self.path), 0)

    def test_an_unknown_client_revokes_nothing(self):
        self.assertEqual(connections_store.revoke_client("nope", path=self.path), 0)


class TestConnectAiPage(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_page_renders_the_connector_url_with_the_mcp_suffix(self):
        with mock.patch.object(app_module.client, 'credentials', {'mcp_public_url': 'https://example.test'}), \
             mock.patch.object(app_module.connections_store, 'list_connections',
                               return_value={"connections": [], "available": True, "reason": None}):
            html = self.client.get('/connect-ai').get_data(as_text=True)
        self.assertIn("https://example.test/mcp", html)

    def test_a_broken_store_warns_instead_of_500ing(self):
        with mock.patch.object(app_module.connections_store, 'list_connections',
                               side_effect=RuntimeError("locked")):
            resp = self.client.get('/connect-ai')
        self.assertEqual(resp.status_code, 200)
        self.assertIn("busy or unavailable", resp.get_data(as_text=True))

    def test_revoke_failure_never_500s(self):
        with mock.patch.object(app_module.connections_store, 'revoke_client', side_effect=RuntimeError("x")):
            resp = self.client.post('/connect-ai/revoke', data={'client_id': 'c1'})
        self.assertEqual(resp.status_code, 302)


if __name__ == "__main__":
    unittest.main()
