"""I-3: a broken avoided-exercises store (e.g. the shared SQLite file locked by
speediance-mcp, or genuinely corrupted) must never break /settings, /library, or the AI
generate/refine routes. Every avoided_store.list_avoided()/avoided_ids() call in app.py
must be wrapped and fall back to an empty result."""

import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402

LIB = [
    {"id": 1001, "title": "Seated Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [], "category_id": "13",
     "accessories": "5", "img": "http://x/row.jpg"},
]


def _broken_list_avoided(path):
    raise sqlite3.OperationalError("database is locked")


class TestSettingsSurvivesStoreFailure(unittest.TestCase):
    def setUp(self):
        self.patches = [
            mock.patch.object(app.avoided_store, "list_avoided", side_effect=_broken_list_avoided),
            mock.patch.object(app.wellness, "is_connected", return_value=False),
            mock.patch.object(app.client, "get_accessories", return_value=[]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.c = app.app.test_client()

    def test_settings_returns_200(self):
        r = self.c.get("/settings")
        self.assertEqual(r.status_code, 200)


class TestLibrarySurvivesStoreFailure(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self.patches = [
            mock.patch.object(app.avoided_store, "list_avoided", side_effect=_broken_list_avoided),
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_accessories", return_value=[]),
            mock.patch.object(app.client, "get_categories", return_value=[]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.c = app.app.test_client()

    def tearDown(self):
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_library_returns_200(self):
        r = self.c.get("/library")
        self.assertEqual(r.status_code, 200)


class TestApiAvoidedGetSurvivesStoreFailure(unittest.TestCase):
    def setUp(self):
        self._patch = mock.patch.object(app.avoided_store, "list_avoided", side_effect=_broken_list_avoided)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.c = app.app.test_client()

    def test_get_avoided_returns_200_with_empty_list(self):
        r = self.c.get("/api/avoided")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"avoided": []})


class TestGenerateRefineSurviveStoreFailure(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self.patches = [
            mock.patch.object(app.avoided_store, "list_avoided", side_effect=_broken_list_avoided),
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_batch_details", return_value=[]),
            mock.patch.object(app.coach, "load_config", return_value={}),
            mock.patch.object(app.coach, "workout_provider", return_value="anthropic"),
            mock.patch.object(app.coach, "workout_model", return_value="claude-x"),
            mock.patch.object(app.coach, "provider_cfg", return_value={"api_key": "sk-test"}),
            mock.patch.object(app.coach, "chat_with",
                               return_value=(True, '{"name": "W", "exercises": '
                                             '[{"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}]}')),
            mock.patch.object(app, "save_workout_gen_last", return_value=None),
            mock.patch.object(app, "_gather_recent_sessions", return_value=([], False)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.c = app.app.test_client()

    def tearDown(self):
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_generate_returns_200_ok_despite_broken_store(self):
        r = self.c.post("/api/workout/generate", json={"request": "back day", "recent_days": 0})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data.get("ok"))

    def test_refine_returns_200_ok_despite_broken_store(self):
        current = {"name": "W", "exercises": [{"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}]}
        r = self.c.post("/api/workout/refine",
                        json={"current_workout": current, "comment": "add rows", "recent_days": 0})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data.get("ok"))


if __name__ == "__main__":
    unittest.main()
