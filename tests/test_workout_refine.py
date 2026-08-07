import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


class WorkoutRefineRoute(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self.c = app.app.test_client()

    def tearDown(self):
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_empty_comment_rejected(self):
        r = self.c.post("/api/workout/refine",
                        json={"current_workout": {"exercises": [{"id": 1}]}, "comment": "  "})
        self.assertEqual(r.status_code, 400)

    def test_empty_current_workout_rejected(self):
        r = self.c.post("/api/workout/refine",
                        json={"current_workout": {"exercises": []}, "comment": "harder"})
        self.assertEqual(r.status_code, 400)

    def test_requires_auth(self):
        app.client.credentials.pop("token", None)
        r = self.c.post("/api/workout/refine", json={"comment": "x"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
