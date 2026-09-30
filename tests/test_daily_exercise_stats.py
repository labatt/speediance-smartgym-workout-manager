"""Personal bests must be computed from DAILY data, not Speediance's weekly buckets.

The bug this pins, seen live on 2026-09-29: the dashboard showed "Standing Barbell
Triceps Push Down — top volume 3,600 lbs, +1,860 (107%) vs 1,740, yesterday". Every
number in that sentence was wrong, because `userActionStatPage` returns one row per WEEK
with `dayStr` always a Monday. Two sessions in the same week had been summed into one
"day", and the bucket's Monday was read as a session date.

Verified against the live API: seven rows for that movement, dayStr 2026-08-17 through
2026-09-28, every one a Monday, exactly 7 days apart.
"""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard as dashboard_calc  # noqa: E402


def ex(name, group_id, sets):
    """A session-detail exercise. `sets` is [(reps, weight)] or [(reps, weight, side)]."""
    out = []
    for entry in sets:
        reps, weight = entry[0], entry[1]
        side = entry[2] if len(entry) > 2 else 0
        detail = {"weights": [], "leftWeights": [], "rightWeights": []}
        if side == 1:
            detail["leftWeights"] = [weight]
        elif side == 2:
            detail["rightWeights"] = [weight]
        else:
            detail["weights"] = [weight]
        out.append({"finishedCount": reps, "leftRight": side, "trainingInfoDetail": detail})
    return {"actionLibraryName": name, "actionLibraryGroupId": group_id, "finishedReps": out}


class DailyStatsTest(unittest.TestCase):
    def test_one_row_per_day_with_that_days_volume_and_top_weight(self):
        stats = dashboard_calc.daily_exercise_stats([
            ("2026-09-28", [ex("Push Down", 337, [(12, 40), (12, 50), (12, 60)])]),
        ])
        rows = stats["Push Down"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dayStr"], "2026-09-28")
        self.assertEqual(rows[0]["totalCapacity"], 12 * 40 + 12 * 50 + 12 * 60)  # 1800
        self.assertEqual(rows[0]["maxWeight"], 60.0)
        self.assertEqual(rows[0]["source"], "machine")

    def test_two_sessions_in_one_week_stay_two_days(self):
        """The exact live failure: Sunday and Monday must not become one 3,600 lb day."""
        stats = dashboard_calc.daily_exercise_stats([
            ("2026-09-27", [ex("Push Down", 337, [(12, 30), (12, 35), (12, 40), (12, 45)])]),
            ("2026-09-28", [ex("Push Down", 337, [(12, 40), (12, 50), (12, 60)])]),
        ])
        rows = stats["Push Down"]
        self.assertEqual([r["dayStr"] for r in rows], ["2026-09-27", "2026-09-28"])
        self.assertEqual([r["totalCapacity"] for r in rows], [1800.0, 1800.0])
        self.assertNotIn(3600.0, [r["totalCapacity"] for r in rows],
                         "summing a week into one day is the bug this test exists for")

    def test_two_sessions_on_the_SAME_day_do_combine(self):
        """A day's volume is a day's volume, however many times the machine was switched on."""
        stats = dashboard_calc.daily_exercise_stats([
            ("2026-09-28", [ex("Push Down", 337, [(10, 40)])]),
            ("2026-09-28", [ex("Push Down", 337, [(10, 50)])]),
        ])
        rows = stats["Push Down"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["totalCapacity"], 900.0)
        self.assertEqual(rows[0]["maxWeight"], 50.0)

    def test_a_unilateral_set_is_not_doubled(self):
        stats = dashboard_calc.daily_exercise_stats([
            ("2026-09-28", [ex("Single Arm Row", 600, [(10, 40, 1)])]),
        ])
        self.assertEqual(stats["Single Arm Row"][0]["totalCapacity"], 400.0)

    def test_both_cables_loaded_sum_the_way_muscle_balance_does(self):
        """Barbell sets put load on both cables; the set's resistance is their sum."""
        exercise = {"actionLibraryName": "Barbell RDL", "actionLibraryGroupId": 1,
                    "finishedReps": [{"finishedCount": 10, "leftRight": 0,
                                      "trainingInfoDetail": {"weights": [50],
                                                             "leftWeights": [25],
                                                             "rightWeights": [25]}}]}
        stats = dashboard_calc.daily_exercise_stats([("2026-09-28", [exercise])])
        self.assertEqual(stats["Barbell RDL"][0]["maxWeight"], 50.0)

    def test_a_bodyweight_or_timed_exercise_carries_no_volume(self):
        stats = dashboard_calc.daily_exercise_stats([
            ("2026-09-28", [{"actionLibraryName": "Plank", "actionLibraryGroupId": 9,
                             "finishedReps": [{"finishedCount": 0, "leftRight": 0,
                                               "trainingInfoDetail": {"weights": []}}]}]),
        ])
        self.assertEqual(stats["Plank"][0]["totalCapacity"], 0.0)

    def test_a_malformed_day_is_skipped_not_crashed_on(self):
        stats = dashboard_calc.daily_exercise_stats([
            ("", [ex("Push Down", 337, [(10, 40)])]),
            ("2026-09-28", [ex("Push Down", 337, [(10, 40)])]),
        ])
        self.assertEqual(len(stats["Push Down"]), 1)

    def test_the_source_label_can_be_set(self):
        stats = dashboard_calc.daily_exercise_stats(
            [("2026-09-28", [ex("Push Down", 337, [(10, 40)])])], source="offmachine")
        self.assertEqual(stats["Push Down"][0]["source"], "offmachine")


class RecordSourceTest(unittest.TestCase):
    """A record's label must describe the day that produced it."""

    def test_a_machine_day_is_not_labelled_off_machine_just_because_the_movement_was(self):
        """The live mislabel: the card said "off-machine" for a Gym Monster session.

        The old flag asked "has this movement EVER been logged off the machine", which is
        true for any movement also done in a hotel — so a machine PR wore a hotel label.
        """
        stats = {"Push Down": [
            {"dayStr": "2026-09-01", "maxWeight": 40, "totalCapacity": 1200, "source": "offmachine"},
            {"dayStr": "2026-09-28", "maxWeight": 60, "totalCapacity": 1800, "source": "machine"},
        ]}
        found = dashboard_calc.personal_records(stats, within_days=14,
                                                today=datetime.date(2026, 9, 29))
        kinds = {k["kind"]: k for k in found[0]["kinds"]}
        self.assertEqual(kinds["Heaviest weight"]["source"], "machine")
        self.assertEqual(kinds["Best day volume"]["source"], "machine")

    def test_an_off_machine_day_is_labelled_off_machine(self):
        stats = {"Push Down": [
            {"dayStr": "2026-09-01", "maxWeight": 30, "totalCapacity": 900, "source": "machine"},
            {"dayStr": "2026-09-28", "maxWeight": 45, "totalCapacity": 1800, "source": "offmachine"},
        ]}
        found = dashboard_calc.personal_records(stats, within_days=14,
                                                today=datetime.date(2026, 9, 29))
        self.assertTrue(all(k["source"] == "offmachine" for k in found[0]["kinds"]))

    def test_rows_with_no_source_default_to_machine(self):
        stats = {"Push Down": [
            {"dayStr": "2026-09-01", "maxWeight": 30, "totalCapacity": 900},
            {"dayStr": "2026-09-28", "maxWeight": 45, "totalCapacity": 1800},
        ]}
        found = dashboard_calc.personal_records(stats, within_days=14,
                                                today=datetime.date(2026, 9, 29))
        self.assertTrue(all(k["source"] == "machine" for k in found[0]["kinds"]))


if __name__ == "__main__":
    unittest.main()
