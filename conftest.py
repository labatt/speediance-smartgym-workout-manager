"""Guarantees the shared-store bootstrap runs before pytest imports any test module.

tests/test_00_avoided_env_bootstrap.py arms AVOIDED_DB_PATH so the suite never touches
the real ~/.config/speediance-mcp/speediance-mcp.db. `unittest discover` imports every
test file in filename order, so "00" sorting first is enough there. pytest gives no such
guarantee when a SINGLE file is run:

    pytest tests/test_accessories.py

imports only that file, the bootstrap never runs, db_path() falls back to DEFAULT_PATH,
and a test that posts to /settings writes the REAL store. That is not hypothetical — it
happened on 2026-09-29 and overwrote the live owned-equipment list with form values.

pytest always loads the rootdir conftest.py whatever subset is being run, so importing
the bootstrap here closes the hole. It is IMPORTED rather than reimplemented so there
stays exactly one copy of this logic, and under the bare module name discovery uses, so
both import styles share one module object (and one temp dir to clean up).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

import test_00_avoided_env_bootstrap  # noqa: E402,F401  (its module-level code arms the env var)
