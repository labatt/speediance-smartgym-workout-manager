import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schedule_planner import (  # noqa: E402
    classify_entry,
    existing_by_date,
    expand,
    plan_changes,
    slot_for,
    summarize,
)

A, B, C = "codeA", "codeB", "codeC"

WEEKLY = {
    "mode": "weekly",
    "weekly": {"mon": A, "tue": B, "wed": C, "thu": A, "fri": B, "sat": C, "sun": None},
}

CYCLE = {
    "mode": "cycle",
    "cycle": {"anchor": "2026-07-13", "sequence": [A, B, C, None]},  # Mon 13th
}


class TestWeekly(unittest.TestCase):
    def test_maps_each_weekday(self):
        # 2026-07-13 is a Monday.
        self.assertEqual(slot_for(WEEKLY, "2026-07-13"), A)
        self.assertEqual(slot_for(WEEKLY, "2026-07-14"), B)
        self.assertEqual(slot_for(WEEKLY, "2026-07-15"), C)
        self.assertEqual(slot_for(WEEKLY, "2026-07-16"), A)
        self.assertEqual(slot_for(WEEKLY, "2026-07-17"), B)
        self.assertEqual(slot_for(WEEKLY, "2026-07-18"), C)
        self.assertIsNone(slot_for(WEEKLY, "2026-07-19"))  # Sunday = rest

    def test_repeats_the_next_week(self):
        self.assertEqual(slot_for(WEEKLY, "2026-07-20"), A)  # Monday again
        self.assertEqual(slot_for(WEEKLY, "2026-09-07"), A)  # months later, still Monday

    def test_does_not_drift_when_a_day_is_missed(self):
        # Weekday mapping is absolute: skipping Wednesday does not shift Thursday.
        self.assertEqual(slot_for(WEEKLY, "2026-07-16"), A)


class TestCycle(unittest.TestCase):
    def test_walks_the_sequence_from_the_anchor(self):
        self.assertEqual(slot_for(CYCLE, "2026-07-13"), A)
        self.assertEqual(slot_for(CYCLE, "2026-07-14"), B)
        self.assertEqual(slot_for(CYCLE, "2026-07-15"), C)
        self.assertIsNone(slot_for(CYCLE, "2026-07-16"))
        self.assertEqual(slot_for(CYCLE, "2026-07-17"), A)  # wraps

    def test_drifts_across_weekdays(self):
        # A 4-day cycle means the same weekday lands on a different slot each week.
        self.assertEqual(slot_for(CYCLE, "2026-07-13"), A)   # Monday
        self.assertIsNone(slot_for(CYCLE, "2026-07-20"))     # Monday, 7 days later
        self.assertEqual(slot_for(CYCLE, "2026-07-27"), C)   # Monday again

    def test_dates_before_the_anchor_do_not_index_backwards(self):
        # (day - anchor) is negative here; % must still yield a valid slot.
        self.assertIsNone(slot_for(CYCLE, "2026-07-12"))     # -1 % 4 == 3 -> rest
        self.assertEqual(slot_for(CYCLE, "2026-07-11"), C)   # -2 % 4 == 2

    def test_empty_sequence_is_all_rest(self):
        self.assertIsNone(slot_for({"mode": "cycle", "cycle": {"anchor": "2026-07-13", "sequence": []}}, "2026-07-13"))


class TestExpand(unittest.TestCase):
    def test_inclusive_of_both_ends(self):
        days = expand(WEEKLY, "2026-07-13", "2026-07-19")
        self.assertEqual(len(days), 7)
        self.assertEqual(days[0][0], datetime.date(2026, 7, 13))
        self.assertEqual(days[-1][0], datetime.date(2026, 7, 19))


class TestClassifyEntry(unittest.TestCase):
    def test_completed_sessions_are_never_ours(self):
        # Deleting one of these would destroy real training history.
        self.assertEqual(classify_entry({"type": 3, "isFinish": 1, "code": "x"}), "completed")

    def test_system_suggestions_are_foreign(self):
        # Speediance's own "Goal-Focused Workout" rows: type 4, no code to remove them by.
        self.assertEqual(classify_entry({"type": 4, "isFinish": 0, "code": None}), "foreign")

    def test_official_courses_are_foreign(self):
        self.assertEqual(classify_entry({"type": 4, "isFinish": 0, "code": "x"}), "foreign")

    def test_our_reservation(self):
        self.assertEqual(classify_entry({"type": 3, "isFinish": 0, "code": "x"}), "reservation")

    def test_existing_by_date_keeps_only_reservations(self):
        calendar = [
            {"date": "2026-07-14", "trainingPlanList": [
                {"type": 3, "isFinish": 1, "code": "done", "title": "history"},
                {"type": 4, "isFinish": 0, "code": None, "title": "Goal-Focused"},
                {"type": 3, "isFinish": 0, "code": B, "title": "Workout B"},
            ]},
        ]
        self.assertEqual(existing_by_date(calendar), {"2026-07-14": [{"code": B, "title": "Workout B"}]})


class TestPlanChanges(unittest.TestCase):
    def test_writes_into_empty_days(self):
        changes = plan_changes(WEEKLY, "2026-07-13", "2026-07-13", {})
        self.assertEqual(changes[0]["action"], "write")
        self.assertEqual(changes[0]["wanted"], A)

    def test_noop_when_already_correct(self):
        existing = {"2026-07-13": [{"code": A, "title": "Workout A"}]}
        self.assertEqual(plan_changes(WEEKLY, "2026-07-13", "2026-07-13", existing)[0]["action"], "noop")

    def test_replaces_a_different_workout_and_reports_what_dies(self):
        existing = {"2026-07-13": [{"code": "other", "title": "Leg day"}]}
        change = plan_changes(WEEKLY, "2026-07-13", "2026-07-13", existing)[0]
        self.assertEqual(change["action"], "replace")
        self.assertEqual(change["remove"], [{"code": "other", "title": "Leg day"}])

    def test_clears_a_reservation_on_a_rest_day(self):
        existing = {"2026-07-19": [{"code": "other", "title": "Recovery ride"}]}   # Sunday
        change = plan_changes(WEEKLY, "2026-07-19", "2026-07-19", existing)[0]
        self.assertEqual(change["action"], "clear")
        self.assertEqual(change["remove"][0]["title"], "Recovery ride")

    def test_empty_rest_day_is_a_noop(self):
        self.assertEqual(plan_changes(WEEKLY, "2026-07-19", "2026-07-19", {})[0]["action"], "noop")

    def test_protect_before_blocks_changes_to_seen_days(self):
        # The automatic top-up must never reach back into days already applied.
        changes = plan_changes(WEEKLY, "2026-07-13", "2026-07-15", {}, protect_before="2026-07-14")
        self.assertEqual([c["date"] for c in changes], ["2026-07-15"])

    def test_summarize_counts_destructive_actions(self):
        existing = {
            "2026-07-13": [{"code": "other", "title": "x"}],   # replace
            "2026-07-19": [{"code": "other", "title": "y"}],   # clear (Sunday)
        }
        counts = summarize(plan_changes(WEEKLY, "2026-07-13", "2026-07-19", existing))
        self.assertEqual(counts["replace"], 1)
        self.assertEqual(counts["clear"], 1)
        self.assertEqual(counts["destructive"], 2)


if __name__ == "__main__":
    unittest.main()
