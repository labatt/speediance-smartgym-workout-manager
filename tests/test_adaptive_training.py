import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import adaptive_training as planner
from adaptive_training import (
    Movement,
    STAMINA_PRESET_ID,
    SETUP_POSITION_ORDER,
    TOBY_REPS,
    WARMUP_RM,
    WORKING_RM,
    TrainingSignals,
    build_plan,
    build_speediance_payload_exercises,
)


RAW_LIBRARY = [
    {"id": 101, "title": "Handle Row", "isCustom": 0, "isUseDevice": True,
     "accessories": "5", "mainMuscleGroupName": "Back", "outPosition": 0},
    {"id": 102, "title": "Handle Press", "isCustom": 0, "isUseDevice": True,
     "accessories": "5", "mainMuscleGroupName": "Chest", "outPosition": 0},
    {"id": 103, "title": "Bodyweight Plank", "isCustom": 0, "isUseDevice": False,
     "accessories": "", "mainMuscleGroupName": "Core", "outPosition": None},
]


class TestLoadLibraryAvoidedIds(unittest.TestCase):
    """BLACKLIST is the static, hand-edited list; avoided_ids is the caller-supplied set
    from the shared avoided-exercises store. Both must be excluded from the pool."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._cache_path = Path(self._tmp.name) / "library_cache.json"
        self._cache_path.write_text(json.dumps(RAW_LIBRARY))
        self._orig_cache = planner.LIBRARY_CACHE
        self._orig_blacklist = planner.BLACKLIST
        planner.LIBRARY_CACHE = self._cache_path
        self.addCleanup(lambda: setattr(planner, "LIBRARY_CACHE", self._orig_cache))
        self.addCleanup(lambda: setattr(planner, "BLACKLIST", self._orig_blacklist))

    def test_no_avoided_ids_keeps_backward_compatible_default(self):
        on, off = planner._load_library()
        ids = {m.group_id for m in on}
        self.assertEqual(ids, {101, 102})

    def test_avoided_ids_excluded_from_on_device_pool(self):
        on, off = planner._load_library(avoided_ids={102})
        ids = {m.group_id for m in on}
        self.assertEqual(ids, {101})

    def test_avoided_ids_combine_with_static_blacklist(self):
        planner.BLACKLIST = (101,)
        on, off = planner._load_library(avoided_ids={102})
        ids = {m.group_id for m in on}
        self.assertEqual(ids, set())

    def test_refresh_pools_accepts_avoided_ids(self):
        planner._refresh_pools(avoided_ids={101})
        ids = {m.group_id for m in planner.ON_DEVICE_POOL}
        self.assertEqual(ids, {102})

        # I-9: restore LIBRARY_CACHE/BLACKLIST BEFORE calling _refresh_pools() again, in
        # one cleanup callback, so ordering can't get scrambled against setUp's own
        # cleanups (which are LIFO-later than anything registered here, so they'd run
        # AFTER whatever we register in the test body — the opposite of what a bare
        # `addCleanup(_refresh_pools)` would need).
        def _restore_and_refresh():
            planner.LIBRARY_CACHE = self._orig_cache
            planner.BLACKLIST = self._orig_blacklist
            planner._refresh_pools()
        self.addCleanup(_restore_and_refresh)

        # Force cleanups now so this test can assert on the outcome deterministically,
        # rather than trusting real teardown timing.
        self.doCleanups()
        on_ids = {m.group_id for m in planner.ON_DEVICE_POOL}
        # Must reflect the REAL cache (restored), never this test's temp fixture (whose
        # ids are 101/102) — that fixture file is about to be deleted by setUp's own
        # TemporaryDirectory cleanup, which must not have already been read from twice.
        self.assertNotIn(101, on_ids)
        self.assertNotIn(102, on_ids)

    def test_refresh_pools_default_call_unaffected(self):
        planner._refresh_pools()
        ids = {m.group_id for m in planner.ON_DEVICE_POOL}
        self.assertEqual(ids, {101, 102})


class TestAdaptiveTrainingPlanner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        planner.TRAINING_PLANS_DIR = Path(self._tmp.name)
        planner.ON_DEVICE_POOL = [
            Movement(
                group_id=1000 + idx,
                name=f"Handle Move {idx}",
                patterns=("pull", "push", "core", "posture", "accessory"),
                implement="handles",
                setup_position=["high", "chest", "base"][idx % 3],
            )
            for idx in range(12)
        ]
        planner.OFF_SPEEDIANCE_POOL = [
            Movement(
                group_id=2000 + idx,
                name=f"Off Device Move {idx}",
                patterns=("core", "accessory"),
                implement="none",
                setup_position="floor",
                off_speediance=True,
            )
            for idx in range(3)
        ]

    def test_brutal_bjj_becomes_walk_and_rm20_recovery(self):
        plan = build_plan(TrainingSignals(
            date="2026-06-10",
            report_context="post_bjj",
            whoop_recovery=72,
            whoop_strain_so_far=15.1,
            bjj_strain=13.8,
            bjj_completed=True,
            garmin_body_battery=58,
            morning_step_target=9000,
        ))

        self.assertEqual(plan.readiness_bucket, "post_bjj_brutal")
        self.assertEqual(plan.run.mode, "walk")
        self.assertEqual(plan.run.distance_miles, 0.0)
        self.assertLessEqual(plan.step_target, 6500)
        self.assertEqual(plan.warmup_count, 10)
        self.assertEqual(plan.working_count, 0)
        self.assertTrue(all(ex.rm == WARMUP_RM for ex in plan.exercises))
        self.assertEqual(plan.implement, "handles")

    def test_build_day_uses_five_rm20_then_five_rm15(self):
        plan = build_plan(TrainingSignals(
            date="2026-06-10",
            report_context="morning",
            whoop_recovery=86,
            whoop_strain_so_far=4.0,
            bjj_strain=0.0,
            bjj_completed=False,
            garmin_body_battery=82,
            morning_step_target=8500,
        ))

        self.assertEqual(plan.readiness_bucket, "build")
        on_device = [ex for ex in plan.exercises if not ex.off_speediance]
        off_device = [ex for ex in plan.exercises if ex.off_speediance]
        self.assertEqual([ex.rm for ex in on_device[:5]], [WARMUP_RM] * 5)
        self.assertEqual([ex.rm for ex in on_device[5:]], [WORKING_RM] * 5)
        self.assertLessEqual(len(off_device), 2)
        self.assertEqual(plan.warmup_count, 5)
        self.assertEqual(plan.working_count, 5)
        self.assertEqual(len({ex.name for ex in plan.exercises}), len(plan.exercises))

    def test_run_distance_scales_to_recent_volume_and_heat(self):
        plan = build_plan(TrainingSignals(
            date="2026-06-11",
            report_context="morning",
            whoop_recovery=84,
            whoop_strain_so_far=0.0,
            bjj_strain=0.0,
            bjj_completed=False,
            garmin_body_battery=39,
            resting_hr=72,
            baseline_resting_hr=64.4,
            recent_28d_run_miles=17.78,
            recent_weekly_run_miles=4.44,
            current_week_run_miles=3.30,
            recent_long_run_miles=3.12,
            observed_max_run_hr=203,
            recent_easy_run_avg_hr=118.7,
            forecast_high_f=93,
            heat_index_f=101,
            thunderstorm_risk=True,
        ))

        self.assertEqual(plan.readiness_bucket, "build")
        self.assertEqual(plan.run.mode, "heat_limited_optional_jog")
        self.assertLessEqual(plan.run.distance_miles, 0.7)
        self.assertIn("114-130 bpm", plan.run.heart_rate_zones)
        self.assertIn("hard cap 135 bpm", plan.run.heart_rate_zones)
        self.assertIn("4.4 mi/week", plan.run.reason)

    def test_payload_uses_speediance_stamina_contract(self):
        plan = build_plan(TrainingSignals(
            date="2026-06-10",
            whoop_recovery=86,
            whoop_strain_so_far=4.0,
            garmin_body_battery=82,
        ))
        payload = build_speediance_payload_exercises(plan)
        on_device = [ex for ex in plan.exercises if not ex.off_speediance]

        self.assertEqual(len(payload), len(on_device))
        self.assertTrue(all(item["preset_id"] == STAMINA_PRESET_ID for item in payload))
        self.assertTrue(all(item["sets"][0]["reps"] == TOBY_REPS for item in payload))
        self.assertEqual(payload[0]["sets"][0]["weight"], WARMUP_RM)
        self.assertEqual(payload[-1]["sets"][0]["weight"], WORKING_RM)

    def test_workout_uses_one_implement_and_setup_order(self):
        plan = build_plan(TrainingSignals(
            date="2026-06-10",
            report_context="post_bjj",
            whoop_recovery=55,
            whoop_strain_so_far=8.0,
            garmin_body_battery=50,
            preferred_implement="handles",
        ))

        self.assertEqual(plan.implement, "handles")
        positions = [
            SETUP_POSITION_ORDER[ex.setup_position]
            for ex in plan.exercises
            if not ex.off_speediance
        ]
        self.assertEqual(positions, sorted(positions))

    def test_avoided_ids_never_appear_in_the_plan(self):
        """I-1: a plan built with avoided_ids must never contain those ids, on-device or
        off-Speediance, whichever selection path they'd otherwise have come from."""
        avoided = {1000, 1001, 1002, 2000}
        plan = build_plan(TrainingSignals(
            date="2026-06-10",
            report_context="morning",
            whoop_recovery=86,
            whoop_strain_so_far=4.0,
            bjj_strain=0.0,
            bjj_completed=False,
            garmin_body_battery=82,
            morning_step_target=8500,
        ), avoided_ids=avoided)

        plan_ids = {ex.group_id for ex in plan.exercises}
        self.assertFalse(plan_ids & avoided)
        self.assertTrue(plan_ids)   # sanity: the rest of the pool still produced a plan

    def test_avoided_ids_none_is_backward_compatible(self):
        plan_without_arg = build_plan(TrainingSignals(
            date="2026-06-10", report_context="morning", whoop_recovery=86,
            whoop_strain_so_far=4.0, bjj_strain=0.0, bjj_completed=False,
            garmin_body_battery=82, morning_step_target=8500,
        ))
        plan_with_none = build_plan(TrainingSignals(
            date="2026-06-10", report_context="morning", whoop_recovery=86,
            whoop_strain_so_far=4.0, bjj_strain=0.0, bjj_completed=False,
            garmin_body_battery=82, morning_step_target=8500,
        ), avoided_ids=None)
        self.assertEqual(
            [ex.group_id for ex in plan_without_arg.exercises],
            [ex.group_id for ex in plan_with_none.exercises],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
