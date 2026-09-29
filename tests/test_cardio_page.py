"""Cardio page shaping: heart-rate zones and today's health cards."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cardio_page import _fmt_duration, heart_rate_zones, today_cards  # noqa: E402
import app as app_module  # noqa: E402

ZONES = {"watchType": 2, "maxHeartRate": 112, "minHeartRate": 67,
         "timeLevelList": [
             {"timeLevel": 2489.0, "levelRateMax": 96, "levelRateDisplay": "<=96"},
             {"timeLevel": 1385.0, "levelRateMin": 97, "levelRateMax": 108, "levelRateDisplay": "97-108"},
             {"timeLevel": 55.0, "levelRateMin": 109, "levelRateMax": 128, "levelRateDisplay": "109-128"},
             {"timeLevel": 0.0, "levelRateMin": 129, "levelRateMax": 162, "levelRateDisplay": "129-162"},
             {"timeLevel": 0.0, "levelRateMin": 163, "levelRateDisplay": ">=163"}]}

SCORE = {"walking": {"value": 3309.0}, "nutrition": {"value": 2450},
         "bodyAge": {"extData": '{"date":"2026-09-27","bodyAgeStatus":2,"age":55.2}'},
         "wellnessMonitor": {"value": 1, "extData": '{"totalCount":4,"status":1}'}}


class TestDuration(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(_fmt_duration(0), "0m")
        self.assertEqual(_fmt_duration(30), "30s")
        self.assertEqual(_fmt_duration(120), "2m")
        self.assertEqual(_fmt_duration(3929), "1h 5m")
        self.assertEqual(_fmt_duration(None), "0m")


class TestHeartRateZones(unittest.TestCase):
    def test_shares_sum_over_recorded_time(self):
        got = heart_rate_zones(ZONES)
        self.assertTrue(got["available"])
        self.assertEqual(got["totalSeconds"], 3929)
        self.assertEqual(got["totalDuration"], "1h 5m")
        self.assertAlmostEqual(sum(z["percent"] for z in got["zones"]), 100.0, places=0)
        self.assertEqual(got["zones"][0]["percent"], 63.3)

    def test_empty_zones_are_kept_so_the_numbering_stays_honest(self):
        # Dropping unreached zones would renumber the ones above them.
        got = heart_rate_zones(ZONES)
        self.assertEqual([z["zone"] for z in got["zones"]], [1, 2, 3, 4, 5])
        self.assertEqual(got["zones"][4]["duration"], "0m")
        self.assertEqual(got["zones"][4]["percent"], 0.0)

    def test_range_falls_back_when_no_display_string(self):
        got = heart_rate_zones({"timeLevelList": [{"timeLevel": 10, "levelRateMin": 90, "levelRateMax": 100}]})
        self.assertEqual(got["zones"][0]["range"], "90-100")

    def test_no_recorded_time_is_reported_unavailable(self):
        for payload in (None, {}, {"timeLevelList": []},
                        {"timeLevelList": [{"timeLevel": 0, "levelRateDisplay": "x"}]}):
            self.assertFalse(heart_rate_zones(payload)["available"], payload)

    def test_watch_flag_and_extremes_are_passed_through(self):
        got = heart_rate_zones(ZONES)
        self.assertTrue(got["watchPaired"])
        self.assertEqual((got["maxHeartRate"], got["minHeartRate"]), (112, 67))


class TestTodayCards(unittest.TestCase):
    def labels(self, cards):
        return [c["label"] for c in cards]

    def test_renders_the_cards_that_have_numbers(self):
        cards = today_cards(SCORE, actual_age=55)
        self.assertEqual(self.labels(cards), ["Steps today", "Nutrition", "Body age", "Wellness alerts"])
        self.assertEqual(cards[0]["value"], "3,309")
        self.assertEqual(cards[3]["value"], "4")

    def test_body_age_is_compared_against_the_real_age(self):
        self.assertEqual(today_cards(SCORE, actual_age=55)[2]["hint"], "same as your age")
        self.assertEqual(today_cards(SCORE, actual_age=50)[2]["hint"], "5.2 years older than you")
        self.assertEqual(today_cards(SCORE, actual_age=60)[2]["hint"], "4.8 years younger than you")
        self.assertIsNone(today_cards(SCORE)[2]["hint"])

    def test_cards_without_a_value_are_omitted_not_blank(self):
        # The entire point of the page is to not show placeholders for absent data.
        self.assertEqual(today_cards({}), [])
        self.assertEqual(self.labels(today_cards({"walking": {"value": 10}})), ["Steps today"])

    def test_corrupt_extdata_does_not_raise(self):
        cards = today_cards({"bodyAge": {"extData": "not json"}, "wellnessMonitor": {"extData": "["}})
        self.assertEqual(cards, [])


class TestCardioRoute(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_page_renders_zones_and_cards(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value=ZONES), \
             mock.patch.object(app_module.client, 'get_health_score', return_value=SCORE), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertIn("Heart-rate zones", html)
        self.assertIn("3,309", html)
        self.assertIn("97-108 bpm", html)

    def test_it_says_why_vo2max_is_absent_rather_than_showing_an_empty_card(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value={}), \
             mock.patch.object(app_module.client, 'get_health_score', return_value={}), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertIn("What isn't here, and why", html)
        self.assertIn("No heart rate has been recorded yet", html)

    def test_a_failure_warns_instead_of_500ing(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', side_effect=RuntimeError("boom")):
            resp = self.client.get('/cardio')
        self.assertEqual(resp.status_code, 200)
        # Jinja escapes the apostrophe, so match the part that survives.
        self.assertIn("return cardio data just now", resp.get_data(as_text=True))

    def test_signed_out_redirects(self):
        with mock.patch.object(app_module.client, 'credentials', {}):
            self.assertEqual(self.client.get('/cardio').status_code, 302)


if __name__ == "__main__":
    unittest.main()
