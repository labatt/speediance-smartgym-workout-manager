"""Accessory deduplication.

Speediance lists the same physical accessory under several ids, so the Settings grid
must show one tile per name and own every id behind it — otherwise ticking the "wrong"
Handles hides every exercise needing the other one.
"""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from accessories import dedupe_accessories, is_owned, parse_selected_ids  # noqa: E402
import app as app_module  # noqa: E402

CATALOG = [
    {"id": 5, "name": "Handles", "type": 0, "img": "handles.png"},
    {"id": 15, "name": "Handles", "type": 0, "img": None},
    {"id": 25, "name": "handles", "type": 0, "img": "other.png"},
    {"id": 4, "name": "Tricep Rope", "type": 0, "img": "rope.png"},
    {"id": 9, "name": "Flat Bench", "type": 1, "img": "bench.png"},
    {"id": None, "name": "", "type": 0},
]


class TestDedupe(unittest.TestCase):
    def setUp(self):
        self.entries = dedupe_accessories(CATALOG)
        self.by_name = {e["name"].lower(): e for e in self.entries}

    def test_one_entry_per_name_regardless_of_case(self):
        self.assertEqual([e["name"] for e in self.entries], ["Flat Bench", "Handles", "Tricep Rope"])

    def test_every_duplicate_id_is_kept(self):
        self.assertEqual(self.by_name["handles"]["ids"], [5, 15, 25])

    def test_furniture_is_distinguished_from_attachments(self):
        self.assertEqual(self.by_name["flat bench"]["type"], "furniture")
        self.assertEqual(self.by_name["handles"]["type"], "attachment")

    def test_the_first_available_image_wins(self):
        self.assertEqual(self.by_name["handles"]["img"], "handles.png")

    def test_nameless_rows_are_dropped(self):
        self.assertEqual(len(self.entries), 3)

    def test_empty_catalog_is_fine(self):
        self.assertEqual(dedupe_accessories(None), [])


class TestOwnership(unittest.TestCase):
    def test_owning_any_duplicate_id_ticks_the_tile(self):
        entry = {"name": "Handles", "ids": [5, 15, 25]}
        self.assertTrue(is_owned(entry, [25]))       # the "wrong" duplicate still counts
        self.assertFalse(is_owned(entry, [4, 9]))
        self.assertFalse(is_owned(entry, []))


class TestParseSelected(unittest.TestCase):
    def test_a_tick_expands_to_every_id_behind_the_name(self):
        self.assertEqual(parse_selected_ids(["5,15,25", "4"]), [5, 15, 25, 4])

    def test_duplicates_collapse_and_junk_is_dropped_rather_than_failing(self):
        self.assertEqual(parse_selected_ids(["5,5", "x", "", "9"]), [5, 9])

    def test_nothing_selected_means_nothing_owned(self):
        self.assertEqual(parse_selected_ids([]), [])


class TestSettingsIntegration(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_settings_renders_one_tile_per_name_with_all_ids(self):
        creds = {'token': 't', 'user_id': '1', 'unit': 1, 'owned_accessories': [25]}
        with mock.patch.object(app_module.client, 'credentials', creds), \
             mock.patch.object(app_module.client, 'get_accessories', return_value=CATALOG), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}), \
             mock.patch.object(app_module, '_avoided_list_safe', return_value=[]), \
             mock.patch.object(app_module.wellness, 'is_connected', return_value=False):
            html = self.client.get('/settings').get_data(as_text=True)
        self.assertEqual(html.count('name="accessories"'), 3)
        self.assertIn('value="5,15,25"', html)

    def test_saving_a_tile_stores_every_id_behind_it(self):
        creds = {'token': 't', 'user_id': '1', 'unit': 1, 'owned_accessories': []}
        with mock.patch.object(app_module.client, 'credentials', creds), \
             mock.patch.object(app_module.client, 'save_config') as save:
            self.client.post('/settings/accessories', data={'accessories': '5,15,25'})
        self.assertEqual(save.call_args[0][7], [5, 15, 25])


if __name__ == "__main__":
    unittest.main()
