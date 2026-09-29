import os
import sqlite3
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import avoided_store as store  # noqa: E402


class TestDbPath(unittest.TestCase):
    def test_uses_config_key_when_present(self):
        self.assertEqual(store.db_path({"avoided_db_path": "/tmp/x.db"}), "/tmp/x.db")

    def test_falls_back_to_default(self):
        self.assertEqual(store.db_path({}), store.DEFAULT_PATH)
        self.assertEqual(store.db_path(None), store.DEFAULT_PATH)


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = os.path.join(self._tmpdir.name, "nested", "speediance-mcp.db")

    def test_set_then_list_round_trips(self):
        store.set_avoided(self.path, 1001, "Bench Press", "shoulder pain")
        rows = store.list_avoided(self.path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["group_id"], 1001)
        self.assertEqual(row["name"], "Bench Press")
        self.assertEqual(row["reason"], "shoulder pain")
        self.assertTrue(row["updated_at"])

    def test_avoided_ids_returns_set_of_ints(self):
        store.set_avoided(self.path, 1001, "Bench Press")
        store.set_avoided(self.path, 1002, "Overhead Press")
        self.assertEqual(store.avoided_ids(self.path), {1001, 1002})

    def test_list_sorted_by_name_case_insensitive(self):
        store.set_avoided(self.path, 1, "zebra move")
        store.set_avoided(self.path, 2, "Apple Move")
        store.set_avoided(self.path, 3, "banana Move")
        names = [r["name"] for r in store.list_avoided(self.path)]
        self.assertEqual(names, ["Apple Move", "banana Move", "zebra move"])

    def test_reason_defaults_to_empty_and_is_stripped(self):
        store.set_avoided(self.path, 5, "Row", "   ")
        self.assertEqual(store.list_avoided(self.path)[0]["reason"], "")
        store.clear_avoided(self.path, 5)
        store.set_avoided(self.path, 5, "Row", "  padded  ")
        self.assertEqual(store.list_avoided(self.path)[0]["reason"], "padded")

    def test_reason_too_long_raises(self):
        with self.assertRaises(ValueError):
            store.set_avoided(self.path, 6, "Row", "x" * 201)

    def test_reason_at_max_length_ok(self):
        store.set_avoided(self.path, 7, "Row", "x" * 200)
        self.assertEqual(len(store.list_avoided(self.path)[0]["reason"]), 200)

    def test_set_avoided_upserts_on_same_group_id(self):
        store.set_avoided(self.path, 8, "Row", "first")
        store.set_avoided(self.path, 8, "Row", "second")
        rows = store.list_avoided(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "second")

    def test_clear_avoided_removes_row_and_reports_true(self):
        store.set_avoided(self.path, 9, "Row")
        self.assertTrue(store.clear_avoided(self.path, 9))
        self.assertEqual(store.list_avoided(self.path), [])

    def test_clear_avoided_missing_row_reports_false(self):
        self.assertFalse(store.clear_avoided(self.path, 999))

    def test_parent_dir_created_with_mode_0700(self):
        store.set_avoided(self.path, 1, "Row")
        parent = os.path.dirname(self.path)
        mode = stat.S_IMODE(os.stat(parent).st_mode)
        self.assertEqual(mode, 0o700)


class TestNeverDeletesPreferred(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = os.path.join(self._tmpdir.name, "shared.db")
        # Seed a 'preferred' row directly, as speediance-mcp's memory.py would.
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS exercise_marks ("
            " group_id INTEGER PRIMARY KEY,"
            " mark TEXT NOT NULL CHECK (mark IN ('preferred', 'avoided')),"
            " name TEXT NOT NULL DEFAULT '',"
            " updated_at TEXT NOT NULL,"
            " reason TEXT NOT NULL DEFAULT ''"
            ")"
        )
        conn.execute(
            "INSERT INTO exercise_marks (group_id, mark, name, updated_at) "
            "VALUES (42, 'preferred', 'Loved Exercise', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        conn.close()

    def test_clear_avoided_does_not_touch_preferred_row(self):
        result = store.clear_avoided(self.path, 42)
        self.assertFalse(result)
        conn = sqlite3.connect(self.path)
        row = conn.execute("SELECT mark FROM exercise_marks WHERE group_id = 42").fetchone()
        conn.close()
        self.assertEqual(row[0], "preferred")

    def test_setting_avoided_on_preferred_row_replaces_it(self):
        store.set_avoided(self.path, 42, "Loved Exercise", "now avoided")
        conn = sqlite3.connect(self.path)
        row = conn.execute(
            "SELECT mark, reason FROM exercise_marks WHERE group_id = 42"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "avoided")
        self.assertEqual(row[1], "now avoided")

    def test_list_avoided_excludes_preferred_rows(self):
        self.assertEqual(store.list_avoided(self.path), [])
        self.assertEqual(store.avoided_ids(self.path), set())


class TestMigrationOfOldSchema(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.path = os.path.join(self._tmpdir.name, "old.db")
        # Old schema: no `reason` column at all.
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE exercise_marks ("
            " group_id INTEGER PRIMARY KEY,"
            " mark TEXT NOT NULL CHECK (mark IN ('preferred', 'avoided')),"
            " name TEXT NOT NULL DEFAULT '',"
            " updated_at TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "INSERT INTO exercise_marks (group_id, mark, name, updated_at) "
            "VALUES (7, 'avoided', 'Old Row', '2025-01-01T00:00:00Z')"
        )
        conn.commit()
        conn.close()

    def test_migration_adds_reason_column_and_existing_rows_readable(self):
        rows = store.list_avoided(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["group_id"], 7)
        self.assertEqual(rows[0]["reason"], "")

    def test_can_write_reason_after_migration(self):
        store.set_avoided(self.path, 7, "Old Row", "newly added reason")
        self.assertEqual(store.list_avoided(self.path)[0]["reason"], "newly added reason")


if __name__ == "__main__":
    unittest.main()
