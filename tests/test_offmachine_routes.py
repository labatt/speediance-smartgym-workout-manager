"""The off-machine HTTP surface.

Two things these tests are really guarding:

* A refused set must come back as 400 with a reason. A silent 500 (or worse, a stored
  half-understood set) is how a bad rep count quietly corrupts a personal best.
* Logging must work with NO Speediance token. That is the whole point — someone is
  travelling, which is exactly when the token tends to have expired.

The store path is isolated by conftest's AVOIDED_DB_PATH bootstrap, so nothing here can
reach the real shared database.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import offmachine_store  # noqa: E402


class OffMachineRoutesTest(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        # Start every test from an empty log, whatever order they run in.
        for day in ("2026-09-22", "2026-09-23", "2026-09-24"):
            offmachine_store.delete_day(app_module.client.credentials, day)

    def tearDown(self):
        for day in ("2026-09-22", "2026-09-23", "2026-09-24"):
            offmachine_store.delete_day(app_module.client.credentials, day)

    def post(self, payload):
        return self.client.post('/api/offmachine', json=payload)

    def test_a_session_can_be_logged_and_read_back(self):
        resp = self.post({"day": "2026-09-23", "location": "hotel", "sets": [
            {"name": "Dumbbell Bench Press", "groupId": 11, "reps": 10, "weight": 40},
            {"name": "Dumbbell Bench Press", "groupId": 11, "reps": 8, "weight": 40},
        ]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["count"], 2)

        listed = self.client.get('/api/offmachine?start=2026-09-23&end=2026-09-23').get_json()
        self.assertEqual(len(listed["sets"]), 2)
        self.assertEqual(len(listed["sessions"]), 1)
        session = listed["sessions"][0]
        self.assertEqual(session["day"], "2026-09-23")
        self.assertEqual(session["setCount"], 2)
        self.assertEqual(session["volume"], 10 * 40 + 8 * 40)

    def test_logging_works_without_a_speediance_token(self):
        """Travelling is exactly when the token has expired — logging must still work."""
        with mock.patch.object(app_module.client, 'credentials', {}):
            resp = self.post({"day": "2026-09-23",
                              "sets": [{"name": "Push-Up", "reps": 20}]})
        self.assertEqual(resp.status_code, 200, "a local log needs no API session")

    def test_a_bad_set_is_refused_with_a_reason_not_a_500(self):
        for bad in ({"day": "2026-09-23", "sets": [{"name": "Push-Up", "reps": 0}]},
                    {"day": "2026-09-23", "sets": [{"name": "", "reps": 5}]},
                    {"day": "not a date", "sets": [{"name": "Push-Up", "reps": 5}]},
                    {"day": "2026-09-23", "sets": []}):
            with self.subTest(bad=bad):
                resp = self.post(bad)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("error", resp.get_json())

    def test_nothing_is_stored_when_one_set_in_the_batch_is_bad(self):
        """All-or-nothing: a session half-logged is worse than one not logged."""
        resp = self.post({"day": "2026-09-23", "sets": [
            {"name": "Dumbbell Bench Press", "reps": 10, "weight": 40},
            {"name": "Dumbbell Bench Press", "reps": -1, "weight": 40},
        ]})
        self.assertEqual(resp.status_code, 400)
        listed = self.client.get('/api/offmachine?start=2026-09-23&end=2026-09-23').get_json()
        self.assertEqual(listed["sets"], [], "the valid set must not have been kept")

    def test_a_single_set_can_be_deleted(self):
        stored = self.post({"day": "2026-09-23", "sets": [
            {"name": "Push-Up", "reps": 20}, {"name": "Push-Up", "reps": 15}]}).get_json()
        set_id = stored["sets"][0]["id"]
        self.assertEqual(self.client.delete(f'/api/offmachine/{set_id}').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/offmachine/{set_id}').status_code, 404)
        left = self.client.get('/api/offmachine?start=2026-09-23&end=2026-09-23').get_json()
        self.assertEqual(len(left["sets"]), 1)

    def test_a_whole_day_can_be_deleted(self):
        self.post({"day": "2026-09-23", "sets": [{"name": "Push-Up", "reps": 20},
                                                 {"name": "Goblet Squat", "reps": 10,
                                                  "weight": 50}]})
        resp = self.client.delete('/api/offmachine/day/2026-09-23')
        self.assertEqual(resp.get_json()["deleted"], 2)
        left = self.client.get('/api/offmachine?start=2026-09-23&end=2026-09-23').get_json()
        self.assertEqual(left["sets"], [])

    def test_deleting_a_malformed_day_is_a_400(self):
        self.assertEqual(self.client.delete('/api/offmachine/day/whenever').status_code, 400)


class ManualSessionDetailTest(unittest.TestCase):
    """A type-10 session's detail page serves OUR exercises, since Speediance has none."""

    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        offmachine_store.delete_day(app_module.client.credentials, "2026-09-22")

    def tearDown(self):
        offmachine_store.delete_day(app_module.client.credentials, "2026-09-22")

    def test_manual_detail_returns_the_logged_sets_and_names_the_source(self):
        offmachine_store.add_sets(app_module.client.credentials, "2026-09-22", [
            {"name": "Dumbbell Bench Press", "groupId": 11, "reps": 10, "weight": 40}],
            training_id=3792, location="hotel")
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_session_info',
                               return_value={"startTime": "2026-09-22 14:00:00"}):
            body = self.client.get('/api/history/detail/3792?type=manual').get_json()
        self.assertEqual(body["source"], "offmachine")
        self.assertEqual(len(body["detail"]), 1)
        self.assertEqual(body["detail"][0]["actionLibraryName"], "Dumbbell Bench Press")
        self.assertIn("off-machine log", body["note"])

    def test_manual_detail_with_nothing_logged_explains_rather_than_looking_broken(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_session_info',
                               return_value={"startTime": "2026-09-22 14:00:00"}):
            body = self.client.get('/api/history/detail/3792?type=manual').get_json()
        self.assertEqual(body["source"], "none")
        self.assertEqual(body["detail"], [])
        self.assertIn("stores no exercise detail", body["note"])


if __name__ == '__main__':
    unittest.main()
