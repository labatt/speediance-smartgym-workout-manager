import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


class WorkoutLastHistory(unittest.TestCase):
    def setUp(self):
        # Satisfy the auth gate and isolate the on-disk file.
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._orig = app.WORKOUT_GEN_LAST_FILE
        fd, self._tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self._tmp)                 # start with no file → empty history
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

    def test_empty_when_none(self):
        d = self.c.get("/api/workout/last").get_json()
        self.assertIsNone(d["last"])
        self.assertEqual(d["history"], [])

    def test_save_prepends_newest_first(self):
        app.save_workout_gen_last({"request": "one", "at": "1"})
        app.save_workout_gen_last({"request": "two", "at": "2"})
        d = self.c.get("/api/workout/last").get_json()
        self.assertEqual(d["last"]["request"], "two")                       # newest is 'last'
        self.assertEqual([e["request"] for e in d["history"]], ["two", "one"])

    def test_caps_at_20_dropping_oldest(self):
        for i in range(25):
            app.save_workout_gen_last({"request": f"r{i}", "at": str(i)})
        h = app.load_workout_gen_history()
        self.assertEqual(len(h), 20)
        self.assertEqual(h[0]["request"], "r24")     # newest kept
        self.assertEqual(h[-1]["request"], "r5")     # r0..r4 dropped

    def test_legacy_single_dict_is_wrapped(self):
        with open(self._tmp, "w") as f:
            json.dump({"request": "legacy", "at": "0"}, f)
        d = self.c.get("/api/workout/last").get_json()
        self.assertEqual(d["last"]["request"], "legacy")
        self.assertEqual(len(d["history"]), 1)

    def test_requires_auth(self):
        app.client.credentials.pop("token", None)
        self.assertEqual(self.c.get("/api/workout/last").status_code, 401)


if __name__ == "__main__":
    unittest.main()
