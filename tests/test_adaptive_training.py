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


if __name__ == "__main__":
    unittest.main(verbosity=2)
