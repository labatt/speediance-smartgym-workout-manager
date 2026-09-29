"""I-7: refine must not silently drop an avoided exercise the user already kept in their
current workout — it stays, with a warning explaining why — but the avoided filter still
applies to picking anything NEW."""

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
    {"id": 1003, "title": "Also Banned", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0},
]

# The model preserves the current workout's exercises (1001, 1002) as instructed, and
# does NOT try to add the other avoided one (1003) — that's the well-behaved case this
# suite targets; test_workout_avoided_filtering.py separately covers a model that
# ignores instructions and tries to sneak in an avoided id that was NOT already present.
FINAL_JSON_KEEPS_EXISTING = (
    '{"name": "W", "exercises": ['
    '{"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]}, '
    '{"id": 1002, "sets": [{"reps": 8, "weight": 30, "mode": 1, "rest": 60}]}'
    ']}'
)


class TestRefineKeepsExistingAvoided(unittest.TestCase):
    def setUp(self):
        self._tok = app.client.credentials.get("token")
        app.client.credentials["token"] = "test-token"
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = os.path.join(self._tmpdir.name, "speediance-mcp.db")
        avoided_store.set_avoided(self.db_path, 1002, "Banned Lift", "shoulder pain")
        avoided_store.set_avoided(self.db_path, 1003, "Also Banned", "knee pain")
        app.client.credentials["avoided_db_path"] = self.db_path
        self.c = app.app.test_client()

        self.captured_system_prompts = []
        self.captured_selection_prompts = []

        def fake_chat_with(provider, model, prompt, cfg, system=None, timeout=120):
            if system is not None:
                self.captured_system_prompts.append(system)
                return True, FINAL_JSON_KEEPS_EXISTING
            self.captured_selection_prompts.append(prompt)
            return True, "[1001]"   # well-behaved: doesn't try to add either avoided id

        self.patches = [
            mock.patch.object(app.client, "get_library", return_value=list(LIB)),
            mock.patch.object(app.client, "get_batch_details", return_value=[]),
            mock.patch.object(app.coach, "load_config", return_value={}),
            mock.patch.object(app.coach, "workout_provider", return_value="anthropic"),
            mock.patch.object(app.coach, "workout_model", return_value="claude-x"),
            mock.patch.object(app.coach, "provider_cfg", return_value={"api_key": "sk-test"}),
            mock.patch.object(app.coach, "chat_with", side_effect=fake_chat_with),
            mock.patch.object(app, "save_workout_gen_last", return_value=None),
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

    def _post(self, current):
        return self.c.post("/api/workout/refine", json={
            "current_workout": current, "comment": "add more back work", "recent_days": 0,
        })

    def test_kept_avoided_exercise_survives_in_output(self):
        current = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 1002, "sets": [{"reps": 8, "weight": 30, "mode": 1, "rest": 60}]},
        ]}
        r = self._post(current)
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        ids = [e["id"] for e in data["workout"]["exercises"]]
        self.assertIn(1001, ids)
        self.assertIn(1002, ids)   # kept, not silently dropped

    def test_kept_avoided_exercise_produces_explanatory_warning(self):
        current = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 1002, "sets": [{"reps": 8, "weight": 30, "mode": 1, "rest": 60}]},
        ]}
        r = self._post(current)
        data = r.get_json()
        warnings = data.get("warnings") or []
        self.assertTrue(
            any("Banned Lift" in w and "marked avoided" in w and "already in your workout" in w
                for w in warnings),
            f"expected a 'kept ... marked avoided ... already in your workout' warning, got: {warnings}",
        )

    def test_not_currently_present_avoided_gets_no_keep_warning(self):
        # 1003 ("Also Banned") is avoided but was never in the current workout, so no
        # "kept" warning should mention it — it's just excluded as normal.
        current = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 1002, "sets": [{"reps": 8, "weight": 30, "mode": 1, "rest": 60}]},
        ]}
        r = self._post(current)
        data = r.get_json()
        warnings = data.get("warnings") or []
        self.assertFalse(any("Also Banned" in w for w in warnings))

    def test_kept_exercise_name_not_in_never_include_line_but_other_avoided_still_is(self):
        current = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 1002, "sets": [{"reps": 8, "weight": 30, "mode": 1, "rest": 60}]},
        ]}
        self._post(current)
        self.assertTrue(self.captured_system_prompts)
        system = self.captured_system_prompts[-1]
        # 1002 is staying (kept) — telling the model "never include" it would contradict
        # the "preserve every exercise" instruction it's also given.
        self.assertNotIn("Banned Lift", system)
        # 1003 is genuinely excluded (never in the workout) — still flagged normally.
        self.assertIn("Also Banned", system)

    def test_selection_stage_still_excludes_both_avoided_ids_from_new_candidates(self):
        # "never ADD a new avoided one": the catalog offered for NEW picks must still
        # exclude both avoided ids, kept-in-workout or not.
        current = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 1002, "sets": [{"reps": 8, "weight": 30, "mode": 1, "rest": 60}]},
        ]}
        self._post(current)
        self.assertTrue(self.captured_selection_prompts)
        selection_prompt = self.captured_selection_prompts[0]
        self.assertNotIn("Banned Lift", selection_prompt)
        self.assertNotIn("Also Banned", selection_prompt)


if __name__ == "__main__":
    unittest.main()
