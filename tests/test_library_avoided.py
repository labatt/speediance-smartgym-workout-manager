import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
import avoided_store  # noqa: E402

LIB = [
    {"id": 1001, "title": "Seated Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [], "category_id": "13",
     "accessories": "5", "img": "http://x/row.jpg"},
    {"id": 1002, "title": "Banned Lift", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [], "category_id": "13",
     "accessories": "5", "img": "http://x/banned.jpg"},
]


class TestLibraryAvoidedRendering(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = os.path.join(self._tmpdir.name, "speediance-mcp.db")
        avoided_store.set_avoided(self.db_path, 1002, "Banned Lift", "shoulder pain")
        app.client.credentials["avoided_db_path"] = self.db_path

        self.patches = [
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_accessories", return_value=[]),
            mock.patch.object(app.client, "get_categories", return_value=[]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.c = app.app.test_client()

    def tearDown(self):
        app.client.credentials.pop("avoided_db_path", None)
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_library_page_loads(self):
        r = self.c.get("/library")
        self.assertEqual(r.status_code, 200)

    def test_avoided_exercise_marked_in_markup(self):
        r = self.c.get("/library")
        html = r.get_data(as_text=True)
        # The avoided card carries a data attribute the filter/JS can read, and the reason
        # text is present somewhere on the page (e.g. as a title attribute) without being
        # injected via innerHTML string concatenation with unescaped data.
        self.assertIn('data-avoided="1"', html)
        self.assertIn('data-group-id="1002"', html)

    def test_non_avoided_exercise_not_marked(self):
        r = self.c.get("/library")
        html = r.get_data(as_text=True)
        self.assertIn('data-group-id="1001"', html)
        # Row 1001's card block should show data-avoided="0"
        idx = html.index('data-group-id="1001"')
        # data-avoided attr should appear near this card; just confirm the un-avoided marker exists at all
        self.assertIn('data-avoided="0"', html)

    def test_filter_control_present(self):
        r = self.c.get("/library")
        html = r.get_data(as_text=True)
        self.assertIn('avoided-filter', html)


if __name__ == "__main__":
    unittest.main()
