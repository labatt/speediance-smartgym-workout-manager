"""A session's exercise breakdown must survive a failing session-info sub-call.

The history detail route makes two API calls: the exercise breakdown
(cttTrainingInfoDetail, the thing the user actually wants) and an optional
session-info summary (courseTrainingInfo — name/duration/calories). For some
Custom workouts the session-info endpoint returns 403 "Sorry. You do not have
access." Letting that 403 propagate 500s the whole route, so the frontend sees
no `detail` array and prints "No exercise breakdown available for this session
type." — even though the breakdown fetched perfectly. The frontend already
falls back to the summary row (rec.*) when session is empty, so a session-info
failure must degrade to session={} rather than kill the breakdown.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
from api_client import SpeedianceAPIError, SpeedianceAuthError  # noqa: E402


class TestHistoryDetailResilience(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_breakdown_survives_session_info_403(self):
        detail = [{"actionLibraryName": "Aerobic Rowing", "finishedReps": []}]
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_detail', return_value=detail), \
             mock.patch.object(app_module.client, 'get_training_session_info',
                               side_effect=SpeedianceAPIError("Sorry. You do not have access.")):
            resp = self.client.get('/api/history/detail/1048701?type=custom')
        self.assertEqual(resp.status_code, 200, "a session-info 403 must not 500 the whole route")
        body = resp.get_json()
        self.assertEqual(body['detail'], detail, "the exercise breakdown must still be returned")
        self.assertEqual(body['session'], {}, "session degrades to empty when its sub-call fails")

    def test_auth_error_from_session_info_still_401s(self):
        # A genuine token expiry (not a resource 403) must still surface as 401,
        # so the frontend can send the user back to login.
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_detail', return_value=[]), \
             mock.patch.object(app_module.client, 'get_training_session_info',
                               side_effect=SpeedianceAuthError("Login expired. Please re-login.")):
            resp = self.client.get('/api/history/detail/1048701?type=custom')
        self.assertEqual(resp.status_code, 401)


if __name__ == '__main__':
    unittest.main()
