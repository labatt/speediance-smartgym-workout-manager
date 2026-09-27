import json, os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module
from wellness_client import WellnessAuthError
import datetime, tempfile

# The backfill route writes its report to app.WP_REPORT_FILE -- the REAL file the Settings
# page shows. Point it at a temp file for the whole module so a test run never overwrites
# the live report with fake data (roadmap #14).
_REAL_REPORT_FILE = app_module.WP_REPORT_FILE
_TMP_DIR = tempfile.TemporaryDirectory()


def setUpModule():
    app_module.WP_REPORT_FILE = os.path.join(_TMP_DIR.name, "report.json")


def tearDownModule():
    app_module.WP_REPORT_FILE = _REAL_REPORT_FILE
    _TMP_DIR.cleanup()


class TestWindowAndReport(unittest.TestCase):
    def test_window_is_90_days_inclusive(self):
        # Wellness Project rejects list_workouts ranges over 90 days, counting both ends
        # (2026-06-29 -> 2026-09-27 is "91 days"), roadmap #13.
        start, end = app_module._wp_window()
        span = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days + 1
        self.assertEqual(span, 90)

    def test_report_goes_to_the_patched_file(self):
        self.assertNotEqual(app_module.WP_REPORT_FILE, _REAL_REPORT_FILE)

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

SP_FREE_RECORDS = [{"trainingId": 2000001, "type": 1, "courseType": 0, "totalCapacity": 1000.0,
                    "calorie": 341, "trainingTime": 900, "startTime": "2026-08-29 09:00:00",
                    "title": "Free Lift"}]
SP_FREE_PAYLOAD = {"id": 2000001, "type": 1, "totalCapacity": 1000.0, "actionList": [
    {"actionLibraryName": "Seated Barbell Row", "groupId": 424, "completionMethod": 1,
     "setList": [{"summary": {"finishedCount": 10, "weight": 100, "time": 40,
                              "totalCapacity": 1000.0}, "rawRepList": []}]}]}
SP_QUICK_PAYLOAD = {"id": 2000001, "type": 7, "totalCapacity": 1000.0}  # no actionList


class TestBackfillRoutes(unittest.TestCase):
    """Roadmap #8: Free Lift / Quick sessions live on freeTraining, not cttTrainingInfoDetail."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _run(self, detail_side_effect, records=SP_FREE_RECORDS):
        w = app_module.wellness
        with mock.patch.object(w, "is_connected", return_value=True), \
             mock.patch.object(w, "list_workouts", return_value=WP_LIST), \
             mock.patch.object(w, "get_workout", return_value="... No exercises logged ..."), \
             mock.patch.object(w, "update_workout", return_value="ok") as upd, \
             mock.patch.object(app_module.client, "get_training_records", return_value=records), \
             mock.patch.object(app_module.client, "get_training_detail",
                               side_effect=detail_side_effect) as det:
            body = self.client.post("/wp/backfill?mode=manual").get_json()
        return body, upd, det

    def test_free_lift_is_read_from_free_training(self):
        body, upd, det = self._run(lambda tid, kind: SP_FREE_PAYLOAD if kind == "free" else [])
        self.assertEqual(det.call_args_list[0].args, (2000001, "free"))
        self.assertEqual(len(body["applied"]), 1, body)
        sets = upd.call_args.args[1][0]["sets"]
        self.assertEqual(sets, [{"reps": 10, "weight_lb": 100.0}])

    def test_quick_session_falls_back_to_free_training_detail(self):
        detail = [{"actionLibraryName": "Standing Barbell Calf Raise", "completionMethod": 1,
                   "finishedReps": [{"finishedCount": 12, "targetCount": 12, "time": 30,
                                     "trainingInfoDetail": {"weights": [40]}}]}]
        body, upd, det = self._run(
            lambda tid, kind: {"free": SP_QUICK_PAYLOAD, "free_detail": detail}.get(kind, []))
        self.assertEqual([c.args[1] for c in det.call_args_list], ["free", "free_detail"])
        self.assertEqual(len(body["applied"]), 1, body)
        self.assertEqual(upd.call_args.args[1][0]["name"], "Standing Barbell Calf Raise")

    def test_goal_focused_uses_ai_route(self):
        records = [dict(SP_FREE_RECORDS[0], type=9, title="Goal-Focused Workout")]
        body, upd, det = self._run(lambda tid, kind: SP_DETAIL if kind == "ai" else [], records)
        self.assertEqual(det.call_args_list[0].args, (2000001, "ai"))
        self.assertEqual(len(body["applied"]), 1, body)


if __name__ == "__main__":
    unittest.main()
