import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module
from wellness_client import WellnessAuthError

WP_LIST = ("Workouts:\n"
           "[ID 696827] 2026-08-29: Strength Training · 33 min · 341 cal\n"
           "[ID 696826] 2026-08-28: Workout · 37 min · 552 cal · 1.81 mi\n")
SP_RECORDS = [{"trainingId": 1103072, "type": 5, "courseType": 0, "totalCapacity": 7745.0,
               "calorie": 341, "trainingTime": 1949, "startTime": "2026-08-29 13:13:17",
               "title": "Miami Pull"}]
SP_DETAIL = [{"actionLibraryName": "Barbell Bent Over Row", "completionMethod": 1,
              "finishedReps": [{"finishedCount": 8, "targetCount": 8, "time": 8,
                                "trainingInfoDetail": {"weights": [50, 50]}}]}]

# Two empty WP "Strength Training" targets on different dates (one day apart, straddling
# the single sp session's date) with the same calorie count -- both fall within
# match_candidates' tolerance of the SAME sp session, so it is the sole confident match
# for each target independently. Ruling A requires only one of them to actually get applied.
WP_LIST_DUP = ("Workouts:\n"
               "[ID 700001] 2026-08-28: Strength Training · 33 min · 341 cal\n"
               "[ID 700002] 2026-08-30: Strength Training · 33 min · 341 cal\n")


class TestBackfill(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_not_connected_returns_connect_required(self):
        with mock.patch.object(app_module.wellness, "is_connected", return_value=False):
            resp = self.client.post("/wp/backfill?mode=scheduled")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "connect_required")

    def test_confident_match_is_applied(self):
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout", return_value="ok") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        body = resp.get_json()
        self.assertEqual(len(body["applied"]), 1)
        self.assertEqual(body["applied"][0]["wp_session_id"], 696827)
        upd.assert_called_once()
        # provenance note carries the trainingId
        self.assertIn("1103072", upd.call_args.kwargs.get("notes", ""))

    def test_nonempty_wp_workout_is_not_written(self):
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="Bench Press: Set 1: 8 @ 135"), \
             mock.patch.object(w, "update_workout") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        upd.assert_not_called()
        self.assertEqual(resp.get_json()["applied"], [])

    def test_double_assignment_guard_applies_only_once(self):
        """Ruling A: two empty WP targets that both confidently match the same
        single Speediance session must not both be written -- only one gets applied,
        the other must be flagged rather than silently dropped or double-applied."""
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST_DUP), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout", return_value="ok") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        body = resp.get_json()
        self.assertEqual(len(body["applied"]), 1)
        upd.assert_called_once()
        self.assertEqual(len(body["flagged"]), 1)
        self.assertIn("already applied", body["flagged"][0]["reason"])

    def test_auth_error_midpass_surfaces_connect_required(self):
        """A token expiring mid-pass (during the empty-check loop) must surface as
        connect_required rather than being swallowed by the broad WellnessAPIError
        handler -- WellnessAuthError is a subclass of WellnessAPIError, so a plain
        `except WellnessAPIError: continue` would hide the auth failure and return
        connected: True with a truncated/empty result."""
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", side_effect=WellnessAuthError("token expired")), \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "connect_required")

    def test_unfillable_empty_detail_is_skipped_not_errored(self):
        """A confident match whose Speediance detail transforms to no exercises
        is reported under 'skipped', not 'errors', and nothing is written."""
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=[]):
            resp = self.client.post("/wp/backfill?mode=manual")
        body = resp.get_json()
        self.assertEqual(body["applied"], [])
        self.assertEqual(body["errors"], [])
        self.assertEqual(len(body["skipped"]), 1)
        self.assertEqual(body["skipped"][0]["wp_session_id"], 696827)
        self.assertIn("no loggable exercises", body["skipped"][0]["reason"])
        upd.assert_not_called()

    def test_deleted_template_detail_fetch_is_skipped(self):
        """A Speediance detail fetch that fails (e.g. 'Template has been deleted')
        is a skip, not an error."""
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail",
                               side_effect=Exception("Template has been deleted")):
            resp = self.client.post("/wp/backfill?mode=manual")
        body = resp.get_json()
        self.assertEqual(body["applied"], [])
        self.assertEqual(body["errors"], [])
        self.assertEqual(len(body["skipped"]), 1)
        self.assertIn("Template has been deleted", body["skipped"][0]["reason"])
        upd.assert_not_called()

    def test_wp_write_failure_is_a_real_error(self):
        """If the WP write itself fails, that IS an error (not a skip)."""
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout", side_effect=Exception("WP 500")), \
             mock.patch.object(app_module.client, "get_training_records", return_value=SP_RECORDS), \
             mock.patch.object(app_module.client, "get_training_detail", return_value=SP_DETAIL):
            resp = self.client.post("/wp/backfill?mode=manual")
        body = resp.get_json()
        self.assertEqual(body["applied"], [])
        self.assertEqual(body["skipped"], [])
        self.assertEqual(len(body["errors"]), 1)
        self.assertEqual(body["errors"][0]["wp_session_id"], 696827)


if __name__ == "__main__":
    unittest.main()
