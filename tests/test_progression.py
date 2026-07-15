import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import progression as p  # noqa: E402


def rep_set(done, target, weight, watts=None, amps=None):
    det = {}
    if watts is not None:
        det["leftWatts"] = watts
    if amps is not None:
        det["leftAmplitudes"] = amps
    det["weights"] = [weight]
    return {"finishedCount": done, "targetCount": target, "trainingInfoDetail": det, "time": 0}


def rep_ex(name, region, sets, **scores):
    return {
        "actionLibraryName": name, "trainingPartId2": region, "completionMethod": 1,
        "finishedReps": sets, **scores,
    }


class TestKind(unittest.TestCase):
    def test_reps(self):
        self.assertEqual(p.exercise_kind({"completionMethod": 1}), "reps")

    def test_timed(self):
        self.assertEqual(p.exercise_kind({"completionMethod": 0}), "timed")
        self.assertEqual(p.exercise_kind({"completionMethod": 2}), "timed")

    def test_vita_is_level(self):
        self.assertEqual(p.exercise_kind({"completionMethod": 5, "dataStatType": 6}), "level")


class TestPowerTrend(unittest.TestCase):
    def test_uses_peak_not_first_rep(self):
        # rep 1 is a low ramp-in; measuring from it would hide a real drop.
        s = p._set_facts("reps", rep_set(6, 6, 35, watts=[30, 60, 58, 56, 40, 38]))
        # peak 60 -> last2 mean 39 -> ~35% down
        self.assertAlmostEqual(s["power_trend_pct"], 35.0, delta=1.0)

    def test_flat_power_is_small_trend(self):
        s = p._set_facts("reps", rep_set(6, 6, 35, watts=[50, 52, 51, 52, 50, 51]))
        self.assertLess(abs(s["power_trend_pct"]), 6)

    def test_ragged_channels_do_not_crash(self):
        det = {"leftWatts": [30, 60, 58, 56], "rightWatts": [30, 60, 58], "weights": [35]}
        s = p._set_facts("reps", {"finishedCount": 4, "targetCount": 4, "trainingInfoDetail": det})
        self.assertIsNotNone(s["power_trend_pct"])


class TestExercise(unittest.TestCase):
    def test_all_complete(self):
        ex = rep_ex("Rows", 13, [rep_set(12, 12, 35), rep_set(10, 10, 40)])
        a = p.analyze_exercise(ex)
        self.assertTrue(a["all_complete"])
        self.assertFalse(a["any_missed"])
        self.assertEqual(a["top_load"], 40)
        self.assertEqual(a["region"], "Back")

    def test_missed_reps_flagged(self):
        a = p.analyze_exercise(rep_ex("Rows", 13, [rep_set(8, 12, 35)]))
        self.assertFalse(a["all_complete"])
        self.assertTrue(a["any_missed"])

    def test_skipped_set_excluded_from_completion(self):
        a = p.analyze_exercise(rep_ex("Rows", 13, [rep_set(12, 12, 35), rep_set(0, 12, 40)]))
        self.assertEqual(a["sets_done"], 1)
        self.assertEqual(a["sets_total"], 2)
        self.assertTrue(a["all_complete"])   # the one worked set was complete

    def test_rom_shrink_is_negative(self):
        ex = rep_ex("Rows", 13, [
            rep_set(12, 12, 35, amps=[0.50, 0.50]),
            rep_set(12, 12, 35, amps=[0.40, 0.40]),
        ])
        self.assertLess(p.analyze_exercise(ex)["rom_change_pct"], 0)

    def test_carries_device_scores(self):
        a = p.analyze_exercise(rep_ex("Rows", 13, [rep_set(12, 12, 35)],
                                       forceControlScore=5, amplitudeStableScore=4))
        self.assertEqual(a["scores"]["force_control"], 5)
        self.assertEqual(a["scores"]["amplitude_stable"], 4)


class TestVita(unittest.TestCase):
    def test_level_exercise_has_no_load_and_no_verdict(self):
        ex = {"actionLibraryName": "Vita Pull", "trainingPartId2": 17,
              "completionMethod": 5, "dataStatType": 6,
              "finishedReps": [{"finishedCount": 24, "targetCount": 30, "time": 30,
                                "trainingInfoDetail": {"weights": [0]}}]}
        a = p.analyze_exercise(ex)
        self.assertEqual(a["kind"], "level")
        self.assertIsNone(a["top_load"])
        self.assertFalse(a["all_complete"])   # 24/30, missed the window target


class TestSessionAndGroups(unittest.TestCase):
    def test_rollup_by_region(self):
        detail = [
            rep_ex("Lat Pulldown", 13, [rep_set(12, 12, 35)]),
            rep_ex("Face Pull", 13, [rep_set(8, 12, 20)]),          # missed
            rep_ex("Leg Curl", 15, [rep_set(10, 10, 15)]),
        ]
        s = p.analyze_session(detail)
        back = next(g for g in s["groups"] if g["region"] == "Back")
        self.assertEqual(sorted(back["exercises"]), ["Face Pull", "Lat Pulldown"])
        self.assertEqual(back["complete"], 1)
        self.assertEqual(back["missed"], 1)
        self.assertEqual(len(s["groups"]), 2)   # Back + Legs

    def test_no_verdict_fields_emitted(self):
        # Guard the core decision: this module reports facts, never add/reduce.
        s = p.analyze_session([rep_ex("Rows", 13, [rep_set(12, 12, 35)])])
        blob = repr(s).lower()
        for banned in ("add weight", "reduce", "verdict", "too light", "grinding"):
            self.assertNotIn(banned, blob)


class TestCompare(unittest.TestCase):
    def test_first_time(self):
        cur = p.analyze_exercise(rep_ex("Rows", 13, [rep_set(12, 12, 35)]))
        self.assertEqual(p.compare_exercise(cur, None)["status"], "first_time")

    def test_load_delta(self):
        cur = p.analyze_exercise(rep_ex("Rows", 13, [rep_set(12, 12, 40)]))
        prev = p.analyze_exercise(rep_ex("Rows", 13, [rep_set(12, 12, 35)]))
        self.assertEqual(p.compare_exercise(cur, prev)["load_delta"], 5)


if __name__ == "__main__":
    unittest.main()
