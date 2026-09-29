"""Integration coverage: /api/workout/generate and /api/workout/refine must never hand an
avoided exercise to the model (catalog + pool_ids), must strip one back out if the model
returns it anyway, and must mention avoided names in the system prompt when any exist.
The pure filtering logic itself is unit-tested in tests/test_workout_gen.py
(drop_avoided); this file checks app.py actually wires it in.

I-2: the fake model's FINAL JSON response deliberately includes the avoided id (1002),
simulating a model that ignores the "Never include" instruction and tries to sneak it
back in. That id survives in `library` (passed to workout_gen.validate_workout) only if
drop_avoided failed to filter it — so this test is only meaningful because 1002 could
plausibly appear in the output; a fake response that never contained 1002 in the first
place (the prior version of this test) would pass whether or not drop_avoided worked at
all. Verified by temporarily replacing workout_gen.drop_avoided with an identity
function and confirming test_generate_never_returns_avoided_exercise and
test_refine_never_returns_avoided_exercise both FAIL (see fix-round-1 report)."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
import avoided_store  # noqa: E402

LIB = [
    {"id": 1001, "title": "Seated Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0},
    {"id": 1002, "title": "Banned Lift", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0},
]

# The model returns BOTH ids in its final JSON, as if it ignored the "Never include"
# instruction — the real assertion is that 1002 gets stripped anyway (because it was
# never in the filtered `library` validate_workout checks against), not that the model
# happened not to mention it.
FINAL_JSON_WITH_BOTH_IDS = (
    '{"name": "W", "exercises": ['
    '{"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}, '
    '{"id": 1002, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}'
    ']}'
)


class TestGenerateExcludesAvoided(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = os.path.join(self._tmpdir.name, "speediance-mcp.db")
        avoided_store.set_avoided(self.db_path, 1002, "Banned Lift", "shoulder pain")
        app.client.credentials["avoided_db_path"] = self.db_path
        self.c = app.app.test_client()

        self.captured_system_prompts = []
        self.captured_selection_prompts = []

        def fake_chat_with(provider, model, prompt, cfg, system=None, timeout=120):
            if system is not None:
                self.captured_system_prompts.append(system)
                return True, FINAL_JSON_WITH_BOTH_IDS
            self.captured_selection_prompts.append(prompt)
            return True, "[1001, 1002]"   # selection stage: model (wrongly) tries to pick the banned lift too

        self.patches = [
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_batch_details", return_value=[]),
            mock.patch.object(app.coach, "load_config", return_value={}),
            mock.patch.object(app.coach, "workout_provider", return_value="anthropic"),
            mock.patch.object(app.coach, "workout_model", return_value="claude-x"),
            mock.patch.object(app.coach, "provider_cfg", return_value={"api_key": "sk-test"}),
            mock.patch.object(app.coach, "chat_with", side_effect=fake_chat_with),
            mock.patch.object(app, "save_workout_gen_last", return_value=None),
            # Defense in depth: guarantee no real Speediance network call happens even if
            # recent_days handling changes later. A live login here would invalidate the
            # production app's active session (Speediance allows one session per account).
            mock.patch.object(app, "_gather_recent_sessions", return_value=([], False)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.client.credentials.pop("avoided_db_path", None)
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_generate_never_returns_avoided_exercise(self):
        # recent_days=0 keeps this test from touching _gather_recent_sessions (real API calls).
        r = self.c.post("/api/workout/generate", json={"request": "back day", "recent_days": 0})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        ids = [e["id"] for e in data["workout"]["exercises"]]
        # The model tried to include 1002 (see FINAL_JSON_WITH_BOTH_IDS) — it must be
        # stripped, and 1001 must survive (sanity: filtering isn't wiping everything).
        self.assertNotIn(1002, ids)
        self.assertIn(1001, ids)
        self.assertNotIn(1002, data["pool_ids"])

    def test_generate_system_prompt_mentions_avoided_name(self):
        self.c.post("/api/workout/generate", json={"request": "back day", "recent_days": 0})
        self.assertTrue(self.captured_system_prompts)
        system = self.captured_system_prompts[-1]
        self.assertIn("Never include these exercises", system)
        self.assertIn("Banned Lift", system)
        self.assertNotIn("[1002]", system)   # avoided exercise dropped from the catalog listing

    def test_generate_selection_stage_catalog_excludes_avoided(self):
        self.c.post("/api/workout/generate", json={"request": "back day", "recent_days": 0})
        self.assertTrue(self.captured_selection_prompts)
        selection_prompt = self.captured_selection_prompts[0]
        self.assertNotIn("Banned Lift", selection_prompt)
        self.assertNotIn("[1002]", selection_prompt)
        self.assertIn("Seated Row", selection_prompt)   # sanity: the non-avoided one is there


class TestRefineExcludesAvoided(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = os.path.join(self._tmpdir.name, "speediance-mcp.db")
        avoided_store.set_avoided(self.db_path, 1002, "Banned Lift", "shoulder pain")
        app.client.credentials["avoided_db_path"] = self.db_path
        self.c = app.app.test_client()

        self.captured_selection_prompts = []

        def fake_chat_with(provider, model, prompt, cfg, system=None, timeout=120):
            if system is not None:
                return True, FINAL_JSON_WITH_BOTH_IDS
            self.captured_selection_prompts.append(prompt)
            return True, "[1002]"

        self.patches = [
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_batch_details", return_value=[]),
            mock.patch.object(app.coach, "load_config", return_value={}),
            mock.patch.object(app.coach, "workout_provider", return_value="anthropic"),
            mock.patch.object(app.coach, "workout_model", return_value="claude-x"),
            mock.patch.object(app.coach, "provider_cfg", return_value={"api_key": "sk-test"}),
            mock.patch.object(app.coach, "chat_with", side_effect=fake_chat_with),
            mock.patch.object(app, "save_workout_gen_last", return_value=None),
            # Defense in depth: guarantee no real Speediance network call happens even if
            # recent_days handling changes later. A live login here would invalidate the
            # production app's active session (Speediance allows one session per account).
            mock.patch.object(app, "_gather_recent_sessions", return_value=([], False)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        app.client.credentials.pop("avoided_db_path", None)
        if self._tok is None:
            app.client.credentials.pop("token", None)
        else:
            app.client.credentials["token"] = self._tok

    def test_refine_never_returns_avoided_exercise(self):
        current = {"name": "W", "exercises": [{"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}]}
        # recent_days=0 keeps this test from touching _gather_recent_sessions (real API calls).
        r = self.c.post("/api/workout/refine",
                        json={"current_workout": current, "comment": "add more back work", "recent_days": 0})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        ids = [e["id"] for e in data["workout"]["exercises"]]
        self.assertNotIn(1002, ids)
        self.assertIn(1001, ids)

    def test_refine_selection_stage_catalog_excludes_avoided(self):
        current = {"name": "W", "exercises": [{"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}]}
        self.c.post("/api/workout/refine",
                    json={"current_workout": current, "comment": "add more back work", "recent_days": 0})
        self.assertTrue(self.captured_selection_prompts)
        selection_prompt = self.captured_selection_prompts[0]
        self.assertNotIn("Banned Lift", selection_prompt)
        self.assertNotIn("[1002]", selection_prompt)


if __name__ == "__main__":
    unittest.main()
