import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
import avoided_store  # noqa: E402


class TestAvoidedRoutes(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = os.path.join(self._tmpdir.name, "speediance-mcp.db")
        self._patch = mock.patch.object(avoided_store, "db_path", return_value=self.path)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        # No Speediance token needed for these routes at all.
        self._tok = app.client.credentials.get("token")
        app.client.credentials.pop("token", None)
        self.addCleanup(lambda: app.client.credentials.update(
            {"token": self._tok}) if self._tok is not None else None)
        self.c = app.app.test_client()

    def test_get_avoided_empty(self):
        r = self.c.get("/api/avoided")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"avoided": []})

    def test_post_then_get_round_trips(self):
        r = self.c.post("/api/avoided", json={"group_id": 1001, "name": "Bench Press", "reason": "shoulder"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True})

        r = self.c.get("/api/avoided")
        data = r.get_json()
        self.assertEqual(len(data["avoided"]), 1)
        self.assertEqual(data["avoided"][0]["group_id"], 1001)
        self.assertEqual(data["avoided"][0]["name"], "Bench Press")
        self.assertEqual(data["avoided"][0]["reason"], "shoulder")

    def test_post_missing_group_id_is_400(self):
        r = self.c.post("/api/avoided", json={"name": "Bench Press"})
        self.assertEqual(r.status_code, 400)

    def test_post_non_numeric_group_id_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": "abc", "name": "Bench Press"})
        self.assertEqual(r.status_code, 400)

    def test_post_reason_too_long_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 5, "name": "Row", "reason": "x" * 201})
        self.assertEqual(r.status_code, 400)

    def test_post_no_body_is_400(self):
        r = self.c.post("/api/avoided")
        self.assertEqual(r.status_code, 400)

    def test_delete_existing_returns_removed_true(self):
        self.c.post("/api/avoided", json={"group_id": 1001, "name": "Bench Press"})
        r = self.c.delete("/api/avoided/1001")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True, "removed": True})
        self.assertEqual(self.c.get("/api/avoided").get_json(), {"avoided": []})

    def test_delete_missing_returns_removed_false(self):
        r = self.c.delete("/api/avoided/9999")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True, "removed": False})

    def test_no_token_required(self):
        # Explicitly confirm these routes work with no Speediance session at all.
        self.assertNotIn("token", app.client.credentials)
        r = self.c.get("/api/avoided")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
