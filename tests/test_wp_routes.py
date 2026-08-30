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

    def test_callback_completes_and_redirects(self):
        with mock.patch.object(app_module.wellness, "complete_authorization") as comp:
            resp = self.client.get("/wp/callback?code=abc&state=xyz")
        comp.assert_called_once()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/wp/reconcile", resp.headers["Location"])
