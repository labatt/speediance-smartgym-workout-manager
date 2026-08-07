import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workout_gen as wg  # noqa: E402

# Minimal library fixtures shaped like get_library() items.
LIB = [
    {"id": 1001, "title": "Seated Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [{"muscleGroupName": "Biceps"}],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0},
    {"id": 1002, "title": "Vita Twist", "category_name": "Core", "trainingPartId2": 17,
     "mainMuscleGroupName": "Abs", "auxiliaryMuscleGroupList": [],
     "dataStatType": 6, "completionMethod": 5, "isLeftRight": 0},
    {"id": 1003, "title": "Archer Row", "category_name": "Back", "trainingPartId2": 13,
     "mainMuscleGroupName": "Lats", "auxiliaryMuscleGroupList": [],
     "dataStatType": 1, "completionMethod": 1, "isLeftRight": 1},
]


class TestTagsAndCatalog(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(wg.exercise_tags(LIB[0]), (False, False, False))
        self.assertEqual(wg.exercise_tags(LIB[1]), (True, True, False))   # Vita: level + timed
        self.assertEqual(wg.exercise_tags(LIB[2]), (False, False, True))  # unilateral

    def test_catalog_has_ids_titles_and_tags(self):
        cat = wg.compact_catalog(LIB)
        self.assertIn("[1001] Seated Row", cat)
        self.assertIn("[TIMED+LEVEL]", cat)          # Vita line
        self.assertIn("[UNILATERAL]", cat)           # Archer line
        self.assertIn("Back", cat)                   # category present


class TestSelection(unittest.TestCase):
    def test_parse_ids_from_json_array_keeps_only_known(self):
        text = 'Sure! [1001, 1002, 999999]'
        self.assertEqual(sorted(wg.parse_selected_ids(text, LIB)), [1001, 1002])

    def test_parse_ids_fallback_keyword_match(self):
        # No parseable IDs -> fall back to matching request words against titles/muscles.
        ids = wg.parse_selected_ids("no ids here", LIB, request="I want a row for my back")
        self.assertIn(1001, ids)

    def test_parse_ids_respects_limit(self):
        big = [{"id": i, "title": f"Ex{i}", "category_name": "X", "trainingPartId2": 13,
                "mainMuscleGroupName": "M", "auxiliaryMuscleGroupList": [],
                "dataStatType": 1, "completionMethod": 1, "isLeftRight": 0} for i in range(2000, 2200)]
        text = "[" + ",".join(str(i) for i in range(2000, 2200)) + "]"
        self.assertEqual(len(wg.parse_selected_ids(text, big, limit=60)), 60)


class TestGenerationPrompt(unittest.TestCase):
    def setUp(self):
        self.merged = [wg.merge_exercise(LIB[0], {"context": "Pull the handles to your torso."}),
                       wg.merge_exercise(LIB[1]),
                       wg.merge_exercise(LIB[2])]

    def test_system_prompt_states_unit_and_forbids_conversion(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        self.assertIn("LBS", p)
        self.assertIn("do not", p.lower())          # a do-not-convert instruction exists
        self.assertNotIn("KG", p.replace("LBS", ""))  # KG not prescribed when unit is LBS

    def test_system_prompt_includes_timed_and_unilateral_sections_when_relevant(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        self.assertIn("TIMED", p)
        self.assertIn("UNILATERAL", p)
        self.assertIn("OUTPUT", p.upper())          # schema section present

    def test_system_prompt_omits_sections_when_not_relevant(self):
        only_plain = [wg.merge_exercise(LIB[0])]
        p = wg.build_generation_system_prompt(only_plain, "KG")
        self.assertNotIn("[TIMED+LEVEL]", p)
        self.assertNotIn("UNILATERAL EXERCISES", p)

    def test_system_prompt_carries_description(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        self.assertIn("Pull the handles to your torso.", p)

    def test_user_prompt_has_request(self):
        u = wg.build_generation_user_prompt("30 minute back day")
        self.assertIn("30 minute back day", u)

    def test_system_prompt_requires_nonzero_weight_and_places_rm(self):
        # Regression: models returned weight:0 on RM presets because the prompt never said
        # the RM value goes in the weight field and must be > 0.
        p = wg.build_generation_system_prompt(self.merged, "LBS")
        low = p.lower()
        self.assertIn("greater than 0", low)     # weight must never be 0
        self.assertIn("rm value", low)           # where the RM number goes
        self.assertIn('"weight"', low)           # it names the weight field explicitly


class TestValidateWorkout(unittest.TestCase):
    def test_drops_unknown_ids_and_warns(self):
        obj = {"name": "W", "exercises": [
            {"id": 1001, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
            {"id": 424242, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
        ]}
        ok, cleaned, warnings = wg.validate_workout(obj, LIB)
        self.assertTrue(ok)
        self.assertEqual([e["id"] for e in cleaned["exercises"]], [1001])
        self.assertTrue(any("424242" in w for w in warnings))

    def test_drops_exercise_with_no_sets(self):
        obj = {"name": "W", "exercises": [{"id": 1001, "sets": []}]}
        ok, cleaned, warnings = wg.validate_workout(obj, LIB)
        self.assertFalse(ok)                         # nothing valid left
        self.assertEqual(cleaned["exercises"], [])

    def test_not_a_dict_is_rejected(self):
        ok, cleaned, warnings = wg.validate_workout(["nope"], LIB)
        self.assertFalse(ok)


class TestRecentPerformance(unittest.TestCase):
    def _ex(self, name, kind, sets, all_complete=True):
        return {"name": name, "kind": kind, "all_complete": all_complete, "sets": sets}

    def setUp(self):
        # Seated Row done twice (load rose 33 -> 36.5); Vita once; Leg Curl once.
        self.sessions = [
            {"date": "2026-07-11", "title": "A", "notes": {"exercises": {"Seated Row": "right"}},
             "snapshot": {"exercises": [
                 self._ex("Seated Row", "reps", [{"done": 10, "target": 10, "complete": True, "skipped": False, "load": 33}]),
             ]}},
            {"date": "2026-07-18", "title": "B", "notes": {"exercises": {"Seated Row": "easy"}},
             "snapshot": {"exercises": [
                 self._ex("Seated Row", "reps", [{"done": 10, "target": 10, "complete": True, "skipped": False, "load": 36.5}]),
                 self._ex("Standing Leg Curl", "reps", [{"done": 12, "target": 12, "complete": True, "skipped": False, "load": 15.5}]),
                 self._ex("Vita Twist", "level", [{"done": 4, "target": 4, "complete": True, "skipped": False, "load": None, "seconds": 20}]),
             ]}},
        ]
        self.p = wg.build_recent_performance(self.sessions, "LBS", 30)

    def test_header_names_window_and_unit(self):
        self.assertIn("last 30 days", self.p)
        self.assertIn("LBS", self.p)

    def test_exercise_appears_once_newest(self):
        rows = [l for l in self.p.splitlines() if l.startswith("- Seated Row")]
        self.assertEqual(len(rows), 1)           # deduped to most-recent
        self.assertIn("2026-07-18", rows[0])     # the newer date
        self.assertIn("36.5 LBS", rows[0])       # newest load, labelled

    def test_trend_up_shows_prior(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Seated Row")][0]
        self.assertIn("↑", row)
        self.assertIn("33", row)                 # prior load referenced

    def test_new_exercise_marked_new(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Standing Leg Curl")][0]
        self.assertIn("(new)", row)

    def test_carries_felt(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Seated Row")][0]
        self.assertIn("felt easy", row)

    def test_vita_timed_no_weight_unit(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Vita Twist")][0]
        self.assertIn("timed", row)
        self.assertNotIn("LBS", row)

    def test_empty_sessions_empty_string(self):
        self.assertEqual(wg.build_recent_performance([], "LBS", 30), "")

    def test_all_skipped_exercise_omitted_no_crash(self):
        s = [{"date": "2026-07-18", "title": "A", "notes": {},
              "snapshot": {"exercises": [self._ex("Bailed Row", "reps",
                  [{"done": 0, "target": 10, "complete": False, "skipped": True, "load": 40}],
                  all_complete=False)]}}]
        out = wg.build_recent_performance(s, "LBS", 30)
        self.assertNotIn("Bailed Row", out)   # omitted, and no TypeError raised


class TestProgressionBlock(unittest.TestCase):
    def setUp(self):
        self.merged = [wg.merge_exercise(LIB[0])]   # one rep-based exercise

    def test_progression_block_present_when_has_recent(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS", has_recent=True).lower()
        self.assertIn("progression", p)
        self.assertIn("felt rating outranks", p)
        self.assertIn("never output weight 0", p)

    def test_progression_block_absent_by_default(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS").lower()
        self.assertNotIn("progression —", p)

    def test_user_prompt_appends_recent_performance(self):
        u = wg.build_generation_user_prompt("back day", recent_performance="RECENT PERFORMANCE (last 30 days...)\n- Row")
        self.assertIn("RECENT PERFORMANCE", u)
        self.assertIn("- Row", u)


class TestReferenceWorkouts(unittest.TestCase):
    def setUp(self):
        self.refs = [{
            "name": "Back Day A",
            "exercises": [
                {"title": "Seated Row", "setsAndReps": "10,10,10", "weights": "40,40,40",
                 "level": "", "is_level": False, "is_timed": False},
                {"title": "Lat Pulldown", "setsAndReps": "12,10,8", "weights": "45,50,55",
                 "level": "", "is_level": False, "is_timed": False},
                {"title": "Vita Pull", "setsAndReps": "30,30,30", "weights": "0,0,0",
                 "level": "10,12,14", "is_level": True, "is_timed": True},
            ],
        }]
        self.p = wg.build_reference_workouts(self.refs, "LBS")

    def test_names_the_workout(self):
        self.assertIn("Back Day A", self.p)

    def test_uniform_sets_summarised(self):
        self.assertIn("Seated Row: 3×10 @ 40 LBS", self.p)

    def test_varying_sets_listed(self):
        self.assertIn("Lat Pulldown: 3×12/10/8 @ 45/50/55 LBS", self.p)

    def test_vita_shows_levels_seconds_no_unit(self):
        row = [l for l in self.p.splitlines() if l.startswith("- Vita Pull")][0]
        self.assertIn("30s", row)
        self.assertIn("levels 10/12/14", row)
        self.assertNotIn("LBS", row)

    def test_empty_returns_empty(self):
        self.assertEqual(wg.build_reference_workouts([], "LBS"), "")


class TestReferencePromptHooks(unittest.TestCase):
    def setUp(self):
        self.merged = [wg.merge_exercise(LIB[0])]

    def test_system_prompt_refs_note_when_has_refs(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS", has_refs=True).lower()
        self.assertIn("reference workout", p)

    def test_system_prompt_no_refs_note_by_default(self):
        p = wg.build_generation_system_prompt(self.merged, "LBS").lower()
        self.assertNotIn("reference workouts are provided", p)

    def test_user_prompt_includes_references_and_recent(self):
        u = wg.build_generation_user_prompt("back day", references="REFERENCE WORKOUTS...\n- Row",
                                            recent_performance="RECENT PERFORMANCE...\n- Curl")
        self.assertIn("REFERENCE WORKOUTS", u)
        self.assertIn("RECENT PERFORMANCE", u)
        self.assertIn("back day", u)


class TestRefinementPrompt(unittest.TestCase):
    def setUp(self):
        self.cur = {"name": "Back Day", "exercises": [
            {"id": 1001, "presetId": -1, "sets": [{"reps": 10, "weight": 40, "mode": 1, "rest": 60}]},
        ]}

    def test_frames_as_edit_and_returns_full(self):
        p = wg.build_refinement_user_prompt(self.cur, "add a set to the row", [])
        low = p.lower()
        self.assertIn("edit of an existing workout", low)
        self.assertIn("add a set to the row", p)
        self.assertIn("full updated workout", low)

    def test_includes_current_workout_json(self):
        p = wg.build_refinement_user_prompt(self.cur, "heavier", [])
        self.assertIn("1001", p)          # the current workout's exercise id appears
        self.assertIn("Back Day", p)

    def test_includes_full_comment_log(self):
        p = wg.build_refinement_user_prompt(self.cur, "now add abs", ["make it harder", "swap squat for hinge"])
        self.assertIn("make it harder", p)
        self.assertIn("swap squat for hinge", p)
        self.assertIn("keep honoring", p.lower())

    def test_empty_log_no_section_no_crash(self):
        p = wg.build_refinement_user_prompt(self.cur, "lighter", None)
        self.assertNotIn("KEEP honoring", p)
        self.assertIn("lighter", p)

    def test_preserves_structure_fields(self):
        p = wg.build_refinement_user_prompt(self.cur, "heavier", [])
        self.assertIn("isUnilateralExpanded", p)


if __name__ == "__main__":
    unittest.main()
