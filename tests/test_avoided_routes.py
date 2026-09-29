import os
import sqlite3
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

    # --- I-5: stricter validation ---

    def test_post_body_not_a_dict_is_400(self):
        r = self.c.post("/api/avoided", json=[1, 2, 3])
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.get_json())

    def test_post_body_a_bare_string_is_400(self):
        r = self.c.post("/api/avoided", json="1001")
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_bool_true_is_400(self):
        # bool is a subclass of int in Python — must be explicitly rejected, not
        # silently coerced to group_id 1.
        r = self.c.post("/api/avoided", json={"group_id": True, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_bool_false_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": False, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_float_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 1001.5, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_whole_number_float_is_400(self):
        # Even a whole-number float (1001.0) must be rejected — the type itself is wrong,
        # not just non-integral values.
        r = self.c.post("/api/avoided", json={"group_id": 1001.0, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_numeric_string_is_400(self):
        # A numeric string is not an int — strict typing, not "parses as a number".
        r = self.c.post("/api/avoided", json={"group_id": "1001", "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_zero_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 0, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_negative_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": -5, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_too_large_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 2**63, "name": "Row"})
        self.assertEqual(r.status_code, 400)

    def test_post_group_id_max_valid_is_ok(self):
        r = self.c.post("/api/avoided", json={"group_id": 2**63 - 1, "name": "Row"})
        self.assertEqual(r.status_code, 200)

    def test_post_group_id_min_valid_is_ok(self):
        r = self.c.post("/api/avoided", json={"group_id": 1, "name": "Row"})
        self.assertEqual(r.status_code, 200)

    def test_post_name_not_a_string_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 5, "name": 12345})
        self.assertEqual(r.status_code, 400)

    def test_post_name_too_long_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 5, "name": "x" * 201})
        self.assertEqual(r.status_code, 400)

    def test_post_name_at_max_length_ok(self):
        r = self.c.post("/api/avoided", json={"group_id": 5, "name": "x" * 200})
        self.assertEqual(r.status_code, 200)

    def test_post_reason_not_a_string_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 5, "name": "Row", "reason": 123})
        self.assertEqual(r.status_code, 400)

    def test_post_reason_a_list_is_400(self):
        r = self.c.post("/api/avoided", json={"group_id": 5, "name": "Row", "reason": ["x"]})
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

    # --- fix round 2, item 3: sqlite errors on write routes -> 503, not 500 ---

    def test_post_sqlite_error_returns_503(self):
        with mock.patch.object(avoided_store, "set_avoided",
                               side_effect=sqlite3.OperationalError("database is locked")):
            r = self.c.post("/api/avoided", json={"group_id": 1001, "name": "Bench Press"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json(),
                         {"error": "The avoided list is busy or unavailable — try again."})

    def test_post_value_error_still_400_not_503(self):
        # ValueError (e.g. reason too long) is a validation failure, not a store outage.
        with mock.patch.object(avoided_store, "set_avoided", side_effect=ValueError("reason too long")):
            r = self.c.post("/api/avoided", json={"group_id": 1001, "name": "Bench Press"})
        self.assertEqual(r.status_code, 400)

    def test_delete_sqlite_error_returns_503(self):
        with mock.patch.object(avoided_store, "clear_avoided",
                               side_effect=sqlite3.OperationalError("database is locked")):
            r = self.c.delete("/api/avoided/1001")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json(),
                         {"error": "The avoided list is busy or unavailable — try again."})

    def test_avoided_ids_safe_wrapper_removed_as_dead_code(self):
        # Fix round 2, item 4: _avoided_ids_safe() was defined but never called anywhere
        # (generate/refine need full rows — name/reason — not just ids, so it had no
        # natural caller). Removed rather than wired in for the sake of it; this guards
        # against silently reintroducing unused dead code.
        self.assertFalse(hasattr(app, "_avoided_ids_safe"))
        # The underlying store function it would have wrapped is still directly tested
        # in tests/test_avoided_store.py and still used by adaptive_training callers.
        self.assertTrue(hasattr(avoided_store, "avoided_ids"))


if __name__ == "__main__":
    unittest.main()
