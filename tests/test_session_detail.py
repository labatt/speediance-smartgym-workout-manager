"""Session type -> detail route, and Free Lift payload -> the list shape the rest of the
app (progression, reconcile, history.html) already parses. Synthetic data only."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import session_detail  # noqa: E402


def free_lift(session_total, set_capacity, weight, action_list=True):
    payload = {"id": 1, "type": 1, "totalCapacity": session_total, "trainingTime": 900}
    if action_list:
        payload["actionList"] = [{
            "actionLibraryName": "Seated Barbell Row", "groupId": 424, "completionMethod": 1,
            "setList": [
                {"summary": {"finishedCount": 10, "weight": weight, "time": 40, "leftRight": 0,
                             "totalCapacity": set_capacity}, "rawRepList": []},
                {"summary": {"finishedCount": 0, "weight": weight, "time": 0, "leftRight": 0,
                             "totalCapacity": 0}, "rawRepList": []},
            ]}]
    return payload


class TestDetailRoute(unittest.TestCase):
    def test_routes_by_history_type(self):
        self.assertEqual(session_detail.detail_kind(1), "free")
        self.assertEqual(session_detail.detail_kind(6), "free")
        self.assertEqual(session_detail.detail_kind(7), "free")
        self.assertEqual(session_detail.detail_kind(2), "course")
        self.assertEqual(session_detail.detail_kind(3), "custom")
        self.assertEqual(session_detail.detail_kind(5), "custom")
        self.assertEqual(session_detail.detail_kind(4), "ai")
        self.assertEqual(session_detail.detail_kind(9), "ai")
        self.assertEqual(session_detail.detail_kind(None), "custom")
        self.assertEqual(session_detail.detail_kind("9"), "ai")


class TestFreeTrainingToDetail(unittest.TestCase):
    def test_lb_account_weights_verbatim(self):
        detail, warning = session_detail.free_training_to_detail(free_lift(1000.0, 1000.0, 100))
        self.assertIsNone(warning)
        self.assertEqual(len(detail), 1)
        ex = detail[0]
        self.assertEqual(ex["actionLibraryName"], "Seated Barbell Row")
        self.assertEqual(ex["actionLibraryGroupId"], 424)
        self.assertEqual(ex["completionMethod"], 1)
        first, skipped = ex["finishedReps"]
        self.assertEqual(first["finishedCount"], 10)
        self.assertEqual(first["targetCount"], 10)
        self.assertEqual(first["time"], 40)
        self.assertEqual(first["trainingInfoDetail"]["weights"], [100])
        self.assertEqual(skipped["finishedCount"], 0)

    def test_kg_account_scale_is_removed(self):
        detail, warning = session_detail.free_training_to_detail(free_lift(454.55, 1000.0, 100))
        self.assertIsNone(warning)
        self.assertEqual(detail[0]["finishedReps"][0]["trainingInfoDetail"]["weights"], [45.5])

    def test_unreconciled_keeps_raw_and_warns(self):
        detail, warning = session_detail.free_training_to_detail(free_lift(700.0, 1000.0, 100))
        self.assertEqual(detail[0]["finishedReps"][0]["trainingInfoDetail"]["weights"], [100])
        self.assertIn("didn't reconcile", warning)

    def test_no_action_list_is_empty(self):
        self.assertEqual(session_detail.free_training_to_detail(free_lift(0, 0, 0, action_list=False)), ([], None))
        self.assertEqual(session_detail.free_training_to_detail(None), ([], None))

    def test_feeds_the_backfill_transform(self):
        import reconcile
        detail, _ = session_detail.free_training_to_detail(free_lift(1000.0, 1000.0, 100))
        self.assertEqual(reconcile.sp_detail_to_wp_exercises(detail),
                         [{"name": "Seated Barbell Row", "slot_type": "working",
                           "sets": [{"reps": 10, "weight_lb": 100.0}]}])


if __name__ == "__main__":
    unittest.main()
