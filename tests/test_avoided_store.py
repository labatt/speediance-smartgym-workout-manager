import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import avoided_store as store  # noqa: E402


class TestDbPath(unittest.TestCase):
    def test_uses_config_key_when_present(self):
        self.assertEqual(store.db_path({"avoided_db_path": "/tmp/x.db"}), "/tmp/x.db")

    def test_falls_back_to_default_when_no_config_and_no_env_override(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("AVOIDED_DB_PATH", None)
            self.assertEqual(store.db_path({}), store.DEFAULT_PATH)
            self.assertEqual(store.db_path(None), store.DEFAULT_PATH)

    def test_env_var_overrides_default_when_no_explicit_config(self):
        with mock.patch.dict(os.environ, {"AVOIDED_DB_PATH": "/tmp/env-override.db"}):
            self.assertEqual(store.db_path({}), "/tmp/env-override.db")
            self.assertEqual(store.db_path(None), "/tmp/env-override.db")

    def test_explicit_config_wins_over_env_var(self):
        with mock.patch.dict(os.environ, {"AVOIDED_DB_PATH": "/tmp/env-override.db"}):
            self.assertEqual(
                store.db_path({"avoided_db_path": "/tmp/explicit.db"}), "/tmp/explicit.db"
            )

    def test_suite_env_var_is_armed_and_points_away_from_real_config_dir(self):
        # tests/test_00_avoided_env_bootstrap.py sets this for the whole run (it sorts
        # first among test_*.py so unittest discover imports it before any other test
        # module) — this is the regression guard: if that wiring ever breaks, this test
        # fails immediately rather than some other test silently touching the real,
        # shared DB.
        env_path = os.environ.get("AVOIDED_DB_PATH")
        self.assertTrue(env_path, "AVOIDED_DB_PATH must be set by test_00_avoided_env_bootstrap.py")
        real_dir = os.path.expanduser("~/.config/speediance-mcp")
        self.assertNotIn(real_dir, env_path)


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

    def test_migration_race_recovers_when_column_added_concurrently(self):
        """Two processes (e.g. this app's other worker and speediance-mcp) can both see the
        old schema and both try to add `reason` — the loser's ALTER raises 'duplicate column
        name'. We must recover by re-checking PRAGMA table_info rather than assume and
        re-raise blindly.

        sqlite3.Connection is a C-level immutable type (mock.patch.object can't set an
        attribute on it), so the race is simulated by wrapping the connection avoided_store
        itself opens, rather than patching the class."""
        real_connect = sqlite3.connect
        path = self.path
        state = {"raced": False}

        class RaceyConnection:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args, **kwargs):
                if not state["raced"] and "ALTER TABLE exercise_marks ADD COLUMN reason" in sql:
                    state["raced"] = True
                    # A concurrent connection wins the race and commits the column first.
                    other = real_connect(path)
                    other.execute("ALTER TABLE exercise_marks ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
                    other.commit()
                    other.close()
                    raise sqlite3.OperationalError("duplicate column name: reason")
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        def fake_connect(*args, **kwargs):
            return RaceyConnection(real_connect(*args, **kwargs))

        with mock.patch("avoided_store.sqlite3.connect", side_effect=fake_connect):
            rows = store.list_avoided(self.path)   # must not raise
        self.assertEqual(rows[0]["group_id"], 7)
        self.assertEqual(rows[0]["reason"], "")
        self.assertTrue(state["raced"])   # sanity: the race was actually exercised

    def test_migration_reraises_a_real_operational_error(self):
        """A genuine failure (not the harmless race above) must still surface — e.g. the
        column really is still missing after the exception, so swallowing it would leave
        the table broken."""
        real_connect = sqlite3.connect

        class BrokenConnection:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args, **kwargs):
                if "ALTER TABLE exercise_marks ADD COLUMN reason" in sql:
                    raise sqlite3.OperationalError("disk I/O error")
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        def fake_connect(*args, **kwargs):
            return BrokenConnection(real_connect(*args, **kwargs))

        with mock.patch("avoided_store.sqlite3.connect", side_effect=fake_connect):
            with self.assertRaises(sqlite3.OperationalError):
                store.list_avoided(self.path)


if __name__ == "__main__":
    unittest.main()
