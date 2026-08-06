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


if __name__ == "__main__":
    unittest.main()
