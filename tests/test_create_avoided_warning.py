import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

LIB = [
    {"id": 1001, "title": "Seated Row", "category_name": "Back", "trainingPartId2": 13,
     "category_id": "13", "device_type_tag": "1", "img": "http://x/row.jpg"},
]


class TestCreatePageWarnsOnAvoided(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self.patches = [
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_categories", return_value=[]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.c = app.app.test_client()

    def tearDown(self):
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_create_page_fetches_avoided_list_once(self):
        r = self.c.get("/create")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("/api/avoided", html)

    def test_create_page_has_avoided_warning_copy(self):
        r = self.c.get("/create")
        html = r.get_data(as_text=True)
        self.assertIn("Marked avoided", html)

    def test_load_avoided_map_does_not_block_init(self):
        """I-6: the avoided-map fetch must not block the rest of page init — the builder
        (or the library search/filter wiring) must be usable immediately, with the
        avoided-map fetch running in the background and re-rendering once it resolves."""
        r = self.c.get("/create")
        html = r.get_data(as_text=True)
        self.assertNotIn("await loadAvoidedMap()", html)
        self.assertIn("loadAvoidedMap().then(", html)


if __name__ == "__main__":
    unittest.main()
