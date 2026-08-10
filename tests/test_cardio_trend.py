"""The cardio trend endpoint returns a time-sorted series of the athlete's cardio
sessions, filtered by courseType, and never 500s when one session's info fails."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module  # noqa: E402
from api_client import SpeedianceAPIError, SpeedianceAuthError  # noqa: E402

RECORDS = [
    {"trainingId": 1, "courseType": 2, "startTimestamp": 200, "title": "HIIT Rowing"},
    {"trainingId": 2, "courseType": 0, "startTimestamp": 150, "title": "Strength"},
    {"trainingId": 3, "courseType": 2, "startTimestamp": 100, "title": "Row & Flow"},
]
SESS = {
    1: {"trainingTime": 530, "totalDistance": 892.71, "totalEnergy": 29580.29, "calorie": 161, "completionRate": 29.0, "rpe": 6},
    3: {"trainingTime": 120, "totalDistance": 200.0, "totalEnergy": 1412.01, "calorie": 23, "completionRate": 10.0, "rpe": 4},
}


class TestCardioTrend(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def _run(self, session_side):
        # Isolate the cache so tests don't read/write the real file.
        with mock.patch.object(app_module, 'load_cardio_cache', return_value={}), \
             mock.patch.object(app_module, 'save_cardio_cache'), \
             mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_records', return_value=RECORDS), \
             mock.patch.object(app_module.client, 'get_training_session_info', side_effect=session_side):
            return self.client.get('/api/cardio/trend')

    def test_filters_to_cardio_and_sorts_by_time(self):
        resp = self._run(lambda tid: SESS[tid])
        self.assertEqual(resp.status_code, 200)
        s = resp.get_json()["sessions"]
        self.assertEqual([x["trainingId"] for x in s], [3, 1])  # sorted by startTimestamp asc
        self.assertAlmostEqual(s[1]["pace500"], 296.9, delta=0.2)

    def test_one_bad_session_is_skipped_not_fatal(self):
        def side(tid):
            if tid == 1:
                raise SpeedianceAPIError("Sorry. You do not have access.")
            return SESS[tid]
        resp = self._run(side)
        self.assertEqual(resp.status_code, 200)
        s = resp.get_json()["sessions"]
        self.assertEqual([x["trainingId"] for x in s], [3])

    def test_auth_error_propagates_as_401(self):
        resp = self._run(mock.Mock(side_effect=SpeedianceAuthError("Login expired.")))
        self.assertEqual(resp.status_code, 401)

    def test_unauthorized_when_no_token(self):
        with mock.patch.object(app_module.client, 'credentials', {}):
            resp = self.client.get('/api/cardio/trend')
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main()
