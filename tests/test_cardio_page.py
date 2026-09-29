"""Cardio page shaping: heart-rate zones and today's health cards."""
import os, sys, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cardio_page import (  # noqa: E402
    _fmt_duration, heart_rate_zones, recovery_cards, sleep_summary, today_cards,
)
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


# A wearable-equipped account. The account this was written against has none, so the
# populated path can only be covered by a fixture — and it is the path most users hit.
RECOVERY = {"recoveryScoreResp": {"value": 72, "recoveryScoreAvg": 68},
            "nightHrvResp": {"nightHrv": 41.5, "nightHrvAvg": 39},
            "nightRestingHeartRateResp": {"nightRestHeartRate": 54, "nightRestHeartRateAvg": 56},
            "sleepResp": {"value": 81, "sleepScoreAvg": 77}}
# Shape taken from a real response: `sleep` is SECONDS, `targetSleepMin` is MINUTES.
SLEEP = {"sleep": 6480.0, "sleepScore": 39, "targetSleepMin": 432, "sleepQualityScore": 30,
         "sleepRegularityScore": 3, "secondaryMetric": {"deepSleepDuration": 1800}}


class TestRecoveryCards(unittest.TestCase):
    def test_a_populated_account_gets_every_card(self):
        cards = recovery_cards(RECOVERY)
        self.assertEqual([c["label"] for c in cards],
                         ["Recovery", "Night HRV", "Night resting HR", "Sleep score"])
        self.assertEqual(cards[1]["value"], "41.5 ms")
        self.assertEqual(cards[2]["hint"], "56 bpm average")

    def test_an_empty_account_gets_nothing_rather_than_dashes(self):
        self.assertEqual(recovery_cards({}), [])
        self.assertEqual(recovery_cards({"recoveryScoreResp": {}, "nightHrvResp": {}}), [])
        self.assertEqual(recovery_cards(None), [])

    def test_an_unrecognised_field_is_surfaced_not_dropped(self):
        # Only the empty shape could be observed live, so a key we guessed wrong must
        # still show the user their number.
        cards = recovery_cards({"nightHrvResp": {"someNewKey": 44}})
        self.assertEqual(cards, [{"label": "Night HRV: someNewKey", "value": "44", "hint": None}])

    def test_a_missing_average_just_omits_the_hint(self):
        self.assertIsNone(recovery_cards({"recoveryScoreResp": {"value": 60}})[0]["hint"])


class TestSleepSummary(unittest.TestCase):
    def test_duration_against_target_respects_the_mixed_units(self):
        # `sleep` is seconds and `targetSleepMin` is minutes. Reading both the same
        # way reported 1h 48m of sleep as 108 hours.
        got = sleep_summary(SLEEP)
        self.assertTrue(got["available"])
        self.assertEqual((got["slept"], got["target"]), ("1h 48m", "7h 12m"))
        self.assertFalse(got["metTarget"])
        self.assertIn("Sleep score", [s["label"] for s in got["scores"]])
        self.assertIn("Deep sleep", [s["label"] for s in got["scores"]])

    def test_meeting_the_target_is_flagged(self):
        self.assertTrue(sleep_summary({"sleep": 8 * 3600, "targetSleepMin": 432})["metTarget"])
        self.assertFalse(sleep_summary({"sleep": 6 * 3600, "targetSleepMin": 432})["metTarget"])

    def test_a_target_with_no_sleep_logged_is_not_available(self):
        self.assertFalse(sleep_summary({"sleep": 0, "targetSleepMin": 432})["available"])
        self.assertFalse(sleep_summary({})["available"])


class TestCardioRoute(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_page_renders_zones_and_cards(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value=ZONES), \
             mock.patch.object(app_module.client, 'get_health_score', return_value=SCORE), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}), \
             mock.patch.object(app_module.client, 'get_recovery', return_value={}), \
             mock.patch.object(app_module.client, 'get_sleep', return_value={}):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertIn("Heart-rate zones", html)
        self.assertIn("3,309", html)
        self.assertIn("97-108 bpm", html)

    def test_it_explains_what_appears_rather_than_showing_empty_cards(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value={}), \
             mock.patch.object(app_module.client, 'get_health_score', return_value={}), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}), \
             mock.patch.object(app_module.client, 'get_recovery', return_value={}), \
             mock.patch.object(app_module.client, 'get_sleep', return_value={}):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertIn("What shows up here", html)
        self.assertIn("No heart rate has been recorded yet", html)

    def test_a_failure_warns_instead_of_500ing(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', side_effect=RuntimeError("boom")):
            resp = self.client.get('/cardio')
        self.assertEqual(resp.status_code, 200)
        # Jinja escapes the apostrophe, so match the part that survives.
        self.assertIn("return cardio data just now", resp.get_data(as_text=True))

    def test_a_wearable_account_sees_recovery_and_sleep(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value=ZONES), \
             mock.patch.object(app_module.client, 'get_health_score', return_value=SCORE), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}), \
             mock.patch.object(app_module.client, 'get_recovery', return_value=RECOVERY), \
             mock.patch.object(app_module.client, 'get_sleep', return_value=SLEEP):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertIn(">Overnight recovery</h2>", html)
        self.assertIn("41.5 ms", html)
        self.assertIn("1h 48m", html)
        self.assertNotIn("Nothing is wrong with your setup", html)

    def test_an_empty_account_is_told_why_rather_than_shown_blanks(self):
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value=ZONES), \
             mock.patch.object(app_module.client, 'get_health_score', return_value=SCORE), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}), \
             mock.patch.object(app_module.client, 'get_recovery', return_value={}), \
             mock.patch.object(app_module.client, 'get_sleep', return_value={}):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertNotIn(">Overnight recovery</h2>", html)
        self.assertIn("Nothing is wrong with your setup", html)

    def test_recovery_walks_back_until_it_finds_data(self):
        # Overnight data can lag several days; a two-day window read as "no data at all".
        seen = []
        def by_date(stamp):
            seen.append(stamp)
            return RECOVERY if len(seen) > 1 else {}
        with mock.patch.object(app_module.client, 'credentials', {'token': 't', 'unit': 1}), \
             mock.patch.object(app_module.client, 'get_heart_rate_zones', return_value=ZONES), \
             mock.patch.object(app_module.client, 'get_health_score', return_value={}), \
             mock.patch.object(app_module.client, 'get_profile', return_value={}), \
             mock.patch.object(app_module.client, 'get_recovery', side_effect=by_date), \
             mock.patch.object(app_module.client, 'get_sleep', return_value={}):
            html = self.client.get('/cardio').get_data(as_text=True)
        self.assertEqual(len(seen), 2)
        self.assertIn(">Overnight recovery</h2>", html)

    def test_signed_out_redirects(self):
        with mock.patch.object(app_module.client, 'credentials', {}):
            self.assertEqual(self.client.get('/cardio').status_code, 302)


if __name__ == "__main__":
    unittest.main()
