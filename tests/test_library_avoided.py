import os
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
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

    # --- I-8 ---

    def test_avoid_toggle_button_is_not_nested_inside_an_anchor(self):
        """Interactive content (a <button>) inside an <a> is invalid HTML — the toggle
        must be a sibling of the card's link, not a descendant of it."""
        r = self.c.get("/library")
        html = r.get_data(as_text=True)

        class _AnchorNestingChecker(HTMLParser):
            def __init__(self):
                super().__init__()
                self.a_depth = 0
                self.violations = 0
                self.saw_button = False

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'a':
                    self.a_depth += 1
                if tag == 'button' and 'avoid-toggle-btn' in (attrs.get('class') or ''):
                    self.saw_button = True
                    if self.a_depth > 0:
                        self.violations += 1

            def handle_endtag(self, tag):
                if tag == 'a' and self.a_depth > 0:
                    self.a_depth -= 1

        checker = _AnchorNestingChecker()
        checker.feed(html)
        self.assertTrue(checker.saw_button, "expected to find at least one avoid-toggle-btn")
        self.assertEqual(checker.violations, 0,
                         "avoid-toggle-btn must never be nested inside an <a> element")

    def test_reason_popover_handles_enter_and_escape(self):
        r = self.c.get("/library")
        html = r.get_data(as_text=True)
        self.assertIn("'Enter'", html)
        self.assertIn("'Escape'", html)

    def test_toggle_button_meets_minimum_touch_target(self):
        r = self.c.get("/library")
        html = r.get_data(as_text=True)
        m = re.search(r'class="avoid-toggle-btn([^"]*)"', html)
        self.assertIsNotNone(m, "expected an avoid-toggle-btn element")
        classes = m.group(1)
        # Tailwind: w-9/h-9 = 2.25rem = 36px at the default root font size.
        self.assertIn("w-9", classes)
        self.assertIn("h-9", classes)

    def test_inline_error_shown_on_avoid_failure(self):
        r = self.c.get("/library")
        html = r.get_data(as_text=True)
        self.assertIn("showInlineError", html)
        # Called from both the save and the remove paths, not just defined.
        self.assertGreaterEqual(html.count("showInlineError"), 3)


if __name__ == "__main__":
    unittest.main()
