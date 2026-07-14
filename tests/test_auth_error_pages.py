"""An expired token must send the user to the login page, never to a 500.

Speediance tokens expire (or get rotated out from under us) intermittently. When that
happened on /schedule it raised SpeedianceAuthError straight out of the view and Flask
turned it into an Internal Server Error, which tells the user nothing and offers them no
way out. Every page that talks to the API has to degrade to "Session expired, please log
in again".
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
from api_client import SpeedianceAuthError  # noqa: E402


class TestExpiredTokenRedirects(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def _expired(self, path):
        # Pretend we hold a token, but have the API reject it the way a real expiry does.
        with mock.patch.object(app_module.client, 'credentials', {'token': 'stale', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_user_workouts',
                               side_effect=SpeedianceAuthError("Login expired. Please re-login.")), \
             mock.patch.object(app_module.client, 'logout'):
            return self.client.get(path)

    def test_schedule_redirects_to_settings_instead_of_500(self):
        resp = self._expired('/schedule')
        self.assertEqual(resp.status_code, 302, "expired token must redirect, not 500")
        self.assertIn('/settings', resp.headers['Location'])

    def test_dashboard_redirects_to_settings_instead_of_500(self):
        resp = self._expired('/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/settings', resp.headers['Location'])


if __name__ == '__main__':
    unittest.main()
