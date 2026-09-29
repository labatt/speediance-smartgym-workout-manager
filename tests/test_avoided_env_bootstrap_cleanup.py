"""Fix round 2, item 4: tests/test_00_avoided_env_bootstrap.py creates a throwaway temp
directory (tempfile.mkdtemp, which — unlike TemporaryDirectory — is NOT cleaned up on
its own) to hold the whole suite's AVOIDED_DB_PATH sqlite file. It must register an
atexit cleanup so that directory doesn't accumulate on disk across runs.

This file's name sorts after test_00_avoided_env_bootstrap.py, so by the time it runs
the bootstrap module's module-level code has already executed in this process.
"""

import importlib
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bootstrap_module():
    """The bootstrap module, however it landed in sys.modules in this process (discovery
    imports it by its bare name; a dotted `tests.` import used elsewhere would use a
    different key) — importing it fresh if neither is present yet is idempotent, since
    Python caches by module name and its guard (`if not os.environ.get(...)`) is a no-op
    on a second import once AVOIDED_DB_PATH is already set."""
    for name in ("test_00_avoided_env_bootstrap", "tests.test_00_avoided_env_bootstrap"):
        mod = sys.modules.get(name)
        if mod is not None:
            return mod
    return importlib.import_module("tests.test_00_avoided_env_bootstrap")


class TestBootstrapTempDirCleanup(unittest.TestCase):
    def setUp(self):
        self.bootstrap = _bootstrap_module()
        self.addCleanup(self._restore_dir_if_missing)

    def _restore_dir_if_missing(self):
        # avoided_store._connect() would recreate this on its own next use (it makedirs
        # any missing parent), but restore it explicitly anyway so this test never
        # leaves the suite's shared AVOIDED_DB_PATH directory missing for anything that
        # runs after it.
        d = self.bootstrap._avoided_test_dir
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

    def test_bootstrap_created_a_real_temp_dir(self):
        self.assertTrue(self.bootstrap._avoided_test_dir)
        self.assertTrue(os.path.isdir(self.bootstrap._avoided_test_dir))

    def test_cleanup_function_is_registered_with_atexit(self):
        # Python 3.12's atexit module exposes no public/private way to enumerate
        # registered callbacks (no more `_exithandlers`; only `register`/`_ncallbacks`),
        # so registration is verified structurally: the module's own source calls
        # atexit.register(...) with this exact function, rather than just defining it
        # and never wiring it up.
        src = inspect.getsource(self.bootstrap)
        self.assertIn("atexit.register(_cleanup_avoided_test_dir)", src)

    def test_cleanup_function_removes_the_temp_dir(self):
        target = self.bootstrap._avoided_test_dir
        self.assertTrue(os.path.isdir(target))
        self.bootstrap._cleanup_avoided_test_dir()
        self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
