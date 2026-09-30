"""The off-machine table is declared in TWO projects. They must not drift apart.

This app's offmachine_store.py and the MCP server's memory.py both declare
`offmachine_sets` in the SAME SQLite file. Whichever process opens the file first creates
the table, and the other silently accepts whatever is already there — so a column added
on one side only would not fail loudly. It would fail as an sqlite error in production,
on whichever process happened to open second, or worse: a NOT NULL column missing its
value on one write path.

So this compares the two declarations directly. The MCP lives in a separate repo and the
MCP must work standalone, so the test SKIPS when its source isn't on this machine rather
than failing — it is a drift alarm where both are present, not a dependency.
"""

import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import offmachine_store  # noqa: E402
import session_stats_store  # noqa: E402

MCP_CANDIDATES = (
    "/srv/speediance-mcp/src/speediance_mcp/memory.py",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "speediance-mcp", "src", "speediance_mcp", "memory.py"),
)


def _create_table(sql_text, table):
    """The CREATE TABLE body for `table`, whitespace- and comment-normalised."""
    match = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);",
                      sql_text, re.DOTALL)
    if not match:
        return None
    body = match.group(1)
    body = re.sub(r"--[^\n]*", "", body)          # strip SQL comments
    body = re.sub(r"\s+", " ", body).strip()      # collapse whitespace
    return body


class SharedSchemaTest(unittest.TestCase):
    def _mcp_source(self):
        for path in MCP_CANDIDATES:
            if os.path.isfile(path):
                with open(path) as handle:
                    return handle.read()
        return None

    def test_both_projects_declare_the_same_offmachine_table(self):
        mcp_source = self._mcp_source()
        if mcp_source is None:
            self.skipTest("speediance-mcp source not present on this machine")
        ours = _create_table(offmachine_store._DDL, "offmachine_sets")
        theirs = _create_table(mcp_source, "offmachine_sets")
        self.assertIsNotNone(ours, "this app's DDL no longer declares offmachine_sets")
        self.assertIsNotNone(theirs, "the MCP's SCHEMA no longer declares offmachine_sets")
        self.assertEqual(ours, theirs,
                         "offmachine_sets has drifted between the web app and the MCP server. "
                         "They share one SQLite file, so both declarations must match exactly — "
                         "change them together.")

    def test_both_projects_declare_the_same_session_stats_tables(self):
        """The personal-best cache is shared too, and drifts the same way if untended."""
        mcp_source = self._mcp_source()
        if mcp_source is None:
            self.skipTest("speediance-mcp source not present on this machine")
        for table in ("session_exercise_stats", "session_stats_scanned"):
            with self.subTest(table=table):
                ours = _create_table(session_stats_store._DDL, table)
                theirs = _create_table(mcp_source, table)
                self.assertIsNotNone(ours, f"the web app no longer declares {table}")
                self.assertIsNotNone(theirs, f"the MCP no longer declares {table}")
                self.assertEqual(ours, theirs,
                                 f"{table} has drifted between the web app and the MCP server. "
                                 "They share one SQLite file, so both declarations must match "
                                 "exactly — change them together.")

    def test_the_side_vocabulary_matches_too(self):
        """Both sides map 'left'/'right'/'both' to the machine's own leftRight codes."""
        mcp_source = self._mcp_source()
        if mcp_source is None:
            self.skipTest("speediance-mcp source not present on this machine")
        match = re.search(r"OFFMACHINE_SIDE_CODES = (\{[^}]*\})", mcp_source)
        self.assertIsNotNone(match, "the MCP no longer defines OFFMACHINE_SIDE_CODES")
        # literal_eval, not eval: this parses a dict out of another project's SOURCE FILE,
        # and nothing read from a file should be executed to be understood.
        self.assertEqual(ast.literal_eval(match.group(1)), offmachine_store.SIDE_CODES)


if __name__ == "__main__":
    unittest.main()
