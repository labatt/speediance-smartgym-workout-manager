import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


class WorkoutListRoute(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._orig = app.client.get_user_workouts
        self.c = app.app.test_client()

    def tearDown(self):
        app.client.get_user_workouts = self._orig
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_list_returns_name_code_entries(self):
        app.client.get_user_workouts = lambda: [
            {"name": "Back Day A", "code": "abc", "actionNum": 8, "durationMinute": 42},
            {"name": "No Code", "actionNum": 3},   # dropped — no code
        ]
        d = self.c.get("/api/workout/list").get_json()
        self.assertEqual(len(d["workouts"]), 1)
        self.assertEqual(d["workouts"][0]["code"], "abc")
        self.assertEqual(d["workouts"][0]["name"], "Back Day A")

    def test_list_requires_auth(self):
        app.client.credentials.pop("token", None)
        self.assertEqual(self.c.get("/api/workout/list").status_code, 401)


if __name__ == "__main__":
    unittest.main()
