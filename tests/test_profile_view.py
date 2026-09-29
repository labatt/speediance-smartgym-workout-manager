"""Read-only profile mirror in Settings."""
import os, sys, unittest, datetime
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from profile_view import profile_summary, _age  # noqa: E402
import app as app_module  # noqa: E402

PROFILE = {"sex": 0, "weight": 295.0, "height": "6'2\"", "birthday": "1971-08-03 16:00:00",
           "weightUnit": 0, "lengthUnit": 1, "isWatch": 2, "unit": 1,
           "email": "athlete@example.com", "isSoftwareLoggedIn": 1, "isHardwareLoggedIn": 0}
TODAY = datetime.date(2026, 9, 29)


def value(summary, label):
    return next((r["value"] for r in summary["rows"] if r["label"] == label), None)


class TestProfileSummary(unittest.TestCase):
    def test_unit_comes_from_config_not_the_unreliable_weightUnit(self):
        # weightUnit is 0 here even though the account is imperial — trusting it
        # would label every weight kg.
        imperial = profile_summary(PROFILE, unit=1, today=TODAY)
        self.assertEqual(value(imperial, "Unit system"), "Imperial (lbs)")
        self.assertEqual(value(imperial, "Bodyweight"), "295 lbs")
        metric = profile_summary(PROFILE, unit=0, today=TODAY)
        self.assertEqual(value(metric, "Unit system"), "Metric (kg)")
        self.assertEqual(value(metric, "Bodyweight"), "295 kg")

    def test_birthday_carries_the_age(self):
        self.assertEqual(value(profile_summary(PROFILE, 1, TODAY), "Birthday"), "1971-08-03 (55)")

    def test_age_handles_a_birthday_later_this_year(self):
        self.assertEqual(_age("1971-12-25", TODAY), 54)
        self.assertIsNone(_age("not-a-date"))
        self.assertIsNone(_age(None))

    def test_sex_and_watch_are_named(self):
        summary = profile_summary(PROFILE, 1, TODAY)
        self.assertEqual(value(summary, "Sex"), "Male")
        self.assertEqual(value(summary, "Watch"), "Paired")
        self.assertEqual(value(profile_summary({"isWatch": 0}, 1, TODAY), "Watch"), "None paired")

    def test_missing_fields_are_omitted_rather_than_shown_blank(self):
        summary = profile_summary({}, unit=1, today=TODAY)
        self.assertEqual([r["label"] for r in summary["rows"]], ["Unit system"])

    def test_session_flags_are_exposed(self):
        summary = profile_summary(PROFILE, 1, TODAY)
        self.assertTrue(summary["signedInPhone"])
        self.assertFalse(summary["signedInMachine"])

    def test_none_profile_is_safe(self):
        self.assertEqual(len(profile_summary(None, 1, TODAY)["rows"]), 1)


class TestSettingsPage(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def _get(self, profile_side_effect):
        creds = {'token': 't', 'user_id': '1', 'unit': 1, 'owned_accessories': []}
        with mock.patch.object(app_module.client, 'credentials', creds), \
             mock.patch.object(app_module.client, 'get_accessories', return_value=[]), \
             mock.patch.object(app_module.client, 'get_profile', side_effect=profile_side_effect), \
             mock.patch.object(app_module, '_avoided_list_safe', return_value=[]), \
             mock.patch.object(app_module.wellness, 'is_connected', return_value=False):
            return self.client.get('/settings')

    def test_profile_is_rendered(self):
        html = self._get(lambda: PROFILE).get_data(as_text=True)
        self.assertIn("Speediance account", html)
        self.assertIn("Imperial (lbs)", html)
        self.assertIn("295 lbs", html)

    def test_a_failing_profile_never_takes_settings_down(self):
        resp = self._get(lambda: (_ for _ in ()).throw(RuntimeError("profile exploded")))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Speediance account", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
