import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
import avoided_store  # noqa: E402


class TestSettingsAvoidedCard(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = os.path.join(self._tmpdir.name, "speediance-mcp.db")
        app.client.credentials["avoided_db_path"] = self.db_path
        self.addCleanup(lambda: app.client.credentials.pop("avoided_db_path", None))
        # Avoid any real Speediance network call: the live config.json may have a real
        # token, and get_accessories() would otherwise hit the real API from this test.
        self.patches = [
            mock.patch.object(app.wellness, "is_connected", return_value=False),
            mock.patch.object(app.client, "get_accessories", return_value=[]),
            mock.patch.object(app.client, "get_profile", return_value={}),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.c = app.app.test_client()

    def test_empty_state_shown_when_no_avoided(self):
        r = self.c.get("/settings")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        # The server-rendered empty-state paragraph (double-quoted attribute), distinct
        # from the client-side JS that can also build one dynamically after a removal.
        self.assertIn('id="avoided-empty-state"', html)

    def test_lists_avoided_with_reason_and_remove_button(self):
        avoided_store.set_avoided(self.db_path, 1001, "Bench Press", "shoulder pain")
        r = self.c.get("/settings")
        html = r.get_data(as_text=True)
        self.assertIn("Bench Press", html)
        self.assertIn("shoulder pain", html)
        self.assertIn("1001", html)
        self.assertNotIn('id="avoided-empty-state"', html)

    def test_links_to_library(self):
        r = self.c.get("/settings")
        self.assertIn(b'href="/library"', r.data)

    def test_persistent_library_link_shown_when_empty(self):
        # I-10: the "mark more" link must be there whether the list is empty or not.
        r = self.c.get("/settings")
        html = r.get_data(as_text=True)
        self.assertIn('id="avoided-mark-more-link"', html)

    def test_persistent_library_link_shown_when_non_empty(self):
        avoided_store.set_avoided(self.db_path, 1001, "Bench Press", "shoulder pain")
        r = self.c.get("/settings")
        html = r.get_data(as_text=True)
        self.assertIn('id="avoided-mark-more-link"', html)


if __name__ == "__main__":
    unittest.main()
