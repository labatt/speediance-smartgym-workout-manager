import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module

class TestWpOAuthRoutes(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_connect_redirects_to_authorize(self):
        with mock.patch.object(app_module.wellness, "begin_authorization",
                               return_value="https://wellnessproject.ai/api/oauth/authorize?x=1") as b:
            resp = self.client.get("/wp/connect")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("oauth/authorize", resp.headers["Location"])
        self.assertTrue(b.call_args[0][0].endswith("/wp/callback"))

    def test_callback_completes_and_redirects_to_settings(self):
        with mock.patch.object(app_module.wellness, "complete_authorization") as comp:
            resp = self.client.get("/wp/callback?code=abc&state=xyz")
        comp.assert_called_once()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/settings", resp.headers["Location"])


class TestSettingsBackfillControls(unittest.TestCase):
    """The Wellness Project Connect/Backfill controls live in the Settings page;
    the standalone /wp/reconcile page was retired to a redirect."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_settings_shows_connect_when_disconnected(self):
        with mock.patch.object(app_module.wellness, "is_connected", return_value=False), \
             mock.patch.object(app_module.client, "get_accessories", return_value=[]):
            resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/wp/connect", resp.data)
        self.assertNotIn(b"wpBackfillBtn", resp.data)

    def test_settings_shows_backfill_and_spinner_when_connected(self):
        with mock.patch.object(app_module.wellness, "is_connected", return_value=True), \
             mock.patch.object(app_module.client, "get_accessories", return_value=[]):
            resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/wp/backfill", resp.data)   # the backfill fetch
        self.assertIn(b"wpSpinner", resp.data)       # spinner element present

    def test_reconcile_redirects_to_settings(self):
        resp = self.client.get("/wp/reconcile")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/settings", resp.headers["Location"])


if __name__ == "__main__":
    unittest.main()
