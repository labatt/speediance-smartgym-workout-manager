import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


class WorkoutLastRoute(unittest.TestCase):
    def setUp(self):
        # Satisfy the auth gate and isolate the on-disk file.
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._orig = app.WORKOUT_GEN_LAST_FILE
        fd, self._tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self._tmp)                 # start with no file → load returns None
        app.WORKOUT_GEN_LAST_FILE = self._tmp
        self.c = app.app.test_client()

    def tearDown(self):
        app.WORKOUT_GEN_LAST_FILE = self._orig
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_last_null_when_none(self):
        self.assertIsNone(self.c.get("/api/workout/last").get_json()["last"])

    def test_save_then_get_roundtrips(self):
        app.save_workout_gen_last({
            "request": "back and biceps day", "recent_days": 30,
            "provider": "gemini", "model": "m", "at": "2026-08-06T10:00:00",
            "system_prompt": "SYSTEM TEXT", "user_prompt": "USER TEXT",
        })
        d = self.c.get("/api/workout/last").get_json()["last"]
        self.assertEqual(d["request"], "back and biceps day")
        self.assertEqual(d["recent_days"], 30)
        self.assertEqual(d["system_prompt"], "SYSTEM TEXT")
        self.assertEqual(d["user_prompt"], "USER TEXT")

    def test_last_requires_auth(self):
        app.client.credentials.pop("token", None)
        self.assertEqual(self.c.get("/api/workout/last").status_code, 401)


if __name__ == "__main__":
    unittest.main()
