import json, os, unittest
import reconcile

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)

class TestTransform(unittest.TestCase):
    def test_miami_pull_oracle(self):
        detail = _load("sp_detail_1103072.json")
        out = reconcile.sp_detail_to_wp_exercises(detail)
        # 5 exercises, in order
        names = [e["name"] for e in out]
        self.assertEqual(names, [
            "Barbell Bent Over Row", "Seated Barbell Lat Pulldown",
            "Seated Barbell Wide Row", "Standing Barbell Biceps Curl",
            "Standing Barbell Shrugs",
        ])
        row = out[0]
        self.assertEqual(row["slot_type"], "working")
        # 4 sets: 12@30, 10@40, 8@45, 8@50 (reps from finishedCount, load from weights[0])
        self.assertEqual([(s["reps"], s["weight_lb"]) for s in row["sets"]],
                         [(12, 30.0), (10, 40.0), (8, 45.0), (8, 50.0)])

    def test_bodyweight_set_when_load_zero(self):
        detail = [{
            "actionLibraryName": "Push Up", "completionMethod": 1,
            "finishedReps": [
                {"finishedCount": 15, "targetCount": 15, "time": 20,
                 "trainingInfoDetail": {"weights": [0, 0, 0]}},
            ],
        }]
        out = reconcile.sp_detail_to_wp_exercises(detail)
        s = out[0]["sets"][0]
        self.assertEqual(s["reps"], 15)
        self.assertTrue(s["is_bodyweight"])
        self.assertNotIn("weight_lb", s)

    def test_timed_set_maps_to_hold(self):
        detail = [{
            "actionLibraryName": "Plank", "completionMethod": 2,  # timed
            "finishedReps": [
                {"finishedCount": 0, "targetCount": 0, "time": 45,
                 "trainingInfoDetail": {"weights": []}},
            ],
        }]
        out = reconcile.sp_detail_to_wp_exercises(detail)
        s = out[0]["sets"][0]
        self.assertEqual(s["hold_length_sec"], 45)
        self.assertNotIn("reps", s)

    def test_skipped_sets_omitted(self):
        detail = [{
            "actionLibraryName": "Curl", "completionMethod": 1,
            "finishedReps": [
                {"finishedCount": 10, "targetCount": 10, "time": 10,
                 "trainingInfoDetail": {"weights": [20, 20]}},
                {"finishedCount": 0, "targetCount": 10, "time": 0,   # skipped
                 "trainingInfoDetail": {"weights": [0]}},
            ],
        }]
        out = reconcile.sp_detail_to_wp_exercises(detail)
        self.assertEqual(len(out[0]["sets"]), 1)

    def test_all_skipped_exercise_omitted(self):
        detail = [{
            "actionLibraryName": "Skipped", "completionMethod": 1,
            "finishedReps": [
                {"finishedCount": 0, "targetCount": 10, "time": 0,
                 "trainingInfoDetail": {"weights": [0]}},
            ],
        }]
        self.assertEqual(reconcile.sp_detail_to_wp_exercises(detail), [])


WP_LIST = """Workouts (2026-06-01 → 2026-08-30):
[ID 696827] 2026-08-29: Strength Training · 33 min · 341 cal
[ID 696826] 2026-08-28: Workout · 37 min · 552 cal · 1.81 mi
[ID 696955] 2026-08-25: Upper @ Gym · NSI 24.5 (Below Average)
[ID 465860] 2026-08-20: Walking · 11 min · 31 cal · 0.38 mi
Avg session NSI in window: 32.1 across 3 sessions."""

WP_EMPTY = ("2026-08-29: Strength Training · 33 min · 341 cal · Health Connect [ID 696827]\n"
            "  Notes: Imported from Health Connect...\n"
            "No exercises logged for this session. A wearable import arrives as a session total...")

WP_DETAILED = ("2026-08-25: Upper @ Gym · Session NSI 24.5 [ID 696955]\n"
               "  Chest Press: [Cable]\n    Set 1: 15 reps @ 45 lb")

class TestWpParsers(unittest.TestCase):
    def test_parse_list(self):
        rows = reconcile.parse_wp_workout_list(WP_LIST)
        by_id = {r["session_id"]: r for r in rows}
        self.assertEqual(len(rows), 4)
        self.assertEqual(by_id[696827]["date"], "2026-08-29")
        self.assertEqual(by_id[696827]["focus"], "Strength Training")
        self.assertEqual(by_id[696827]["calorie"], 341)
        self.assertIsNone(by_id[696827]["nsi"])
        self.assertFalse(by_id[696827]["has_miles"])
        self.assertTrue(by_id[696826]["has_miles"])
        self.assertEqual(by_id[696955]["nsi"], 24.5)

    def test_is_empty(self):
        self.assertTrue(reconcile.wp_workout_is_empty(WP_EMPTY))
        self.assertFalse(reconcile.wp_workout_is_empty(WP_DETAILED))

    def test_is_backfill_target(self):
        rows = {r["session_id"]: r for r in reconcile.parse_wp_workout_list(WP_LIST)}
        self.assertTrue(reconcile.is_backfill_target(rows[696827]))   # Strength Training, no NSI
        self.assertFalse(reconcile.is_backfill_target(rows[696826]))  # Workout + miles (rowing)
        self.assertFalse(reconcile.is_backfill_target(rows[696955]))  # @ Gym, has NSI
        self.assertFalse(reconcile.is_backfill_target(rows[465860]))  # Walking
