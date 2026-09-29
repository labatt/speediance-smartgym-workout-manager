"""Per-muscle volume, balance ratios, and the route that serves them."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from muscle_balance import (  # noqa: E402
    attribute, exercise_volume, muscle_index, ratios, set_load, untrained,
)
import app as app_module  # noqa: E402


def lib(group_id, part, main, assist=()):
    return {"id": group_id, "trainingPartId2": part,
            "mainMuscleGroupList": [{"muscleGroupName": m} for m in main],
            "auxiliaryMuscleGroupList": [{"muscleGroupName": a} for a in assist]}


LIBRARY = [
    lib(1, 11, ["Pecs"], ["Triceps", "Front Delts"]),
    lib(2, 13, ["Lats"], ["Biceps"]),
    lib(3, 15, ["Quads"], ["Glutes"]),
    lib(4, 18, ["Full Body"]),
]
INDEX = muscle_index(LIBRARY)


def ex(group_id, sets, name="Move"):
    """sets: list of (reps, trainingInfoDetail, leftRight)."""
    return {"actionLibraryGroupId": group_id, "actionLibraryName": name,
            "finishedReps": [{"finishedCount": r, "trainingInfoDetail": d, "leftRight": s}
                             for r, d, s in sets]}


class TestSetLoad(unittest.TestCase):
    def test_both_cables_loaded_sum_because_each_carries_its_own_weight(self):
        # The trap: taking one side's max halves every barbell number.
        self.assertEqual(set_load({"leftWeights": [25.0], "rightWeights": [25.0]}, None), 50.0)

    def test_a_pinned_side_is_that_side_alone(self):
        detail = {"leftWeights": [12.0], "rightWeights": [12.5]}
        self.assertEqual(set_load(detail, 1), 12.0)
        self.assertEqual(set_load(detail, 2), 12.5)

    def test_derived_force_weights_are_only_a_fallback(self):
        # `weights` on a dual-cable move is cable tension, not the resistance setting.
        detail = {"weights": [48.5, 47.0], "leftWeights": [12.0], "rightWeights": [12.5]}
        self.assertEqual(set_load(detail, None), 24.5)
        self.assertEqual(set_load({"weights": [30.0]}, None), 30.0)
        self.assertIsNone(set_load({}, None))

    def test_csv_and_junk_values_are_tolerated(self):
        self.assertEqual(set_load({"weights": "10,x,20"}, None), 20.0)


class TestExerciseVolume(unittest.TestCase):
    def test_reps_times_load_summed_over_sets(self):
        got = exercise_volume(ex(1, [(10, {"weights": [50.0]}, 0), (8, {"weights": [60.0]}, 0)]))
        self.assertEqual(got, 980.0)

    def test_a_set_with_no_reps_or_no_load_adds_nothing(self):
        self.assertEqual(exercise_volume(ex(1, [(0, {"weights": [50.0]}, 0)])), 0.0)
        self.assertEqual(exercise_volume(ex(1, [(10, {}, 0)])), 0.0)


class TestAttribute(unittest.TestCase):
    def test_main_takes_full_volume_and_assisting_half(self):
        got = attribute([ex(1, [(10, {"weights": [50.0]}, 0)])], INDEX)
        self.assertEqual(got["byMuscle"], {"Pecs": 500.0, "Triceps": 250.0, "Front Delts": 250.0})
        self.assertEqual(got["byBodyPart"], {"Chest": 500.0})

    def test_unweighted_work_is_counted_not_silently_zeroed(self):
        got = attribute([ex(1, [(0, {}, 0)]), ex(2, [(5, {"weights": [40.0]}, 0)])], INDEX)
        self.assertEqual(got["unweightedExercises"], 1)
        self.assertEqual(got["byMuscle"]["Lats"], 200.0)

    def test_an_exercise_missing_from_the_library_is_named(self):
        got = attribute([ex(999, [(10, {"weights": [50.0]}, 0)], name="Mystery")], INDEX)
        self.assertEqual(got["exercisesNotInLibrary"], ["Mystery"])
        self.assertEqual(got["byMuscle"], {})


class TestRatiosAndUntrained(unittest.TestCase):
    def test_push_pull_and_upper_lower(self):
        got = ratios({"Pecs": 100.0, "Lats": 100.0, "Quads": 50.0})
        self.assertEqual(got["pushPull"], 1.0)
        self.assertEqual(got["upperLower"], 4.0)

    def test_no_denominator_gives_none_not_a_crash(self):
        self.assertIsNone(ratios({"Pecs": 100.0})["pushPull"])

    def test_full_body_joins_neither_chain(self):
        got = ratios({"Full Body": 500.0})
        self.assertEqual((got["push"], got["pull"]), (0.0, 0.0))

    def test_untrained_skips_full_body_and_assist_only_muscles(self):
        got = untrained({"Pecs": 10.0}, INDEX)
        self.assertIn("Lats", got)
        self.assertNotIn("Full Body", got)
        self.assertNotIn("Triceps", got)  # never a main muscle in this catalog


class TestProgressRoute(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def _run(self, detail_side_effect=None, records=None):
        records = records if records is not None else [{"trainingId": 1, "type": 3}]
        detail = detail_side_effect or (lambda tid, kind: [ex(1, [(10, {"weights": [50.0]}, 0)])])
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_training_records', return_value=records), \
             mock.patch.object(app_module.client, 'get_library', return_value=LIBRARY), \
             mock.patch.object(app_module, '_session_detail', side_effect=detail):
            return self.client.get('/api/progress/muscles?days=30')

    def test_returns_muscle_volume_and_ratios(self):
        resp = self._run()
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["byMuscle"][0], {"muscle": "Pecs", "volume": 500.0})
        self.assertEqual(body["ratios"]["push"], 1000.0)   # Pecs 500 + Triceps 250 + Front Delts 250
        self.assertIn("Lats", body["notTrained"])

    def test_one_unreadable_session_does_not_empty_the_page(self):
        def flaky(tid, kind):
            raise RuntimeError("detail exploded")
        resp = self._run(detail_side_effect=flaky)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["byMuscle"], [])

    def test_days_is_clamped_and_junk_falls_back_to_the_default(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_training_records', return_value=[]), \
             mock.patch.object(app_module.client, 'get_library', return_value=LIBRARY):
            self.assertEqual(self.client.get('/api/progress/muscles?days=9999').get_json()["windowDays"], 365)
            self.assertEqual(self.client.get('/api/progress/muscles?days=abc').get_json()["windowDays"], 30)

    def test_signed_out_is_401(self):
        with mock.patch.object(app_module.client, 'credentials', {}):
            self.assertEqual(self.client.get('/api/progress/muscles').status_code, 401)


if __name__ == "__main__":
    unittest.main()
