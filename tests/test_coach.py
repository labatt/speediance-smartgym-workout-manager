import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach  # noqa: E402


SNAPSHOT = {
    "exercises": [
        {
            "name": "Standing Leg Curl", "region": "Legs", "kind": "reps",
            "all_complete": True, "top_load": 15.5, "rom_change_pct": 2.0,
            "sets": [
                {"done": 12, "target": 12, "load": 15.5, "power_trend_pct": 41.0, "skipped": False},
                {"done": 10, "target": 10, "load": 12, "power_trend_pct": 8.0, "skipped": False},
            ],
            "scores": {"force_control": 4, "amplitude_stable": 3, "bilateral_balance": None, "rating": 4},
        },
        {
            "name": "Vita Pull", "region": "Core", "kind": "level",
            "all_complete": False, "top_load": None, "rom_change_pct": None,
            "sets": [{"done": 14, "target": 20, "seconds": 30, "skipped": False}],
            "scores": {"force_control": None, "amplitude_stable": None, "bilateral_balance": None, "rating": None},
        },
    ],
    "groups": [],
}
NOTES = {"overall": "right", "exercises": {"Standing Leg Curl": "easy"}}


class TestBuildPrompt(unittest.TestCase):
    def setUp(self):
        self.p = coach.build_prompt(SNAPSHOT, NOTES)

    def test_includes_felt_ratings(self):
        self.assertIn("Felt: easy", self.p)
        self.assertIn("just right", self.p)

    def test_unrated_exercise_marked_not_rated(self):
        self.assertIn("Felt: not rated", self.p)

    def test_vita_spoken_in_levels_not_weight(self):
        vita_line = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertIn("level-based", vita_line)
        self.assertNotIn("@", vita_line)

    def test_power_trend_labelled_as_unreliable(self):
        self.assertIn("NOT a measure of effort", self.p)


class TestSystemPromptGuardrails(unittest.TestCase):
    def test_encodes_the_core_lesson(self):
        s = coach.SYSTEM_PROMPT.lower()
        self.assertIn("felt rating outranks", s)
        self.assertIn("never invent", s)
        self.assertIn("cannot measure effort", s)


class TestEndpointAllowlist(unittest.TestCase):
    def test_ollama_cloud_and_local_allowed(self):
        self.assertTrue(coach.endpoint_allowed("ollama", "https://ollama.com"))
        self.assertTrue(coach.endpoint_allowed("ollama", "http://127.0.0.1:11434"))

    def test_ollama_blocks_loopback_service_ports_and_metadata(self):
        for bad in ("http://127.0.0.1:5432", "http://127.0.0.1:6379",
                    "http://169.254.169.254/", "http://10.0.0.5:11434", "http://ollama.com"):
            self.assertFalse(coach.endpoint_allowed("ollama", bad), bad)

    def test_fixed_providers_pinned_to_their_host(self):
        self.assertTrue(coach.endpoint_allowed("anthropic", "https://api.anthropic.com"))
        self.assertTrue(coach.endpoint_allowed("openai", "https://api.openai.com"))
        self.assertTrue(coach.endpoint_allowed("gemini", "https://generativelanguage.googleapis.com"))
        self.assertTrue(coach.endpoint_allowed("grok", "https://api.x.ai"))
        # A different host for a fixed provider is rejected — no SSRF via a swapped endpoint.
        self.assertFalse(coach.endpoint_allowed("anthropic", "https://evil.test"))
        self.assertFalse(coach.endpoint_allowed("openai", "http://127.0.0.1:6379"))


class TestModelFilter(unittest.TestCase):
    def test_keeps_chat_models_drops_others(self):
        self.assertTrue(coach._looks_like_chat_model("gpt-4o"))
        self.assertTrue(coach._looks_like_chat_model("o3-mini"))
        self.assertTrue(coach._looks_like_chat_model("chatgpt-4o-latest"))
        for bad in ("text-embedding-3-large", "whisper-1", "tts-1", "dall-e-3", "omni-moderation-latest"):
            self.assertFalse(coach._looks_like_chat_model(bad), bad)


class TestProviderDispatchOffline(unittest.TestCase):
    def _cfg(self, provider, **pfields):
        cfg = {"provider": provider, "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS},
               "known_models": {}, "last_model_check": None}
        cfg["providers"][provider].update(pfields)
        return cfg

    def test_missing_model_refused_before_any_call(self):
        cfg = self._cfg("openai", api_key="k", model="")
        ok, msg = coach.chat("hi", cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("model", msg.lower())

    def test_missing_key_refused_for_keyed_provider(self):
        cfg = self._cfg("anthropic", api_key="", model="claude-opus-4-8")
        ok, msg = coach.chat("hi", cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("key", msg.lower())

    def test_list_models_needs_key(self):
        ok, msg = coach.list_models("openai", coach._blank_provider("openai"))
        self.assertFalse(ok)
        self.assertIn("key", msg.lower())

    def test_status_reports_active_provider(self):
        cfg = self._cfg("grok", api_key="k", model="grok-2")
        st = coach.status(cfg)
        self.assertEqual(st["provider"], "grok")
        self.assertTrue(st["ready"])


class TestConfigMigration(unittest.TestCase):
    def test_new_shape_round_trips(self):
        cfg = {"provider": "openai", "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS},
               "known_models": {}, "last_model_check": None}
        cfg["providers"]["openai"]["api_key"] = "secret"
        self.assertEqual(coach.active_provider(cfg), "openai")
        self.assertEqual(coach.provider_cfg(cfg, "openai")["api_key"], "secret")


class TestNewModelCheck(unittest.TestCase):
    def test_throttled_within_interval(self):
        today = datetime.date.today().isoformat()
        cfg = {"provider": "ollama", "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS},
               "known_models": {}, "last_model_check": today}
        new, _ = coach.check_new_models(cfg)   # just checked today -> skip
        self.assertEqual(new, {})


if __name__ == "__main__":
    unittest.main()
