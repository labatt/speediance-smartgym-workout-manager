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
        self.assertIn("Felt: easy", self.p)          # per-exercise
        self.assertIn("just right", self.p)           # overall

    def test_unrated_exercise_marked_not_rated(self):
        self.assertIn("Felt: not rated", self.p)      # Vita has no rating

    def test_vita_spoken_in_levels_not_weight(self):
        # The Vita line must not carry a weight-style '@ number'.
        vita_line = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertIn("level-based", vita_line)
        self.assertNotIn("@", vita_line)

    def test_power_trend_labelled_as_unreliable(self):
        self.assertIn("NOT a measure of effort", self.p)

    def test_groups_by_region(self):
        self.assertIn("== Legs ==", self.p)
        self.assertIn("== Core ==", self.p)

    def test_only_given_numbers_appear(self):
        # A guard against the prompt implying figures we did not provide.
        self.assertIn("12/12 @ 15.5", self.p)
        self.assertIn("14/20 in 30s", self.p)


class TestSystemPromptGuardrails(unittest.TestCase):
    def test_encodes_the_core_lesson(self):
        s = coach.SYSTEM_PROMPT.lower()
        self.assertIn("felt rating outranks", s)
        self.assertIn("never invent", s)
        self.assertIn("cannot measure effort", s)


class TestOllamaOffline(unittest.TestCase):
    def test_unreachable_returns_friendly_reason(self):
        cfg = {"endpoint": "http://127.0.0.1:59999", "model": "x", "api_key": ""}
        ok, msg = coach.ask_ollama("hi", cfg=cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("Couldn't reach", msg)

    def test_cloud_without_key_is_refused_before_any_call(self):
        cfg = {"endpoint": "https://ollama.com", "model": "gpt-oss:120b", "api_key": ""}
        ok, msg = coach.ask_ollama("hi", cfg=cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("API key", msg)

    def test_status_when_down(self):
        st = coach.ollama_status(cfg={"endpoint": "http://127.0.0.1:59999", "model": "x", "api_key": ""})
        self.assertFalse(st["up"])
        self.assertEqual(st["models"], [])


if __name__ == "__main__":
    unittest.main()
