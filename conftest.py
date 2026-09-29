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


# ---------------------------------------------------------------------------
# No test may reach the live Speediance API.
#
# On 2026-09-29 a new route's tests left two of its client calls unmocked. Those
# calls hit the real account, came back unauthorised, and the route's error path
# called client.logout(). Because the test had patched client.credentials to a
# stub dict, logout() then rewrote config.json from that stub — clearing the live
# token AND the remembered sign-in. The app was signed out, on disk, by a test run.
#
# The SQLite store already has this protection (AVOIDED_DB_PATH, above). The HTTP
# client did not. A test that needs API data mocks the specific client method it
# uses; anything that slips through now fails loudly instead of touching the
# account.
import pytest


class LiveApiCallBlocked(BaseException):
    """Deliberately NOT an Exception.

    Every client method wraps _request in `except Exception` and returns a default,
    which is precisely why the original damage was silent: the blocked call would be
    swallowed and the test would pass while still having reached the network. A
    BaseException passes straight through those handlers.
    """


@pytest.fixture(autouse=True)
def _no_live_api_calls(request):
    """Block the real network, not the client's own plumbing.

    Guarding SpeedianceClient._request was too blunt: tests that exercise the retry
    and header logic inject a fake session and never reach the network. requests'
    Session.request is the actual boundary, so a test with a mocked session or a
    mocked client method passes untouched, while anything that would really leave
    the machine fails loudly.
    """
    if request.node.get_closest_marker("live_api"):
        yield  # opt-in, for the e2e suite that already requires SPEEDIANCE_E2E=1
        return
    import requests

    def _blocked(self, method, url, *a, **kw):
        raise LiveApiCallBlocked(
            f"Test tried to reach the network: {method} {url}. Mock the client method "
            "it needs. Reaching the real account can sign the app out and clear its "
            "saved credentials."
        )

    original = requests.Session.request
    requests.Session.request = _blocked
    try:
        yield
    finally:
        requests.Session.request = original
