"""Per-block rowing telemetry: the pure derivation and the route that serves it.

Fixtures are synthetic but shaped like the real payload — a sample every few seconds
carrying stroke rate, pace, watts and the target band the workout is asking for.
"""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rowing_stats import derive_rowing_blocks  # noqa: E402
import app as app_module  # noqa: E402


def sample(time, spm, pace=None, power=None, band=(20, 24, 2, 3)):
    lo_spm, hi_spm, lo_res, hi_res = band
    return {"time": time, "spm": spm, "pace": pace, "power": power, "resistance": lo_res,
            "minSpm": lo_spm, "maxSpm": hi_spm, "minResistance": lo_res, "maxResistance": hi_res}


GRAPH = {"pointDataList": (
    [sample(t, 0, pace=590.0, power=6) for t in (0, 3)]
    + [sample(t, 22, pace=250.0, power=180) for t in (6, 9)]
    + [sample(t, 26, pace=215.0, power=300, band=(24, 28, 3, 4)) for t in (12, 15)])}


class TestDeriveRowingBlocks(unittest.TestCase):
    def test_no_samples_is_reported_unavailable(self):
        for payload in (None, {}, {"pointDataList": []}, {"pointDataList": [None, "x"]}):
            got = derive_rowing_blocks(payload)
            self.assertFalse(got["available"], payload)
            self.assertIn("no samples", got["reason"])

    def test_blocks_split_where_the_target_band_changes(self):
        got = derive_rowing_blocks(GRAPH)
        self.assertTrue(got["available"])
        self.assertEqual(got["sampleSeconds"], 3)
        self.assertEqual([b["targetStrokeRate"] for b in got["blocks"]], ["20-24", "24-28"])
        self.assertEqual([b["targetResistance"] for b in got["blocks"]], ["2-3", "3-4"])
        second = got["blocks"][1]
        self.assertEqual((second["startSec"], second["endSec"], second["seconds"]), (12, 18, 6))

    def test_non_stroking_samples_are_rest_and_never_skew_the_rates(self):
        # The spm-0 samples are the flywheel spinning up; their coasting pace would
        # otherwise report a speed never actually rowed.
        got = derive_rowing_blocks(GRAPH)
        self.assertEqual((got["workingSec"], got["restingSec"]), (12, 6))
        self.assertEqual(got["avgPace500"], 232.5)
        self.assertEqual(got["bestPace500"], 215.0)     # fastest = smallest
        self.assertEqual(got["avgStrokeRate"], 24.0)
        self.assertEqual(got["maxWatts"], 300)

    def test_in_target_percent_counts_only_stroking_samples(self):
        points = [sample(0, 0, pace=500.0), sample(3, 22, pace=250.0), sample(6, 23, pace=250.0),
                  sample(9, 21, pace=250.0), sample(12, 30, pace=220.0)]
        block = derive_rowing_blocks({"pointDataList": points})["blocks"][0]
        self.assertEqual(block["inTargetPercent"], 75.0)

    def test_an_unknown_target_band_is_not_reported_as_zero_percent(self):
        points = [{"time": 0, "spm": 22, "pace": 250.0, "power": 100},
                  {"time": 3, "spm": 23, "pace": 248.0, "power": 110}]
        block = derive_rowing_blocks({"pointDataList": points})["blocks"][0]
        self.assertIsNone(block["inTargetPercent"])
        self.assertIsNone(block["targetStrokeRate"])
        self.assertEqual(block["avgStrokeRate"], 22.5)

    def test_samples_are_sorted_by_time(self):
        points = [sample(6, 22, pace=250.0), sample(0, 20, pace=260.0), sample(3, 21, pace=255.0)]
        got = derive_rowing_blocks({"pointDataList": points})
        self.assertEqual(got["durationSec"], 9)
        self.assertEqual(got["blocks"][0]["startSec"], 0)

    def test_matches_the_mcp_twin_on_the_shared_shape(self):
        # rowing_stats and speediance-mcp's parsing.rowing_telemetry are separate
        # implementations on purpose; the keys they publish must not drift apart.
        got = derive_rowing_blocks(GRAPH)
        for key in ("available", "samples", "sampleSeconds", "durationSec", "workingSec",
                    "restingSec", "avgStrokeRate", "maxStrokeRate", "avgPace500",
                    "bestPace500", "avgWatts", "maxWatts", "blocks"):
            self.assertIn(key, got)
        for key in ("block", "startSec", "endSec", "seconds", "targetStrokeRate",
                    "targetResistance", "inTargetPercent"):
            self.assertIn(key, got["blocks"][0])


class TestRowingRoute(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def _run(self, info, graph=GRAPH):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_session_info', return_value=info), \
             mock.patch.object(app_module.client, 'get_rowing_graph', return_value=graph) as fetch:
            return self.client.get('/api/session/7001/rowing'), fetch

    def test_returns_blocks_for_a_session_with_telemetry(self):
        resp, _ = self._run({"existBoatingSkiDataGraph": True, "uuid": "row-uuid"})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["available"])
        self.assertEqual(len(body["blocks"]), 2)

    def test_fetches_by_the_sessions_own_uuid_never_a_caller_supplied_one(self):
        # The uuid comes from the account's own session summary, so a caller can't
        # point this at a session they don't own.
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'user_id': '1'}), \
             mock.patch.object(app_module.client, 'get_training_session_info',
                               return_value={"existBoatingSkiDataGraph": True, "uuid": "mine"}), \
             mock.patch.object(app_module.client, 'get_rowing_graph', return_value=GRAPH) as fetch:
            self.client.get('/api/session/7001/rowing?uuid=someone-elses')
        fetch.assert_called_once_with("mine")

    def test_a_session_without_telemetry_says_so_rather_than_fetching(self):
        resp, fetch = self._run({"existBoatingSkiDataGraph": False, "uuid": "row-uuid"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["available"])
        fetch.assert_not_called()

    def test_flagged_but_no_uuid_is_reported_not_crashed(self):
        resp, fetch = self._run({"existBoatingSkiDataGraph": True})
        self.assertFalse(resp.get_json()["available"])
        fetch.assert_not_called()

    def test_signed_out_is_401(self):
        with mock.patch.object(app_module.client, 'credentials', {}):
            self.assertEqual(self.client.get('/api/session/7001/rowing').status_code, 401)


if __name__ == "__main__":
    unittest.main()
