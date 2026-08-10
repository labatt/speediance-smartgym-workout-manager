import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cardio_stats import derive_cardio_stats, is_cardio_record, CARDIO_COURSE_TYPES  # noqa: E402

ORACLE = {"trainingTime": 530, "calorie": 161, "totalEnergy": 29580.29,
          "totalDistance": 892.71, "completionRate": 29.0, "rpe": 6}


class TestDeriveCardioStats(unittest.TestCase):
    def test_oracle_session(self):
        r = derive_cardio_stats(ORACLE)
        self.assertEqual(r["durationSec"], 530)
        self.assertAlmostEqual(r["distanceM"], 892.71, places=2)
        self.assertAlmostEqual(r["pace500"], 296.9, delta=0.2)
        self.assertAlmostEqual(r["speedMs"], 1.68, delta=0.02)
        self.assertAlmostEqual(r["calPerMin"], 18.2, delta=0.2)
        self.assertAlmostEqual(r["energyKJ"], 29.6, delta=0.1)
        self.assertAlmostEqual(r["avgWatts"], 56, delta=1)
        self.assertIsInstance(r["avgWatts"], int)
        self.assertEqual(r["completion"], 29.0)
        self.assertEqual(r["rpe"], 6)

    def test_zero_distance_nulls_pace_and_speed(self):
        r = derive_cardio_stats({"trainingTime": 300, "totalDistance": 0, "calorie": 50})
        self.assertIsNone(r["pace500"])
        self.assertIsNone(r["speedMs"])
        self.assertAlmostEqual(r["calPerMin"], 10.0, delta=0.1)

    def test_missing_fields_are_none_never_nan(self):
        r = derive_cardio_stats({})
        for k in ("pace500", "speedMs", "calPerMin", "avgWatts", "distanceM", "rpe"):
            self.assertIsNone(r[k], f"{k} should be None on empty input")

    def test_zero_duration_nulls_rate_stats(self):
        r = derive_cardio_stats({"trainingTime": 0, "totalDistance": 100, "totalEnergy": 500})
        self.assertIsNone(r["pace500"])
        self.assertIsNone(r["calPerMin"])
        self.assertIsNone(r["avgWatts"])


class TestIsCardioRecord(unittest.TestCase):
    def test_rowing_courseType_2_is_cardio(self):
        self.assertTrue(is_cardio_record({"courseType": 2}))

    def test_strength_courseType_0_is_not(self):
        self.assertFalse(is_cardio_record({"courseType": 0}))

    def test_missing_courseType_is_not(self):
        self.assertFalse(is_cardio_record({}))

    def test_extension_point_is_a_set(self):
        self.assertIn(2, CARDIO_COURSE_TYPES)


if __name__ == "__main__":
    unittest.main()
