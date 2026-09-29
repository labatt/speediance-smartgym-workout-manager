"""Test-suite-wide setup: arms AVOIDED_DB_PATH before any other test can touch the real,
shared ~/.config/speediance-mcp/speediance-mcp.db.

Why this file, and why this name: `python -m unittest discover -s tests` treats `tests`
itself as the top-level dir, so files inside it are imported by their bare module name —
a `tests/__init__.py` is NEVER imported in that mode (verified: 'tests' never appears in
sys.modules during discovery), so package-init-based setup silently does nothing here.
What discovery DOES guarantee is that every `test*.py` file is imported, in filename-sorted
order, before any test runs. Naming this file so it sorts first ("00" < any letter) makes
its module-level code run before any other test module — including ones that don't know
about the avoided-exercises store at all, like a pre-existing /settings or /library route
test — is ever imported.

avoided_store.db_path() honours this env var as a fallback, below an explicit
`avoided_db_path` config key and above DEFAULT_PATH. See
tests/test_avoided_store.py::TestDbPath.test_suite_env_var_is_armed_and_points_away_from_real_config_dir
for the regression guard that fails loudly if this stops being armed.

`tempfile.mkdtemp` (unlike `TemporaryDirectory`) is not cleaned up on its own, so it
would otherwise accumulate a throwaway directory on disk every run — `_avoided_test_dir`
is registered with `atexit` for removal when the process exits. See
tests/test_avoided_env_bootstrap_cleanup.py for the regression guard.
"""

import atexit
import os
import shutil
import tempfile

_avoided_test_dir = None


def _cleanup_avoided_test_dir():
    if _avoided_test_dir:
        shutil.rmtree(_avoided_test_dir, ignore_errors=True)


if not os.environ.get("AVOIDED_DB_PATH"):
    _avoided_test_dir = tempfile.mkdtemp(prefix="avoided-test-")
    os.environ["AVOIDED_DB_PATH"] = os.path.join(_avoided_test_dir, "speediance-mcp.db")
    atexit.register(_cleanup_avoided_test_dir)
