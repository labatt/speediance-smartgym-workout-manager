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
