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
                {"done": 12, "target": 12, "load": 15.5, "power_trend_pct": 41.0, "skipped": False,
                 "seconds": 40, "rest": 90, "speed_trend_pct": 18.0,
                 "left_reps": 12, "right_reps": 12},
                {"done": 10, "target": 10, "load": 12, "power_trend_pct": 8.0, "skipped": False,
                 "seconds": 30, "rest": 60, "speed_trend_pct": 5.0,
                 "left_reps": 10, "right_reps": 7},
            ],
            "scores": {"force_control": 4, "amplitude_stable": 3, "bilateral_balance": 5, "rating": 4},
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

    def test_an_unrated_exercise_says_nothing_about_feel(self):
        """Silence, not "not rated".

        Most sessions are never rated. Printing "Felt: not rated" on every line put the
        absence in front of the model once per exercise, and it answered by asking for
        ratings instead of reading the data it did have. An unrated exercise is the normal
        case, so it reads as normal.
        """
        vita = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertNotIn("Felt", vita)
        exercise_lines = [l for l in self.p.splitlines() if l.startswith("- ")]
        self.assertFalse([l for l in exercise_lines if "not rated" in l],
                         "the absence must not be repeated on every exercise line")

    def test_objective_effort_signals_reach_the_model(self):
        """Without a felt rating these are all the coach has, so they must be in the brief."""
        line = [l for l in self.p.splitlines() if l.startswith("- Standing Leg Curl")][0]
        self.assertIn("in 40s", line, "set duration — the same reps taking longer is fatigue")
        self.assertIn("rest 90s", line, "rest actually taken, not what was prescribed")
        self.assertIn("speed", line, "velocity loss is the best objective proximity-to-failure proxy")
        self.assertIn("left/right balance 5/5", line, "the machine's own unevenness read")

    def test_uneven_sides_are_named_only_when_they_diverge(self):
        line = [l for l in self.p.splitlines() if l.startswith("- Standing Leg Curl")][0]
        self.assertIn("uneven sides (10L/7R)", line)
        vita = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertNotIn("uneven", vita, "equal or absent counts are noise")

    def test_vita_spoken_in_levels_not_weight(self):
        vita_line = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertIn("level-based", vita_line)
        self.assertNotIn("@", vita_line)

    def test_power_trend_labelled_as_unreliable(self):
        self.assertIn("NOT direct measures of effort", self.p)


class TestSystemPromptGuardrails(unittest.TestCase):
    def test_encodes_the_core_lesson(self):
        s = coach.SYSTEM_PROMPT.lower()
        self.assertIn("outranks every sensor metric", s)
        self.assertIn("never invent", s)
        self.assertIn("cannot measure effort", s)

    def test_tells_the_coach_to_assess_without_a_felt_rating(self):
        """The prompt used to make a rating a precondition for any recommendation.

        "Recommend adding weight ONLY where ... the athlete felt it easy/too-easy AND ..."
        is an AND that can never be satisfied when nothing is rated, so the coach was
        structurally barred from saying anything useful about a normal session.
        """
        s = coach.SYSTEM_PROMPT.lower()
        self.assertIn("most sessions are not rated", s)
        self.assertIn("never refuse to assess", s)
        for signal in ("rep completion", "set duration", "rest taken", "speed trend",
                       "range of motion", "form scores"):
            self.assertIn(signal, s, f"{signal} is a signal that works without a rating")


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

    def test_keeps_novel_chat_names(self):
        # Denylist-only: a newly-released chat model must not be hidden just because its
        # name doesn't match a known prefix. This is the "always show the latest" guarantee.
        for good in ("gpt-6", "o5", "o5-pro", "gpt-5.5-flagship", "claude-style-new-reasoner"):
            self.assertTrue(coach._looks_like_chat_model(good), good)

    def test_drops_legacy_and_specialized(self):
        for bad in ("davinci-002", "babbage-002", "gpt-4o-audio-preview",
                    "gpt-4o-realtime-preview", "gpt-image-1", "gpt-4o-search-preview"):
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


class TestAssessmentPrompt(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            {"date": "2026-07-18", "title": "Workout A", "snapshot": SNAPSHOT, "notes": NOTES},
            {"date": "2026-07-20", "title": "Workout B", "snapshot": SNAPSHOT, "notes": {}},
        ]
        self.p = coach.build_assessment_prompt(self.sessions, 7)

    def test_lists_each_session_date_and_title(self):
        self.assertIn("2026-07-18", self.p)
        self.assertIn("Workout A", self.p)
        self.assertIn("2026-07-20", self.p)
        self.assertIn("Workout B", self.p)

    def test_window_size_stated(self):
        self.assertIn("7 day", self.p)

    def test_vita_spoken_in_levels_not_weight(self):
        vita_lines = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")]
        self.assertTrue(vita_lines)
        for l in vita_lines:
            self.assertIn("level-based", l)
            self.assertNotIn("@", l)

    def test_carries_felt_ratings(self):
        self.assertIn("Felt: easy", self.p)

    def test_asks_the_assessment_questions(self):
        low = self.p.lower()
        for kw in ("strong", "weak", "improving", "regress", "increase weight or resistance"):
            self.assertIn(kw, low)

    def test_empty_sessions_does_not_raise(self):
        out = coach.build_assessment_prompt([], 1)
        self.assertIn("1 day", out)


class TestAssessmentSystemPrompt(unittest.TestCase):
    def test_encodes_guardrails(self):
        s = coach.ASSESSMENT_SYSTEM_PROMPT.lower()
        self.assertIn("outranks every sensor metric", s)
        self.assertIn("most sessions are not rated", s)
        self.assertIn("never invent", s)

    def test_organised_by_finding_not_by_body_part(self):
        """The assessment reads "where you are strong" first, muscle groups nested under it.

        Grouping by muscle region put a separate strong/improving/plateauing breakdown under
        every body part, which buried the actual findings.
        """
        s = coach.ASSESSMENT_SYSTEM_PROMPT.lower()
        self.assertIn("organise by finding, not by body part", s)
        for section in ("### where you are strong", "### where you are improving",
                        "### where you are plateauing or regressing",
                        "### where you are weak or lagging", "### what to change next"):
            self.assertIn(section, s)
        self.assertIn("never put an exercise at the same level as its muscle group", s)


class TestUnitLabelling(unittest.TestCase):
    # The API returns loads already in the account's display unit; the facts must SAY which
    # unit, or the model guesses (it printed "kg" for lbs data). See the units memory.
    def test_exercise_line_labels_load_with_unit(self):
        ex = SNAPSHOT["exercises"][0]  # Standing Leg Curl, weighted
        line = coach._exercise_line(ex, NOTES, unit="lbs")
        self.assertIn("15.5 lbs", line)

    def test_exercise_line_no_unit_by_default_unchanged(self):
        ex = SNAPSHOT["exercises"][0]
        line = coach._exercise_line(ex, NOTES)
        self.assertIn("@ 15.5", line)
        self.assertNotIn("lbs", line)
        self.assertNotIn("kg", line)

    def test_vita_line_never_gets_a_weight_unit(self):
        vita = SNAPSHOT["exercises"][1]
        line = coach._exercise_line(vita, NOTES, unit="lbs")
        self.assertNotIn("lbs", line)
        self.assertIn("level-based", line)

    def test_build_prompt_states_the_unit(self):
        p = coach.build_prompt(SNAPSHOT, NOTES, unit="lbs")
        self.assertIn("lbs", p)

    def test_assessment_prompt_states_the_unit(self):
        sessions = [{"date": "2026-07-20", "title": "A", "snapshot": SNAPSHOT, "notes": NOTES}]
        p = coach.build_assessment_prompt(sessions, 7, unit="lbs")
        self.assertIn("lbs", p)

    def test_system_prompts_forbid_conversion(self):
        self.assertIn("convert", coach.SYSTEM_PROMPT.lower())
        self.assertIn("convert", coach.ASSESSMENT_SYSTEM_PROMPT.lower())


class TestWorkoutGeneratorConfig(unittest.TestCase):
    def _cfg(self):
        return {"provider": "ollama",
                "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS},
                "known_models": {}, "last_model_check": None,
                "workout_generator": {"provider": "anthropic", "model": "claude-x"}}

    def test_reads_workout_provider_and_model(self):
        cfg = self._cfg()
        self.assertEqual(coach.workout_provider(cfg), "anthropic")
        self.assertEqual(coach.workout_model(cfg), "claude-x")

    def test_defaults_when_missing(self):
        cfg = {"provider": "ollama",
               "providers": {p: coach._blank_provider(p) for p in coach.PROVIDERS}}
        self.assertIn(coach.workout_provider(cfg), coach.PROVIDERS)  # a valid provider
        self.assertEqual(coach.workout_model(cfg), "")

    def test_chat_with_refuses_without_model(self):
        cfg = self._cfg()
        ok, msg = coach.chat_with("anthropic", "", "hi", cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("model", msg.lower())

    def test_chat_with_refuses_without_key(self):
        cfg = self._cfg()   # anthropic has a blank api_key
        ok, msg = coach.chat_with("anthropic", "claude-x", "hi", cfg, timeout=2)
        self.assertFalse(ok)
        self.assertIn("key", msg.lower())


if __name__ == "__main__":
    unittest.main()


class TestBalanceScoreIsNotFabricated(unittest.TestCase):
    """A zero balance score means "not applicable", and must not be reported as a finding.

    Verified against live data: bilateralBalanceScore is 0 only on unilateral movements
    (isLeftRight=1), which train one side at a time and so have no left-vs-right balance to
    measure. Bilateral movements score 2-5. Passing the 0 through made the coach report a
    severe imbalance that did not exist.
    """

    def _line(self, balance):
        ex = {"name": "Standing Cable External Rotation", "region": "Shoulders", "kind": "reps",
              "all_complete": True, "rom_change_pct": None,
              "sets": [{"done": 15, "target": 15, "load": 8, "skipped": False,
                        "seconds": 30, "rest": 45, "left_reps": 15, "right_reps": 0}],
              "scores": {"force_control": 5, "amplitude_stable": 4,
                         "bilateral_balance": balance, "rating": None}}
        return coach._exercise_line(ex, {}, {}, "lbs")

    def test_zero_is_omitted_not_reported_as_a_failing_score(self):
        self.assertNotIn("balance", self._line(0))

    def test_none_is_omitted(self):
        self.assertNotIn("balance", self._line(None))

    def test_a_real_score_is_reported(self):
        self.assertIn("left/right balance 3/5", self._line(3))

    def test_a_one_sided_set_is_not_called_uneven(self):
        """A unilateral set is 15 left and 0 right by design, not an imbalance."""
        self.assertNotIn("uneven", self._line(0))


class TestNonDeviceAndOpeningSetHandling(unittest.TestCase):
    """Two ways the coach used to invent findings out of artefacts."""

    def _ex(self, **over):
        ex = {"name": "Bodyweight Sumo Squat", "region": "Legs", "kind": "timed",
              "all_complete": True, "rom_change_pct": None, "uses_device": True,
              "recorded": True, "sets": [],
              "scores": {"force_control": None, "amplitude_stable": None,
                         "bilateral_balance": None, "rating": None}}
        ex.update(over)
        return ex

    def test_a_bodyweight_movement_is_not_accused_of_missing_reps(self):
        """361 of the 1040 library exercises use no cables (isUseDevice=0).

        The machine records nothing for them — no reps, no telemetry, no form scores — and
        the line used to read "MISSED some reps. Sets . force None/5", which is three
        falsehoods at once, after which the coach made load recommendations about an
        exercise it had no data for.
        """
        line = coach._exercise_line(self._ex(uses_device=False), {}, {}, "lbs")
        self.assertNotIn("MISSED", line)
        self.assertNotIn("None/5", line)
        self.assertIn("no reps, load or form data", line)
        self.assertIn("do not make a load recommendation", line)

    def test_a_planned_but_unperformed_exercise_reads_as_such(self):
        """Different from a bodyweight movement: the cables could have measured it."""
        line = coach._exercise_line(self._ex(name="Standing Leg Curl", kind="reps",
                                             recorded=False), {}, {}, "lbs")
        self.assertIn("planned and not performed", line)
        self.assertNotIn("MISSED", line)

    def test_an_opening_set_imbalance_is_discarded_as_a_mis_start(self):
        """A big left/right split on set 1 is almost always a stray rep counted while
        getting into position, not an asymmetry. Believing it had the coach reporting an
        imbalance that never happened."""
        sets = [{"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 12, "right_reps": 6},
                {"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 12, "right_reps": 12}]
        line = coach._exercise_line(self._ex(name="Row", kind="reps", sets=sets), {}, {}, "lbs")
        self.assertNotIn("uneven", line)

    def test_an_imbalance_in_a_working_set_is_still_reported(self):
        sets = [{"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 12, "right_reps": 12},
                {"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 12, "right_reps": 8}]
        line = coach._exercise_line(self._ex(name="Row", kind="reps", sets=sets), {}, {}, "lbs")
        self.assertIn("uneven sides (12L/8R)", line)

    def test_alternating_unilateral_sets_are_not_called_an_imbalance(self):
        """1L/11R then 11L/1R is one side per set, by design — not an asymmetry.

        Seen live: the coach reported "severe side-to-side execution discrepancies" for a
        cable kickback that was simply alternating sides. A real imbalance needs both sides
        worked within the SAME set.
        """
        sets = [{"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 12, "right_reps": 12},
                {"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 1, "right_reps": 11},
                {"done": 12, "target": 12, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 11, "right_reps": 1}]
        line = coach._exercise_line(self._ex(name="Kickback", kind="reps", sets=sets), {}, {}, "lbs")
        self.assertNotIn("uneven", line)

    def test_a_genuine_within_set_imbalance_still_reports(self):
        """Both sides doing real work, but unequally — that is the finding worth keeping."""
        sets = [{"done": 20, "target": 20, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 10, "right_reps": 10},
                {"done": 20, "target": 20, "load": 20, "skipped": False, "seconds": 40,
                 "rest": 60, "left_reps": 12, "right_reps": 8}]
        line = coach._exercise_line(self._ex(name="Row", kind="reps", sets=sets), {}, {}, "lbs")
        self.assertIn("uneven sides (12L/8R)", line)
