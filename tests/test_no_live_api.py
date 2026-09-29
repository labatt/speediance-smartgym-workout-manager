"""Regression guard: the suite must not be able to reach the live Speediance API.

A test run once signed the app out and cleared its remembered sign-in by calling
the real account, getting a 401, and hitting the logout path with a stubbed
credentials dict. This fails loudly instead.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api_client  # noqa: E402
from conftest import LiveApiCallBlocked  # noqa: E402


class TestNoLiveApi(unittest.TestCase):
    def test_the_network_is_blocked_during_tests(self):
        client = api_client.SpeedianceClient()
        with self.assertRaises(LiveApiCallBlocked) as caught:
            client._request('GET', 'https://api2.speediance.com/api/app/userinfo/info')
        self.assertIn("reach the network", str(caught.exception))

    def test_a_route_helper_cannot_slip_through(self):
        # get_profile wraps _request, so it must be blocked too rather than
        # silently swallowing the error and returning {}.
        client = api_client.SpeedianceClient()
        with self.assertRaises(LiveApiCallBlocked):
            client.get_profile()


if __name__ == "__main__":
    unittest.main()
