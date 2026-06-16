"""
Unit tests for api_client.py — no real API calls needed.
All HTTP calls are mocked.
"""
import json
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from api_client import SpeedianceClient, SpeedianceProtocolError


def _make_client():
    """Return a client with fake credentials so methods don't bail early."""
    client = SpeedianceClient.__new__(SpeedianceClient)
    client.credentials = {"user_id": "test_user", "token": "test_token", "region": "Global", "unit": 0, "custom_instruction": "", "device_type": 1, "allow_monster_moves": False, "owned_accessories": [], "owned_devices": []}
    client.host = "api2.speediance.com"
    client.base_url = "https://api2.speediance.com"
    client.last_debug_info = {}
    client.library_cache = None
    client.device_type = 1
    client.allow_monster_moves = False
    client.session = MagicMock()
    return client


def _mock_save_response():
    """A successful save response mock."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"code": 0, "message": "Success", "data": {"id": 999, "code": "TEST001"}}
    return resp


def _make_detail_response(group_id, variant_id, is_unilateral=False):
    """Builds a fake exercise detail response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "code": 0,
        "data": {
            "id": group_id,
            "isLeftRight": 1 if is_unilateral else 0,
            "actionLibraryList": [{"id": variant_id}]
        }
    }
    return resp


def _make_batch_response(group_ids, variant_offset=1000):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "code": 0,
        "data": [
            {
                "id": gid,
                "actionLibraryList": [{"id": gid + variant_offset}]
            }
            for gid in group_ids
        ]
    }
    return resp


def _make_api_response(body, status_code=200, request_headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = json.dumps(body)
    resp.request = MagicMock(headers=request_headers or {})
    return resp


class TestRequestFlow(unittest.TestCase):

    def test_authenticated_headers_include_app_identity(self):
        client = _make_client()

        headers = client._get_headers()

        self.assertEqual(headers['App_type'], 'SOFTWARE')
        self.assertEqual(headers['App_user_id'], 'test_user')
        self.assertEqual(headers['Token'], 'test_token')

    def test_calendar_protocol_error_is_raised(self):
        client = _make_client()
        headers = client._get_headers()
        client.session.request = MagicMock(return_value=_make_api_response(
            {'code': 1002, 'message': 'Invalid appid'},
            request_headers=headers,
        ))

        with self.assertRaises(SpeedianceProtocolError):
            client.get_calendar_month('2026-03')

    def test_request_retries_once_after_login_expired(self):
        client = _make_client()
        stale_headers = client._get_headers()

        def relogin():
            client.credentials['user_id'] = 'fresh_user'
            client.credentials['token'] = 'fresh_token'
            return True

        client._relogin_from_environment = MagicMock(side_effect=relogin)
        client.session.request = MagicMock(side_effect=[
            _make_api_response(
                {'code': 91, 'message': 'Login expired. Please re-login.'},
                request_headers=stale_headers,
            ),
            _make_api_response(
                {'code': 0, 'message': 'Success', 'data': [{'date': '2026-03-01'}]},
                request_headers={**stale_headers, 'App_user_id': 'fresh_user', 'Token': 'fresh_token'},
            ),
        ])

        data = client.get_calendar_month('2026-03')

        self.assertEqual(data, [{'date': '2026-03-01'}])
        second_headers = client.session.request.call_args_list[1].kwargs['headers']
        self.assertEqual(second_headers['App_user_id'], 'fresh_user')
        self.assertEqual(second_headers['Token'], 'fresh_token')
        self.assertEqual(second_headers['App_type'], 'SOFTWARE')


class TestSaveWorkoutWeights(unittest.TestCase):

    def _run_save(self, exercises, group_ids=None, unilateral_flags=None, details=None):
        """
        Runs save_workout with mocked network calls.
        Returns the JSON payload sent to the POST endpoint.
        """
        client = _make_client()

        if group_ids is None:
            group_ids = list({ex['groupId'] for ex in exercises})
        if unilateral_flags is None:
            unilateral_flags = {gid: False for gid in group_ids}

        # Mock get_batch_details
        if details is None:
            details = [
                {"id": gid, "actionLibraryList": [{"id": gid + 1000}]}
                for gid in group_ids
            ]
        client.get_batch_details = MagicMock(return_value=details)

        # Mock is_exercise_unilateral
        client.is_exercise_unilateral = MagicMock(
            side_effect=lambda gid: unilateral_flags.get(gid, False)
        )

        # Capture the POST payload
        captured = {}
        def fake_request(method, url, **kwargs):
            if method == 'POST':
                captured['payload'] = kwargs.get('json', {})
            return _mock_save_response()

        client._request = MagicMock(side_effect=fake_request)

        client.save_workout("Test Workout", exercises)
        return captured.get('payload', {})

    def _get_action(self, payload, group_id):
        for a in payload.get('actionLibraryList', []):
            if a['groupId'] == group_id:
                return a
        return None

    # ------------------------------------------------------------------
    # Weight conversion tests
    # ------------------------------------------------------------------

    def test_custom_preset_weights_field_used(self):
        """Custom preset (-1) must populate 'weights', leave counterweight2 empty."""
        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': -1,
            'sets': [{'reps': 10, 'weight': 20.0, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        payload = self._run_save(exercises)
        action = self._get_action(payload, 1)
        self.assertIsNotNone(action)
        self.assertNotEqual(action['weights'], '')
        self.assertEqual(action['counterweight2'], '')

    def test_custom_preset_weight_stored_as_is(self):
        """Custom preset (-1): weight must be stored as-is — no unit conversion.
        The Speediance API stores weights in the user's configured unit (LBS or KG).
        Python must NOT multiply or divide by 2.2.
        """
        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': -1,
            'sets': [{'reps': 10, 'weight': 20.0, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        payload = self._run_save(exercises)
        action = self._get_action(payload, 1)
        # Must be '20.0' — NOT '44.0' (which would mean a wrong ×2.2 was applied)
        self.assertEqual(action['weights'], '20.0')

    def test_custom_weight_stored_without_conversion(self):
        """3.5 (user unit) → API weight = '3.5' — stored as-is, never multiplied by 2.2."""
        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': -1,
            'sets': [{'reps': 10, 'weight': 3.5, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        payload = self._run_save(exercises)
        action = self._get_action(payload, 1)
        # Must be '3.5' — NOT '7.7' (which would mean a wrong ×2.2 was applied)
        self.assertEqual(action['weights'], '3.5')

    def test_rm_preset_uses_counterweight2(self):
        """Gain Muscle preset (1) → counterweight2 has RM values, weights has dummy '3.5'."""
        exercises = [{
            'groupId': 2,
            'variant_id': 2001,
            'preset_id': 1,
            'sets': [
                {'reps': 10, 'weight': 12, 'mode': 1, 'rest': 60, 'unit': 'reps'},
                {'reps': 8, 'weight': 13, 'mode': 1, 'rest': 60, 'unit': 'reps'},
            ]
        }]
        payload = self._run_save(exercises)
        action = self._get_action(payload, 2)
        self.assertEqual(action['weights'], '3.5,3.5')
        self.assertEqual(action['counterweight2'], '12,13')

    def test_multiple_sets_weight_csv(self):
        """Multiple sets → weights field is comma-separated, values stored as-is."""
        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': -1,
            'sets': [
                {'reps': 10, 'weight': 10.0, 'mode': 1, 'rest': 60, 'unit': 'reps'},
                {'reps': 8,  'weight': 15.0, 'mode': 1, 'rest': 60, 'unit': 'reps'},
                {'reps': 6,  'weight': 20.0, 'mode': 2, 'rest': 90, 'unit': 'reps'},
            ]
        }]
        payload = self._run_save(exercises)
        action = self._get_action(payload, 1)
        # Must be '10.0,15.0,20.0' — NOT '22.0,33.0,44.0' (wrong ×2.2 conversion)
        self.assertEqual(action['weights'], '10.0,15.0,20.0')

    # ------------------------------------------------------------------
    # Unilateral L/R tests
    # ------------------------------------------------------------------

    def test_bilateral_leftright_all_zeros(self):
        """Bilateral exercise → leftRight = '0,0,0'."""
        exercises = [{
            'groupId': 10,
            'variant_id': 10001,
            'preset_id': -1,
            'sets': [
                {'reps': 10, 'weight': 20.0, 'mode': 1, 'rest': 60, 'unit': 'reps'},
                {'reps': 10, 'weight': 20.0, 'mode': 1, 'rest': 60, 'unit': 'reps'},
                {'reps': 10, 'weight': 20.0, 'mode': 1, 'rest': 60, 'unit': 'reps'},
            ]
        }]
        payload = self._run_save(exercises, unilateral_flags={10: False})
        action = self._get_action(payload, 10)
        self.assertEqual(action['leftRight'], '0,0,0')

    def test_unilateral_leftright_alternates_1_2(self):
        """Unilateral 4 sets (L1,R1,L2,R2) → leftRight = '1,2,1,2'."""
        exercises = [{
            'groupId': 20,
            'variant_id': 20001,
            'preset_id': -1,
            'sets': [
                {'reps': 10, 'weight': 6.0, 'mode': 1, 'rest': 45, 'unit': 'reps'},
                {'reps': 10, 'weight': 6.0, 'mode': 1, 'rest': 45, 'unit': 'reps'},
                {'reps': 8,  'weight': 7.0, 'mode': 2, 'rest': 60, 'unit': 'reps'},
                {'reps': 8,  'weight': 7.0, 'mode': 2, 'rest': 60, 'unit': 'reps'},
            ]
        }]
        payload = self._run_save(exercises, unilateral_flags={20: True})
        action = self._get_action(payload, 20)
        self.assertEqual(action['leftRight'], '1,2,1,2')

    # ------------------------------------------------------------------
    # CSV field correctness
    # ------------------------------------------------------------------

    def test_reps_modes_rest_csv(self):
        """setsAndReps, sportMode, breakTime2 are built correctly."""
        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': -1,
            'sets': [
                {'reps': 10, 'weight': 20.0, 'mode': 1, 'rest': 60, 'unit': 'reps'},
                {'reps': 8,  'weight': 14.0, 'mode': 2, 'rest': 90, 'unit': 'reps'},
                {'reps': 12, 'weight': 10.0, 'mode': 3, 'rest': 45, 'unit': 'reps'},
            ]
        }]
        payload = self._run_save(exercises)
        action = self._get_action(payload, 1)
        self.assertEqual(action['setsAndReps'], '10,8,12')
        self.assertEqual(action['sportMode'], '1,2,3')
        self.assertEqual(action['breakTime2'], '60,90,45')

    def test_preset_id_stored_in_action(self):
        """templatePresetId is passed through correctly."""
        for preset_id in [-1, 1, 3, 5]:
            exercises = [{
                'groupId': 1,
                'variant_id': 1001,
                'preset_id': preset_id,
                'sets': [{'reps': 10, 'weight': 10, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
            }]
            payload = self._run_save(exercises)
            action = self._get_action(payload, 1)
            self.assertEqual(action['templatePresetId'], preset_id, f"preset_id={preset_id} not preserved")

    def test_prefers_liz_variant_when_available(self):
        """When no variant is explicit, default to Liz (coach id 31) if the exercise has her variant."""
        exercises = [{
            'groupId': 1,
            'preset_id': -1,
            'sets': [{'reps': 10, 'weight': 10, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        details = [{
            "id": 1,
            "actionLibraryList": [
                {"id": 1001, "coach": {"id": 5, "name": "Default"}},
                {"id": 1031, "coach": {"id": 31, "name": "Liz"}},
            ],
        }]
        payload = self._run_save(exercises, details=details)
        action = self._get_action(payload, 1)
        self.assertEqual(action['actionLibraryId'], 1031)

    def test_explicit_variant_id_overrides_preferred_coach(self):
        """Manual choices stay manual; Liz preference only fills unspecified variants."""
        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': -1,
            'sets': [{'reps': 10, 'weight': 10, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        details = [{
            "id": 1,
            "actionLibraryList": [
                {"id": 1001, "coach": {"id": 5, "name": "Default"}},
                {"id": 1031, "coach": {"id": 31, "name": "Liz"}},
            ],
        }]
        payload = self._run_save(exercises, details=details)
        action = self._get_action(payload, 1)
        self.assertEqual(action['actionLibraryId'], 1001)

    def test_falls_back_to_first_variant_when_liz_unavailable(self):
        """Exercises without a Liz variant keep the old first-variant behavior."""
        exercises = [{
            'groupId': 1,
            'preset_id': -1,
            'sets': [{'reps': 10, 'weight': 10, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        details = [{
            "id": 1,
            "actionLibraryList": [
                {"id": 1001, "coach": {"id": 5, "name": "Default"}},
                {"id": 1002, "coach": {"id": 6, "name": "Helga"}},
            ],
        }]
        payload = self._run_save(exercises, details=details)
        action = self._get_action(payload, 1)
        self.assertEqual(action['actionLibraryId'], 1001)


class TestImperialWeightRoundTrip(unittest.TestCase):
    """
    Regression tests for imperial (LBS) weight handling.

    Bug history:
        The Speediance API stores weights in the user's configured unit — LBS for
        imperial users, KG for metric users.  No conversion should occur in Python.

        A developer (testing only in KG/metric mode) introduced a ×2.2 multiply in
        api_client.py::save_workout, and a matching ÷2.2 in the JS save path, which
        cancelled out for KG users but broke imperial users:

          Imperial enter → JS ÷2.2 → Python ×2.2 → stored as LBS ← correct value stored
          BUT the JS import used kgToLbs (×2.2) on the returned LBS value → displayed ×2.2 too high

        Or in other configurations the multiply/divide stacked, sending the machine
        values that were 2.2× too low (e.g. 25 lbs entered → machine showed 11 lbs).

    Correct contract (verified against live machine):
        - Frontend sends weight in user's unit, no conversion.
        - Python stores it as-is (no ×2.2 or ÷2.2).
        - On import, frontend uses the value as-is (no kgToLbs call for custom exercises).
        - Machine and create.html both show the original entered value.
    """

    def _run_save(self, weight, preset_id=-1):
        """Simulate save_workout and return the API weights field for a single set."""
        from api_client import SpeedianceClient
        client = SpeedianceClient.__new__(SpeedianceClient)
        client.credentials = {
            "user_id": "u", "token": "t", "region": "Global", "unit": 1,
            "custom_instruction": "", "device_type": 1,
            "allow_monster_moves": False, "owned_accessories": [], "owned_devices": []
        }
        client.host = "api2.speediance.com"
        client.base_url = "https://api2.speediance.com"
        client.last_debug_info = {}
        client.library_cache = None
        client.device_type = 1
        client.allow_monster_moves = False
        client.session = MagicMock()
        client.get_batch_details = MagicMock(return_value=[
            {"id": 1, "actionLibraryList": [{"id": 1001}]}
        ])
        client.is_exercise_unilateral = MagicMock(return_value=False)

        captured = {}
        def fake_request(method, url, **kwargs):
            if method == 'POST':
                captured['payload'] = kwargs.get('json', {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"code": 0, "data": {"id": 1, "code": "X"}}
            return resp
        client._request = MagicMock(side_effect=fake_request)

        exercises = [{
            'groupId': 1,
            'variant_id': 1001,
            'preset_id': preset_id,
            'data_stat_type': None,
            'sets': [{'reps': 10, 'weight': weight, 'mode': 1, 'rest': 60, 'unit': 'reps'}]
        }]
        client.save_workout("Test", exercises)
        payload = captured.get('payload', {})
        actions = payload.get('actionLibraryList', [])
        return actions[0]['weights'] if actions else None

    def _simulate_import(self, stored_value, user_unit=1):
        """
        Simulate what create.html does on import for a custom exercise.
        user_unit=1 → imperial (LBS), 0 → metric (KG).
        Correct behavior: value is used as-is (no kgToLbs conversion).
        """
        val = float(stored_value)
        if user_unit == 1:
            return round(val)          # LBS: round to nearest integer
        else:
            return round(val * 2) / 2  # KG: round to nearest 0.5

    # --- Save side: Python must not convert ---

    def test_imperial_50lbs_stored_as_50(self):
        """50 LBS entered → API must receive '50.0', not '110.0' (×2.2) or '22.5' (÷2.2)."""
        result = self._run_save(50.0)
        self.assertEqual(result, '50.0',
            "REGRESSION: Python is applying a unit conversion. "
            "Weights must be stored as-is in the user's configured unit.")

    def test_imperial_25lbs_stored_as_25(self):
        """25 LBS → stored as '25.0'. Machine was showing ~11 lbs when this was wrong (÷2.2)."""
        result = self._run_save(25.0)
        self.assertEqual(result, '25.0')

    def test_imperial_100lbs_stored_as_100(self):
        """100 LBS → stored as '100.0'."""
        result = self._run_save(100.0)
        self.assertEqual(result, '100.0')

    def test_kg_user_20kg_stored_as_20(self):
        """KG user enters 20 KG → stored as '20.0' (same pass-through logic)."""
        result = self._run_save(20.0)
        self.assertEqual(result, '20.0')

    # --- Import side: no kgToLbs conversion ---

    def test_import_50_displays_as_50_lbs(self):
        """API returns 50 → imperial display = 50 LBS (no ×2.2 kgToLbs applied)."""
        displayed = self._simulate_import(50.0, user_unit=1)
        self.assertEqual(displayed, 50,
            "REGRESSION: Import is applying kgToLbs. "
            "The API already returns values in the user's unit — no conversion needed.")

    def test_import_25_displays_as_25_lbs(self):
        """API returns 25 → imperial display = 25 LBS."""
        displayed = self._simulate_import(25.0, user_unit=1)
        self.assertEqual(displayed, 25)

    def test_import_20_kg_displays_as_20(self):
        """API returns 20 → KG display = 20.0 (rounded to nearest 0.5)."""
        displayed = self._simulate_import(20.0, user_unit=0)
        self.assertEqual(displayed, 20.0)

    # --- Full round-trip ---

    def test_full_roundtrip_50lbs(self):
        """50 LBS → save → stored → import → displayed == 50 LBS."""
        stored = self._run_save(50.0)
        displayed = self._simulate_import(stored, user_unit=1)
        self.assertEqual(displayed, 50,
            "Round-trip failed: entered 50 LBS, got back a different value after save/reload.")

    def test_full_roundtrip_25lbs(self):
        """25 LBS round-trip stays 25."""
        stored = self._run_save(25.0)
        displayed = self._simulate_import(stored, user_unit=1)
        self.assertEqual(displayed, 25)

    def test_full_roundtrip_100lbs(self):
        """100 LBS round-trip stays 100."""
        stored = self._run_save(100.0)
        displayed = self._simulate_import(stored, user_unit=1)
        self.assertEqual(displayed, 100)


class TestClampStep(unittest.TestCase):
    """Tests for weight clamping/stepping logic."""

    def _clamp_step(self, val, min_w, max_w, step):
        val = max(min_w, min(max_w, val))
        return round(val / step) * step

    def test_clamp_to_min(self):
        self.assertEqual(self._clamp_step(3.0, 3.5, 100, 0.5), 3.5)

    def test_round_to_step(self):
        self.assertAlmostEqual(self._clamp_step(5.3, 3.5, 100, 0.5), 5.5)
        self.assertAlmostEqual(self._clamp_step(5.1, 3.5, 100, 0.5), 5.0)

    def test_integer_step(self):
        self.assertEqual(self._clamp_step(13, 9, 13, 1), 13)
        self.assertEqual(self._clamp_step(8, 9, 13, 1), 9)


if __name__ == '__main__':
    unittest.main(verbosity=2)
