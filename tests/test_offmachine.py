"""Off-machine training: the store, the adapters, and the derivations they feed.

The whole design rests on one claim — that off-machine sets can be adapted into the
shapes the existing derivations already consume, so volume-by-muscle and personal bests
need no knowledge of a second data source. So the important tests here do not check the
adapters in isolation: they run the REAL muscle_balance and dashboard functions over
adapted data. If that claim ever stops holding, those tests fail.
"""

import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard as dashboard_calc  # noqa: E402
import muscle_balance  # noqa: E402
import offmachine  # noqa: E402
import offmachine_store as store  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        os.unlink(self.path)  # let sqlite create it

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def add(self, day, sets, **kw):
        return store.add_sets({}, day, sets, path=self.path, **kw)

    def test_sets_come_back_with_per_exercise_set_numbers(self):
        rows = self.add("2026-09-23", [
            {"name": "Dumbbell Bench Press", "groupId": 11, "reps": 10, "weight": 40},
            {"name": "Dumbbell Bench Press", "groupId": 11, "reps": 9, "weight": 40},
            {"name": "Goblet Squat", "groupId": 22, "reps": 12, "weight": 50},
        ])
        press = [r for r in rows if r["name"] == "Dumbbell Bench Press"]
        self.assertEqual([r["setIndex"] for r in press], [1, 2])
        # A set index is per movement, so the squat is set 1 — not set 3 of the session.
        squat = [r for r in rows if r["name"] == "Goblet Squat"]
        self.assertEqual([r["setIndex"] for r in squat], [1])

    def test_a_movement_with_no_speediance_equivalent_stores_with_no_group(self):
        rows = self.add("2026-09-23", [{"name": "Hotel Stairwell Carry", "reps": 5, "weight": 60}])
        self.assertIsNone(rows[0]["groupId"])
        self.assertEqual(rows[0]["name"], "Hotel Stairwell Carry")

    def test_bodyweight_sets_are_allowed_but_broken_rep_counts_are_not(self):
        rows = self.add("2026-09-23", [{"name": "Push-Up", "reps": 20}])
        self.assertEqual(rows[0]["weight"], 0.0)   # zero load is a real answer
        with self.assertRaises(ValueError):
            self.add("2026-09-24", [{"name": "Push-Up", "reps": 0}])
        with self.assertRaises(ValueError):
            self.add("2026-09-24", [{"name": "Push-Up", "reps": "some"}])
        with self.assertRaises(ValueError):
            self.add("2026-09-24", [{"name": "", "reps": 5}])
        with self.assertRaises(ValueError):
            self.add("2026-09-24", [{"name": "Push-Up", "reps": 5, "weight": -10}])

    def test_a_malformed_date_is_refused_rather_than_stored(self):
        with self.assertRaises(ValueError):
            self.add("last tuesday", [{"name": "Push-Up", "reps": 5}])

    def test_range_listing_is_inclusive_and_days_logged_is_distinct(self):
        self.add("2026-09-20", [{"name": "Push-Up", "reps": 10}])
        self.add("2026-09-23", [{"name": "Push-Up", "reps": 10},
                                {"name": "Push-Up", "reps": 8}])
        self.add("2026-09-30", [{"name": "Push-Up", "reps": 10}])
        in_range = store.list_sets({}, "2026-09-20", "2026-09-23", path=self.path)
        self.assertEqual(len(in_range), 3)
        self.assertEqual(store.days_logged({}, "2026-09-01", "2026-09-30", path=self.path),
                         ["2026-09-20", "2026-09-23", "2026-09-30"])

    def test_a_day_can_be_removed_again(self):
        self.add("2026-09-23", [{"name": "Push-Up", "reps": 10},
                                {"name": "Goblet Squat", "reps": 10, "weight": 50}])
        self.assertEqual(store.delete_day({}, "2026-09-23", path=self.path), 2)
        self.assertEqual(store.list_sets({}, "2026-09-23", "2026-09-23", path=self.path), [])

    def test_one_set_can_be_removed_by_id(self):
        rows = self.add("2026-09-23", [{"name": "Push-Up", "reps": 10},
                                       {"name": "Push-Up", "reps": 8}])
        self.assertTrue(store.delete_set({}, rows[0]["id"], path=self.path))
        self.assertFalse(store.delete_set({}, 999999, path=self.path))
        self.assertEqual(len(store.list_sets({}, "2026-09-23", "2026-09-23", path=self.path)), 1)

    def test_the_speediance_manual_session_can_be_linked(self):
        rows = self.add("2026-09-22", [{"name": "Push-Up", "reps": 10}], training_id=3792,
                        location="hotel")
        self.assertEqual(rows[0]["trainingId"], 3792)
        self.assertEqual(rows[0]["location"], "hotel")


class AdapterTest(unittest.TestCase):
    """The adapters, checked against the real derivations they exist to feed."""

    # A minimal library entry in the catalog's own shape, so muscle_index parses it
    # exactly as it parses Speediance's.
    LIBRARY = [{"id": 11, "trainingPartId2": 11,
                "mainMuscleGroupList": [{"muscleGroupName": "Pectoralis Major"}],
                "auxiliaryMuscleGroupList": [{"muscleGroupName": "Triceps"}]}]

    def sets(self, **overrides):
        base = {"id": 1, "day": "2026-09-23", "trainingId": None, "groupId": 11,
                "name": "Dumbbell Bench Press", "setIndex": 1, "reps": 10, "weight": 40.0,
                "side": "both", "location": "hotel", "note": ""}
        base.update(overrides)
        return base

    def test_adapted_sets_produce_volume_through_the_real_muscle_balance(self):
        rows = [self.sets(id=1, setIndex=1, reps=10, weight=40),
                self.sets(id=2, setIndex=2, reps=8, weight=40)]
        exercises = offmachine.as_exercises(rows)
        self.assertEqual(len(exercises), 1, "both sets belong to one movement")
        # 10x40 + 8x40 = 720, computed by the machine's own function.
        self.assertEqual(muscle_balance.exercise_volume(exercises[0]), 720.0)

        index = muscle_balance.muscle_index(self.LIBRARY)
        attributed = muscle_balance.attribute(exercises, index)
        # Main muscle takes the full volume, assisting half — the standing convention.
        self.assertEqual(attributed["byMuscle"]["Pectoralis Major"], 720.0)
        self.assertEqual(attributed["byMuscle"]["Triceps"], 360.0)
        self.assertEqual(attributed["byBodyPart"]["Chest"], 720.0)

    def test_a_single_arm_set_is_not_counted_as_both_arms(self):
        """A one-arm row at 40 is 40, not 80.

        set_load doubles a set only when BOTH cables carry load. Putting a unilateral
        set's weight into `weights` instead of `leftWeights` would read as bilateral and
        inflate every single-arm movement.
        """
        rows = [self.sets(reps=10, weight=40, side="left")]
        exercises = offmachine.as_exercises(rows)
        self.assertEqual(muscle_balance.exercise_volume(exercises[0]), 400.0)

    def test_a_movement_not_in_the_library_is_reported_not_dropped(self):
        rows = [self.sets(groupId=None, name="Hotel Stairwell Carry")]
        attributed = muscle_balance.attribute(offmachine.as_exercises(rows),
                                              muscle_balance.muscle_index(self.LIBRARY))
        self.assertEqual(attributed["exercisesNotInLibrary"], ["Hotel Stairwell Carry"])
        self.assertEqual(attributed["byMuscle"], {})

    def test_stat_rows_drive_a_personal_best_through_the_real_dashboard_code(self):
        """The payoff: a hotel session sets a personal best with no change to dashboard.py."""
        rows = [
            self.sets(id=1, day="2026-09-01", reps=10, weight=30),
            self.sets(id=2, day="2026-09-23", reps=10, weight=45),
        ]
        stats = offmachine.stat_rows(rows)
        self.assertIn("Dumbbell Bench Press", stats)
        found = dashboard_calc.personal_records(stats, within_days=14,
                                                today=datetime.date(2026, 9, 24))
        self.assertEqual(len(found), 1)
        kinds = {k["kind"]: k for k in found[0]["kinds"]}
        self.assertEqual(kinds["Heaviest weight"]["value"], 45.0)
        self.assertEqual(kinds["Heaviest weight"]["previous"], 30.0)
        self.assertEqual(kinds["Heaviest weight"]["gain"], 15.0)

    def test_stat_rows_sum_a_days_volume_and_take_that_days_top_weight(self):
        rows = [self.sets(id=1, setIndex=1, reps=10, weight=40),
                self.sets(id=2, setIndex=2, reps=5, weight=50)]
        row = offmachine.stat_rows(rows)["Dumbbell Bench Press"][0]
        self.assertEqual(row["maxWeight"], 50.0)
        self.assertEqual(row["totalCapacity"], 10 * 40 + 5 * 50)

    def test_a_day_trained_both_on_and_off_the_machine_merges_into_one_row(self):
        """Two sources, one day, one row — or personal_records sees a phantom 'previous'.

        If both rows survived, the same day would appear twice and the later scan could
        report one of them as the record and the other as what it beat.
        """
        machine = {"Dumbbell Bench Press": [
            {"dayStr": "2026-09-23", "maxWeight": 50.0, "totalCapacity": 500.0}]}
        local = offmachine.stat_rows([self.sets(reps=10, weight=40)])
        merged = offmachine.merge_stats(machine, local)
        rows = merged["Dumbbell Bench Press"]
        self.assertEqual(len(rows), 1, "one day is one row")
        self.assertEqual(rows[0]["maxWeight"], 50.0, "the heavier of the two")
        self.assertEqual(rows[0]["totalCapacity"], 900.0, "500 on the machine + 400 off it")
        self.assertEqual(rows[0]["source"], "mixed")

    def test_merging_keeps_days_that_only_one_source_has_and_stays_sorted(self):
        machine = {"Dumbbell Bench Press": [
            {"dayStr": "2026-09-20", "maxWeight": 45.0, "totalCapacity": 450.0}]}
        local = offmachine.stat_rows([self.sets(day="2026-09-10", reps=10, weight=30),
                                      self.sets(id=2, day="2026-09-23", reps=10, weight=40)])
        rows = offmachine.merge_stats(machine, local)["Dumbbell Bench Press"]
        self.assertEqual([r["dayStr"] for r in rows],
                         ["2026-09-10", "2026-09-20", "2026-09-23"])

    def test_merging_leaves_an_exercise_only_the_machine_knows_untouched(self):
        machine = {"Cable Fly": [{"dayStr": "2026-09-20", "maxWeight": 30.0,
                                  "totalCapacity": 300.0}]}
        merged = offmachine.merge_stats(machine, offmachine.stat_rows([self.sets()]))
        self.assertEqual(merged["Cable Fly"], machine["Cable Fly"])
        self.assertIn("Dumbbell Bench Press", merged)

    def test_sessions_summarise_each_day_newest_first(self):
        rows = [self.sets(id=1, day="2026-09-20", reps=10, weight=40),
                self.sets(id=2, day="2026-09-23", reps=10, weight=40),
                self.sets(id=3, day="2026-09-23", name="Goblet Squat", groupId=22,
                          reps=12, weight=50)]
        out = offmachine.sessions(rows)
        self.assertEqual([s["day"] for s in out], ["2026-09-23", "2026-09-20"])
        latest = out[0]
        self.assertEqual(latest["exerciseCount"], 2)
        self.assertEqual(latest["setCount"], 2)
        self.assertEqual(latest["volume"], 10 * 40 + 12 * 50)
        self.assertEqual(latest["location"], "hotel")

    def test_adapted_exercises_are_marked_as_off_machine(self):
        """Nothing may pass hotel work off as machine data."""
        exercises = offmachine.as_exercises([self.sets()])
        self.assertEqual(exercises[0]["source"], "offmachine")
        self.assertEqual(exercises[0]["finishedReps"][0]["source"], "offmachine")
        self.assertEqual(offmachine.stat_rows([self.sets()])["Dumbbell Bench Press"][0]["source"],
                         "offmachine")


if __name__ == "__main__":
    unittest.main()


class GroupIdsTest(unittest.TestCase):
    def test_names_with_a_group_id_are_returned_for_history_lookup(self):
        sets = [{"name": "Dumbbell Bench Press", "groupId": 11},
                {"name": "Dumbbell Bench Press", "groupId": 11},
                {"name": "Hotel Stairwell Carry", "groupId": None}]
        self.assertEqual(offmachine.group_ids(sets), {"Dumbbell Bench Press": 11})
