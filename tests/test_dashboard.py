"""Dashboard derivations."""
import datetime, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dashboard import (  # noqa: E402
    muscle_recovery, personal_records, streak, week_comparison,
)

TODAY = datetime.date(2026, 9, 29)
NOW = datetime.datetime(2026, 9, 29, 12, 0, 0)


def session(day, *, volume=1000, seconds=3000, calories=400, part=11, health=False, hour=9):
    rec = {"startTime": f"{day} {hour:02d}:00:00", "totalCapacity": volume,
           "trainingTime": seconds, "calorie": calories, "trainingPartId2": part}
    if health:
        rec["belongUserHealth"] = True
    return rec


class TestStreak(unittest.TestCase):
    def test_counts_back_from_today(self):
        rows = [session("2026-09-29"), session("2026-09-28"), session("2026-09-27")]
        self.assertEqual(streak(rows, TODAY), 3)

    def test_an_untrained_today_does_not_break_it(self):
        # The day isn't over; counting from yesterday is the honest reading.
        rows = [session("2026-09-28"), session("2026-09-27")]
        self.assertEqual(streak(rows, TODAY), 2)

    def test_a_gap_ends_it(self):
        rows = [session("2026-09-28"), session("2026-09-26")]
        self.assertEqual(streak(rows, TODAY), 1)

    def test_a_walk_is_not_a_training_day(self):
        rows = [session("2026-09-28", health=True), session("2026-09-27")]
        self.assertEqual(streak(rows, TODAY), 0)

    def test_no_sessions(self):
        self.assertEqual(streak([], TODAY), 0)


class TestWeekComparison(unittest.TestCase):
    def test_deltas_against_the_previous_seven_days(self):
        rows = [session("2026-09-28", volume=1000), session("2026-09-27", volume=1000),
                session("2026-09-20", volume=1000)]
        got = week_comparison(rows, TODAY)
        self.assertEqual(got["sessions"], 2)
        self.assertEqual(got["volume"], 2000)
        self.assertEqual(got["sessionsDelta"], 100)   # 2 vs 1

    def test_no_baseline_returns_none_not_zero(self):
        # "Last week was empty" is not "no change"; 0% would be a lie.
        got = week_comparison([session("2026-09-28")], TODAY)
        self.assertIsNone(got["sessionsDelta"])
        self.assertIsNone(got["volumeDelta"])

    def test_phone_health_is_excluded_from_volume(self):
        rows = [session("2026-09-28", volume=500), session("2026-09-28", volume=9999, health=True)]
        self.assertEqual(week_comparison(rows, TODAY)["volume"], 500)


class TestMuscleRecovery(unittest.TestCase):
    def test_hours_left_come_from_when_the_part_was_trained_and_its_fatigue(self):
        # Fatigue 3 holds a part out 72h; trained 12h ago leaves 60.
        trained = {13: datetime.datetime(2026, 9, 29, 0, 0)}
        got = muscle_recovery([{"trainingPartId2": 13, "fatigue": 3}], trained, NOW)
        self.assertEqual(got["recovering"][0]["bodyPart"], "Back")
        self.assertEqual(got["recovering"][0]["hoursLeft"], 60)

    def test_a_part_trained_long_ago_counts_as_ready(self):
        trained = {13: datetime.datetime(2026, 9, 20, 9, 0)}
        got = muscle_recovery([{"trainingPartId2": 13, "fatigue": 3}], trained, NOW)
        self.assertEqual(got["recovering"], [])
        self.assertEqual(got["readyPercent"], 100)
        self.assertEqual(got["verdict"], "Ready to train")

    def test_an_empty_map_must_not_silently_report_everything_ready(self):
        # History records carry no body part, so an early version always passed an empty
        # map here and the card read "100% ready" regardless of training.
        got = muscle_recovery([{"trainingPartId2": 15, "fatigue": 2}], {}, NOW)
        self.assertEqual(got["readyPercent"], 100)
        self.assertTrue(got["available"])

    def test_ready_percent_and_verdict_scale_with_how_much_is_out(self):
        trained = {p: datetime.datetime(2026, 9, 29, 6, 0) for p in (11, 12, 13)}
        fatigue = [{"trainingPartId2": p, "fatigue": 3} for p in (11, 12, 13)] + \
                  [{"trainingPartId2": 15, "fatigue": 1}]
        got = muscle_recovery(fatigue, trained, NOW)
        self.assertEqual(got["readyPercent"], 25)
        self.assertEqual(got["verdict"], "Mostly recovering")

    def test_string_keys_from_json_are_accepted(self):
        trained = {"13": datetime.datetime(2026, 9, 29, 0, 0)}
        got = muscle_recovery([{"trainingPartId2": 13, "fatigue": 3}], trained, NOW)
        self.assertEqual(got["recovering"][0]["hoursLeft"], 60)

    def test_no_fatigue_data_is_reported_unavailable(self):
        self.assertFalse(muscle_recovery([], {}, NOW)["available"])
        self.assertFalse(muscle_recovery(None, {}, NOW)["available"])


class TestPersonalRecords(unittest.TestCase):
    def stats(self, rows):
        return {"Barbell Row": rows}

    def test_a_recent_best_carries_the_number_and_what_it_beat(self):
        rows = [{"date": "2026-09-01", "maxWeight": 50, "totalCapacity": 900},
                {"date": "2026-09-28", "maxWeight": 60, "totalCapacity": 1200}]
        got = personal_records(self.stats(rows), today=TODAY)
        self.assertEqual(got[0]["exercise"], "Barbell Row")
        self.assertEqual(sorted(k["kind"] for k in got[0]["kinds"]),
                         ["Best day volume", "Heaviest weight"])
        weight = next(k for k in got[0]["kinds"] if k["kind"] == "Heaviest weight")
        # The number is what makes it a record, and the previous best is what makes it mean
        # something — reporting one without the other says nothing.
        self.assertEqual((weight["value"], weight["previous"]), (60.0, 50.0))
        self.assertEqual((weight["gain"], weight["gainPercent"]), (10.0, 20))
        self.assertEqual(got[0]["daysAgo"], 1)

    def test_the_latest_day_that_reached_the_best_is_reported(self):
        # Repeating a best is today's news, not a callback to the first time.
        rows = [{"date": "2026-09-01", "maxWeight": 60, "totalCapacity": 100},
                {"date": "2026-09-20", "maxWeight": 55, "totalCapacity": 100},
                {"date": "2026-09-28", "maxWeight": 65, "totalCapacity": 100}]
        got = personal_records(self.stats(rows), today=TODAY)
        weight = next(k for k in got[0]["kinds"] if k["kind"] == "Heaviest weight")
        self.assertEqual(weight["date"], "2026-09-28")
        self.assertEqual(weight["previous"], 60.0)

    def test_matching_an_older_best_is_not_a_record(self):
        # Equalling a previous best is not beating it.
        rows = [{"date": "2026-09-01", "maxWeight": 60, "totalCapacity": 100},
                {"date": "2026-09-28", "maxWeight": 60, "totalCapacity": 100}]
        self.assertEqual(personal_records(self.stats(rows), today=TODAY), [])

    def test_a_first_ever_best_has_no_previous(self):
        rows = [{"date": "2026-09-27", "maxWeight": 0, "totalCapacity": 500},
                {"date": "2026-09-28", "maxWeight": 40, "totalCapacity": 400}]
        got = personal_records(self.stats(rows), today=TODAY)
        weight = next(k for k in got[0]["kinds"] if k["kind"] == "Heaviest weight")
        self.assertIsNone(weight["previous"])
        self.assertIsNone(weight["gain"])

    def test_an_old_best_is_not_news(self):
        rows = [{"date": "2026-01-01", "maxWeight": 50, "totalCapacity": 900},
                {"date": "2026-02-01", "maxWeight": 60, "totalCapacity": 1200}]
        self.assertEqual(personal_records(self.stats(rows), today=TODAY), [])

    def test_a_first_ever_entry_is_not_a_record(self):
        rows = [{"date": "2026-09-28", "maxWeight": 60, "totalCapacity": 1200}]
        self.assertEqual(personal_records(self.stats(rows), today=TODAY), [])

    def test_the_stats_feeds_dayStr_key_is_accepted(self):
        # userActionStatPage keys its rows `dayStr`, not `date`; missing that silently
        # produced no records at all.
        rows = [{"dayStr": "2026-09-01", "maxWeight": 50, "totalCapacity": 900},
                {"dayStr": "2026-09-28", "maxWeight": 60, "totalCapacity": 1200}]
        got = personal_records(self.stats(rows), today=TODAY)
        self.assertEqual(got[0]["daysAgo"], 1)

    def test_unparseable_dates_are_skipped_not_fatal(self):
        rows = [{"date": "n/a", "maxWeight": 60}, {"date": "2026-09-28", "maxWeight": 70,
                                                   "totalCapacity": 10}]
        self.assertEqual(personal_records(self.stats(rows), today=TODAY), [])


if __name__ == "__main__":
    unittest.main()
