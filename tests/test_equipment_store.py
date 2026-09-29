"""Shared owned / unusable equipment store (roadmap #28, #27).

The MCP server's SQLite preferences table is the source of truth, so these tests run
against a temp DB file — never the real shared one.
"""
import json, os, sqlite3, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import equipment_store  # noqa: E402
import app as app_module  # noqa: E402

ENTRIES = [
    {"name": "Barbell", "ids": [4], "img": None, "type": "attachment"},
    {"name": "Handles", "ids": [5, 15], "img": None, "type": "attachment"},
    {"name": "Flat Bench", "ids": [9], "img": None, "type": "furniture"},
]


class TestStore(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def test_empty_store_reads_as_two_empty_lists(self):
        self.assertEqual(equipment_store.get_equipment(path=self.path), {"owned": [], "unusable": []})

    def test_round_trip(self):
        equipment_store.set_equipment(owned=["Barbell", "Handles"], unusable=["Handles"], path=self.path)
        self.assertEqual(equipment_store.get_equipment(path=self.path),
                         {"owned": ["Barbell", "Handles"], "unusable": ["Handles"]})

    def test_passing_none_leaves_that_list_alone(self):
        equipment_store.set_equipment(owned=["Barbell"], unusable=["Barbell"], path=self.path)
        equipment_store.set_equipment(owned=["Barbell", "Handles"], path=self.path)
        self.assertEqual(equipment_store.get_equipment(path=self.path)["unusable"], ["Barbell"])

    def test_names_are_trimmed_and_deduplicated(self):
        equipment_store.set_equipment(owned=["  Barbell ", "barbell", "", "Handles"], path=self.path)
        self.assertEqual(equipment_store.get_equipment(path=self.path)["owned"], ["Barbell", "Handles"])

    def test_it_reads_what_the_mcp_server_wrote(self):
        # Same table, same key: the MCP server writes a plain JSON list.
        conn = sqlite3.connect(self.path)
        conn.execute(equipment_store._DDL)
        conn.execute("INSERT INTO preferences (key, value_json) VALUES (?, ?)",
                     ("owned_equipment", json.dumps(["Barbell", "AeroRow"])))
        conn.commit(); conn.close()
        self.assertEqual(equipment_store.get_equipment(path=self.path)["owned"], ["Barbell", "AeroRow"])

    def test_a_corrupt_value_reads_as_empty_rather_than_exploding(self):
        conn = sqlite3.connect(self.path)
        conn.execute(equipment_store._DDL)
        conn.execute("INSERT INTO preferences (key, value_json) VALUES (?, ?)", ("owned_equipment", "not json"))
        conn.commit(); conn.close()
        self.assertEqual(equipment_store.get_equipment(path=self.path)["owned"], [])


class TestDerivations(unittest.TestCase):
    def test_usable_is_owned_minus_unusable(self):
        eq = {"owned": ["Barbell", "Flat Bench"], "unusable": ["flat bench"]}
        self.assertEqual(equipment_store.usable_names(eq), ["Barbell"])

    def test_owned_ids_expand_every_duplicate_of_a_usable_name(self):
        eq = {"owned": ["Handles", "Flat Bench"], "unusable": ["Flat Bench"]}
        self.assertEqual(equipment_store.owned_ids(eq, ENTRIES), [5, 15])

    def test_unusable_gear_contributes_no_ids(self):
        eq = {"owned": ["Flat Bench"], "unusable": ["Flat Bench"]}
        self.assertEqual(equipment_store.owned_ids(eq, ENTRIES), [])


class TestSettingsIntegration(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.creds = {'token': 't', 'user_id': '1', 'unit': 1, 'avoided_db_path': self.path}

    def test_saving_writes_names_and_rebuilds_the_id_cache_from_usable_ones(self):
        with mock.patch.object(app_module.client, 'credentials', self.creds), \
             mock.patch.object(app_module.client, 'get_accessories',
                               return_value=[{"id": 4, "name": "Barbell"}, {"id": 5, "name": "Handles"},
                                             {"id": 15, "name": "Handles"}, {"id": 9, "name": "Flat Bench"}]), \
             mock.patch.object(app_module.client, 'save_config') as save:
            self.client.post('/settings/accessories',
                             data={'accessories': ['Barbell', 'Flat Bench'], 'unusable': ['Flat Bench']})
        stored = equipment_store.get_equipment(path=self.path)
        self.assertEqual(stored, {"owned": ["Barbell", "Flat Bench"], "unusable": ["Flat Bench"]})
        # Flat Bench is owned but unusable, so its id must not reach the filter cache.
        self.assertEqual(save.call_args[0][7], [4])

    def test_marking_something_unusable_that_is_not_owned_is_ignored(self):
        with mock.patch.object(app_module.client, 'credentials', self.creds), \
             mock.patch.object(app_module.client, 'get_accessories', return_value=[{"id": 4, "name": "Barbell"}]), \
             mock.patch.object(app_module.client, 'save_config'):
            self.client.post('/settings/accessories', data={'accessories': ['Barbell'], 'unusable': ['Handles']})
        self.assertEqual(equipment_store.get_equipment(path=self.path)["unusable"], [])


if __name__ == "__main__":
    unittest.main()
