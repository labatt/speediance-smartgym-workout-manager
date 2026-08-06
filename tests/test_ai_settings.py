import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
import coach  # noqa: E402


class AISettingsRoutes(unittest.TestCase):
    def setUp(self):
        # Isolate the on-disk config and satisfy the auth gate without the real token.
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._cfgfile = coach._CONFIG_FILE
        fd, self._tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        coach._CONFIG_FILE = self._tmp
        coach.save_config(coach.load_config())   # seed a clean default config on disk
        self._list_models = coach.list_models
        self.c = app.app.test_client()

    def tearDown(self):
        coach.list_models = self._list_models
        coach._CONFIG_FILE = self._cfgfile
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_workout_config_accepts_all_five_providers(self):
        for p in ("anthropic", "openai", "gemini", "ollama", "grok"):
            r = self.c.post("/api/workout/config", json={"provider": p, "model": "m1"})
            self.assertEqual(r.status_code, 200, p)
            self.assertTrue(r.get_json().get("saved"), p)

    def test_workout_config_rejects_unknown_provider(self):
        r = self.c.post("/api/workout/config", json={"provider": "bogus", "model": "m"})
        self.assertEqual(r.status_code, 400)

    def test_workout_config_get_lists_all_five(self):
        d = self.c.get("/api/workout/config").get_json()
        self.assertEqual(set(d["providers"]), set(coach.PROVIDERS))

    def test_models_route_caches_known_models(self):
        coach.list_models = lambda provider, pc: (True, ["m-a", "m-b"])
        r = self.c.get("/api/coach/models?provider=anthropic").get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["models"], ["m-a", "m-b"])
        on_disk = json.load(open(self._tmp))
        self.assertEqual(on_disk["known_models"]["anthropic"], ["m-a", "m-b"])

    def test_coach_config_get_exposes_known_models(self):
        coach.list_models = lambda provider, pc: (True, ["x1"])
        self.c.get("/api/coach/models?provider=openai")           # populate cache
        d = self.c.get("/api/coach/config").get_json()
        self.assertIn("known_models", d)
        self.assertEqual(d["known_models"].get("openai"), ["x1"])


if __name__ == "__main__":
    unittest.main()
