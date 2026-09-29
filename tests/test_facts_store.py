"""Coaching-memory page: reading the shared curated fact store, and archiving.

The MCP server owns this table; these tests run against a temp DB, never the real one.
"""
import os, sqlite3, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import facts_store  # noqa: E402
import app as app_module  # noqa: E402

DDL = """
CREATE TABLE curated_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, kind TEXT NOT NULL,
  severity TEXT, category TEXT NOT NULL, scope TEXT,
  supersedes_json TEXT NOT NULL DEFAULT '[]', superseded_by INTEGER,
  source TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT,
  archived_at TEXT, legacy INTEGER NOT NULL DEFAULT 0, legacy_id INTEGER UNIQUE);
"""


def insert(conn, **kw):
    row = {"text": "a fact", "kind": "observation", "severity": None, "category": "note",
           "scope": None, "supersedes_json": "[]", "superseded_by": None, "source": "user",
           "created_at": "2026-09-01T00:00:00Z", "expires_at": None, "archived_at": None, "legacy": 0}
    row.update(kw)
    conn.execute(
        "INSERT INTO curated_facts (text,kind,severity,category,scope,supersedes_json,"
        "superseded_by,source,created_at,expires_at,archived_at,legacy) "
        "VALUES (:text,:kind,:severity,:category,:scope,:supersedes_json,:superseded_by,"
        ":source,:created_at,:expires_at,:archived_at,:legacy)", row)


class TestListFacts(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(DDL)
        self.addCleanup(self.conn.close)

    def commit(self):
        self.conn.commit()

    def test_facts_are_grouped_by_kind_and_severity(self):
        insert(self.conn, text="no flat bench", kind="constraint", severity="hard", category="injury")
        insert(self.conn, text="prefers barbell", kind="constraint", severity="soft", category="note")
        insert(self.conn, text="likes rows", kind="preference")
        insert(self.conn, text="lose 20lb", kind="goal")
        self.commit()
        got = facts_store.list_facts(path=self.path)
        self.assertEqual([f["text"] for f in got["hard"]], ["no flat bench"])
        self.assertEqual([f["text"] for f in got["soft"]], ["prefers barbell"])
        self.assertEqual([f["text"] for f in got["preferences"]], ["likes rows"])
        self.assertEqual([f["text"] for f in got["goals"]], ["lose 20lb"])

    def test_archived_superseded_and_expired_facts_leave_the_default_read(self):
        insert(self.conn, text="live")
        insert(self.conn, text="explicitly archived", archived_at="2026-09-02T00:00:00Z")
        insert(self.conn, text="superseded", superseded_by=1)
        insert(self.conn, text="expired", expires_at="2020-01-01T00:00:00Z")
        self.commit()
        got = facts_store.list_facts(path=self.path)
        self.assertEqual([f["text"] for f in got["observations"]], ["live"])
        self.assertEqual(got["activeTotal"], 1)
        self.assertEqual(got["total"], 4)
        reasons = sorted(f["archivedReason"] for f in got["archived"])
        self.assertEqual(reasons, ["archived", "expired", "superseded by #1"])

    def test_include_archived_shows_them_in_their_groups(self):
        insert(self.conn, text="gone", archived_at="2026-09-02T00:00:00Z")
        self.commit()
        got = facts_store.list_facts(path=self.path, include_archived=True)
        self.assertEqual([f["text"] for f in got["observations"]], ["gone"])

    def test_legacy_facts_are_called_out_separately_while_still_active(self):
        insert(self.conn, text="old note", legacy=1)
        self.commit()
        got = facts_store.list_facts(path=self.path)
        self.assertEqual(got["legacyTotal"], 1)
        self.assertEqual([f["text"] for f in got["legacy"]], ["old note"])

    def test_only_the_newest_observations_are_returned_newest_first(self):
        for n in range(facts_store.RECENT_OBSERVATIONS + 3):
            insert(self.conn, text=f"obs {n}")
        self.commit()
        rows = facts_store.list_facts(path=self.path)["observations"]
        self.assertEqual(len(rows), facts_store.RECENT_OBSERVATIONS)
        self.assertEqual(rows[0]["text"], "obs 12")

    def test_a_missing_table_reads_as_empty_rather_than_exploding(self):
        fd, empty = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(empty) and os.remove(empty))
        self.assertEqual(facts_store.list_facts(path=empty)["total"], 0)


class TestArchive(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        conn = sqlite3.connect(self.path)
        conn.execute(DDL)
        insert(conn, text="live one")
        conn.commit(); conn.close()

    def test_archiving_removes_it_from_the_default_read(self):
        self.assertTrue(facts_store.archive_fact(1, path=self.path))
        self.assertEqual(facts_store.list_facts(path=self.path)["activeTotal"], 0)

    def test_archiving_twice_reports_nothing_to_do(self):
        facts_store.archive_fact(1, path=self.path)
        self.assertFalse(facts_store.archive_fact(1, path=self.path))

    def test_an_unknown_id_reports_false(self):
        self.assertFalse(facts_store.archive_fact(999, path=self.path))


class TestMemoryPage(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_page_renders(self):
        with mock.patch.object(app_module.facts_store, 'list_facts',
                               return_value={**facts_store._empty(), "total": 0}):
            resp = self.client.get('/memory')
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Coaching memory", resp.get_data(as_text=True))

    def test_a_broken_store_warns_instead_of_500ing(self):
        with mock.patch.object(app_module.facts_store, 'list_facts', side_effect=RuntimeError("locked")):
            resp = self.client.get('/memory')
        self.assertEqual(resp.status_code, 200)
        self.assertIn("busy or unavailable", resp.get_data(as_text=True))

    def test_archive_failure_never_500s(self):
        with mock.patch.object(app_module.facts_store, 'archive_fact', side_effect=RuntimeError("locked")):
            resp = self.client.post('/memory/archive', data={'id': '1'}, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)


if __name__ == "__main__":
    unittest.main()
