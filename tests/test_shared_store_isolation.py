"""Regression guard: the test suite must never touch the real shared store.

A single-file pytest run once bypassed the bootstrap and overwrote the live
owned-equipment list. These tests fail loudly if that protection stops working.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import avoided_store, equipment_store  # noqa: E402

REAL = os.path.expanduser("~/.config/speediance-mcp/speediance-mcp.db")


class TestIsolation(unittest.TestCase):
    def test_env_var_is_armed(self):
        self.assertTrue(os.environ.get("AVOIDED_DB_PATH"),
                        "AVOIDED_DB_PATH is not armed: conftest.py or the test_00 bootstrap is not running")

    def test_the_resolved_path_is_not_the_real_shared_store(self):
        for resolved in (avoided_store.db_path({}), avoided_store.db_path(None)):
            self.assertNotEqual(os.path.realpath(resolved), os.path.realpath(REAL))
            self.assertNotEqual(os.path.realpath(resolved), os.path.realpath(avoided_store.DEFAULT_PATH))

    def test_the_equipment_store_resolves_through_the_same_rule(self):
        # It imports db_path from avoided_store precisely so there is one rule to protect.
        self.assertIs(equipment_store.db_path, avoided_store.db_path)

    def test_writing_with_no_explicit_path_stays_inside_the_temp_store(self):
        equipment_store.set_equipment(owned=["Canary"])
        self.assertEqual(equipment_store.get_equipment()["owned"], ["Canary"])
        self.assertNotIn("Canary", open(REAL, "rb").read().decode("utf-8", "ignore")
                         if os.path.exists(REAL) else "")


if __name__ == "__main__":
    unittest.main()
