"""The personal-best cache: deriving it, storing it, and keeping it honest.

This cache is what makes volume records all-time instead of "best in the last 30 days",
and what took the records endpoint from ~15 API calls to about one. Being a cache, its
dangerous failures are quiet ones — a stale row that keeps setting a record, a session
deleted in the app that keeps counting, numbers derived by logic since corrected. Those
are what these tests are aimed at.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import session_stats  # noqa: E402
import session_stats_store as store  # noqa: E402


def detail(name, group_id, sets):
    """A session-detail exercise. `sets` is [(reps, weight)] or [(reps, weight, side)]."""
    reps_rows = []
    for entry in sets:
        reps, weight = entry[0], entry[1]
        side = entry[2] if len(entry) > 2 else 0
        d = {"weights": [], "leftWeights": [], "rightWeights": []}
        if side == 1:
            d["leftWeights"] = [weight]
        elif side == 2:
            d["rightWeights"] = [weight]
        else:
            d["weights"] = [weight]
        reps_rows.append({"finishedCount": reps, "leftRight": side, "trainingInfoDetail": d})
    return {"actionLibraryName": name, "actionLibraryGroupId": group_id, "finishedReps": reps_rows}


class ReduceTest(unittest.TestCase):
    def test_volume_reps_sets_and_top_weight(self):
        out = session_stats.reduce_exercises([detail("Row", 321, [(10, 40), (8, 45)])])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0], {"name": "Row", "groupId": 321, "volume": 10 * 40 + 8 * 45,
                                  "maxWeight": 45.0, "sets": 2, "reps": 18})

    def test_a_skipped_set_is_not_a_set_that_happened(self):
        out = session_stats.reduce_exercises([detail("Row", 321, [(10, 40), (0, 40)])])
        self.assertEqual((out[0]["sets"], out[0]["reps"], out[0]["volume"]), (1, 10, 400.0))

    def test_a_movement_listed_twice_in_one_session_is_combined(self):
        """Two entries would collide on (training_id, name) and silently lose the first."""
        out = session_stats.reduce_exercises([detail("Row", 321, [(10, 40)]),
                                              detail("Row", 321, [(10, 50)])])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["volume"], 900.0)
        self.assertEqual(out[0]["sets"], 2)
        self.assertEqual(out[0]["maxWeight"], 50.0)

    def test_a_unilateral_set_is_not_doubled_and_two_cables_sum(self):
        one_arm = session_stats.reduce_exercises([detail("Single Arm Row", 600, [(10, 40, 1)])])
        self.assertEqual(one_arm[0]["volume"], 400.0)
        barbell = session_stats.reduce_exercises([{
            "actionLibraryName": "Barbell RDL", "actionLibraryGroupId": 385,
            "finishedReps": [{"finishedCount": 10, "leftRight": 0, "trainingInfoDetail": {
                "weights": [50], "leftWeights": [25], "rightWeights": [25]}}]}])
        self.assertEqual(barbell[0]["maxWeight"], 50.0)

    def test_bodyweight_work_counts_as_sets_but_no_volume(self):
        out = session_stats.reduce_exercises([detail("Push-Up", None, [(20, 0)])])
        self.assertEqual((out[0]["sets"], out[0]["reps"], out[0]["volume"]), (1, 20, 0.0))


class StoreTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        os.unlink(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def put(self, training_id, day, exercises, **kw):
        return store.store_session({}, training_id, day, exercises, path=self.path, **kw)

    def test_stored_sessions_read_back_as_daily_rows(self):
        self.put(1, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 1800,
                                    "maxWeight": 45, "sets": 4, "reps": 48}])
        rows = store.daily_rows({}, path=self.path)["Row"]
        self.assertEqual(rows, [{"dayStr": "2026-09-27", "totalCapacity": 1800.0,
                                 "maxWeight": 45.0, "source": "machine"}])

    def test_two_sessions_on_one_day_sum_but_two_days_stay_apart(self):
        """The exact shape of the weekly-bucket bug, guarded on our own side."""
        self.put(1, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 1800, "maxWeight": 45}])
        self.put(2, "2026-09-28", [{"name": "Row", "groupId": 321, "volume": 1800, "maxWeight": 60}])
        self.put(3, "2026-09-28", [{"name": "Row", "groupId": 321, "volume": 200, "maxWeight": 30}])
        rows = store.daily_rows({}, path=self.path)["Row"]
        self.assertEqual([(r["dayStr"], r["totalCapacity"], r["maxWeight"]) for r in rows],
                         [("2026-09-27", 1800.0, 45.0), ("2026-09-28", 2000.0, 60.0)])

    def test_restoring_a_session_replaces_rather_than_duplicates(self):
        self.put(1, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 1800, "maxWeight": 45}])
        self.put(1, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 900, "maxWeight": 30}])
        self.assertEqual(store.daily_rows({}, path=self.path)["Row"][0]["totalCapacity"], 900.0)

    def test_a_session_with_no_exercises_is_still_marked_scanned(self):
        """Or an empty session is re-fetched on every reconcile, forever."""
        self.put(7, "2026-09-27", [], session_type=6)
        self.assertIn(7, store.scanned_ids({}, path=self.path))
        self.assertEqual(store.daily_rows({}, path=self.path), {})

    def test_a_forgotten_session_stops_counting(self):
        self.put(1, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 1800, "maxWeight": 45}])
        store.forget_sessions({}, [1], path=self.path)
        self.assertEqual(store.daily_rows({}, path=self.path), {})
        self.assertNotIn(1, store.scanned_ids({}, path=self.path))

    def test_rows_from_an_older_derivation_are_ignored_and_rescanned(self):
        """A corrected derivation must not leave the old numbers in place.

        The volume logic has real traps (two-cable sums, the `weights` telemetry field).
        If fixing one left every cached row untouched, the bug would outlive its fix.
        """
        self.put(1, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 1800, "maxWeight": 45}])
        original = store.DERIVED_VERSION
        try:
            store.DERIVED_VERSION = original + 1
            self.assertEqual(store.daily_rows({}, path=self.path), {},
                             "stale rows must not be served")
            self.assertNotIn(1, store.scanned_ids({}, path=self.path),
                             "the session must look unscanned so it is derived again")
            self.assertEqual(store.summary({}, path=self.path)["staleSessions"], 1)
        finally:
            store.DERIVED_VERSION = original

    def test_cached_days_is_bounded_by_the_window(self):
        self.put(1, "2026-09-01", [])
        self.put(2, "2026-09-27", [])
        self.assertEqual(set(store.cached_days({}, "2026-09-20", "2026-09-30", path=self.path)), {2})
        self.assertEqual(set(store.cached_days({}, path=self.path)), {1, 2})

    def test_summary_reports_what_is_held(self):
        self.put(1, "2026-09-01", [{"name": "Row", "groupId": 321, "volume": 100, "maxWeight": 10}])
        self.put(2, "2026-09-27", [{"name": "Row", "groupId": 321, "volume": 200, "maxWeight": 20}])
        got = store.summary({}, path=self.path)
        self.assertEqual((got["sessions"], got["exerciseRows"]), (2, 2))
        self.assertEqual((got["firstDay"], got["lastDay"]), ("2026-09-01", "2026-09-27"))


class PlanTest(unittest.TestCase):
    """Reconcile policy, without any I/O."""

    RECORDS = [
        {"trainingId": 1, "startTime": "2026-09-01 10:00:00", "type": 5},
        {"trainingId": 2, "startTime": "2026-09-27 10:00:00", "type": 5},
        {"trainingId": 3, "startTime": "2026-09-28 10:00:00", "type": 5},
        {"trainingId": 9, "startTime": "2026-09-28 11:00:00", "belongUserHealth": True},
    ]

    def test_only_missing_gym_sessions_are_fetched_oldest_first(self):
        plan = session_stats.plan_reconcile(self.RECORDS, cached={2})
        self.assertEqual(plan["fetch"], [1, 3], "oldest first, and never the phone-health row")
        self.assertFalse(plan["nothingMissing"])

    def test_a_full_cache_fetches_nothing(self):
        plan = session_stats.plan_reconcile(self.RECORDS, cached={1, 2, 3})
        self.assertEqual(plan["fetch"], [])
        self.assertTrue(plan["nothingMissing"])

    def test_the_fetch_budget_is_respected_and_the_rest_reported(self):
        plan = session_stats.plan_reconcile(self.RECORDS, cached=set(), max_fetch=2)
        self.assertEqual(plan["fetch"], [1, 2])
        self.assertEqual(plan["remaining"], 1)

    def test_deletes_are_only_judged_inside_the_window_asked_about(self):
        """A session outside the range is absent because it wasn't requested.

        Judging it gone would wipe the whole cache the first time anything read a narrow
        window — the most destructive plausible bug in this feature.
        """
        cached = {1: "2026-09-01", 2: "2026-09-27", 3: "2026-09-28"}
        listed = {2: "2026-09-27", 3: "2026-09-28"}
        self.assertEqual(session_stats.stale_ids(cached, listed, "2026-09-20", "2026-09-30"), [])
        self.assertEqual(session_stats.stale_ids(cached, listed, "2026-08-01", "2026-09-30"), [1])


class ReconcileTest(unittest.TestCase):
    """The loop around the policy, with a fake client and the real store."""

    class FakeClient:
        def __init__(self, records):
            self.records = records
            self.calls = 0

        def get_training_records(self, start, end):
            self.calls += 1
            return [r for r in self.records if start <= str(r["startTime"])[:10] <= end]

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        os.unlink(self.path)
        # Route the store at a temp file for the duration of the test.
        self._real_db_path = store.db_path
        store.db_path = lambda config: self.path
        self.addCleanup(setattr, store, "db_path", self._real_db_path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_a_run_caches_what_is_missing_and_a_second_run_does_nothing(self):
        client = self.FakeClient([
            {"trainingId": 1, "startTime": "2026-09-27 10:00:00", "type": 5},
            {"trainingId": 2, "startTime": "2026-09-28 10:00:00", "type": 5},
        ])
        fetched = []

        def fetch(record):
            fetched.append(record["trainingId"])
            return [detail("Row", 321, [(10, 40)])]

        first = session_stats.reconcile(client, store, {}, "2026-09-01", "2026-09-30", fetch)
        self.assertEqual((first["sessionsAdded"], first["sessionsDropped"]), (2, 0))
        self.assertTrue(first["upToDate"])
        self.assertEqual(fetched, [1, 2])

        second = session_stats.reconcile(client, store, {}, "2026-09-01", "2026-09-30", fetch)
        self.assertEqual(second["sessionsAdded"], 0, "already cached")
        self.assertEqual(fetched, [1, 2], "no session is fetched twice")

    def test_a_session_deleted_in_the_app_stops_counting(self):
        records = [{"trainingId": 1, "startTime": "2026-09-27 10:00:00", "type": 5},
                   {"trainingId": 2, "startTime": "2026-09-28 10:00:00", "type": 5}]
        client = self.FakeClient(records)
        session_stats.reconcile(client, store, {}, "2026-09-01", "2026-09-30",
                                lambda r: [detail("Row", 321, [(10, 40)])])
        self.assertEqual(len(store.daily_rows({})["Row"]), 2)

        records.pop()                                  # the user deleted it in the app
        report = session_stats.reconcile(client, store, {}, "2026-09-01", "2026-09-30",
                                         lambda r: [detail("Row", 321, [(10, 40)])])
        self.assertEqual(report["sessionsDropped"], 1)
        self.assertEqual([r["dayStr"] for r in store.daily_rows({})["Row"]], ["2026-09-27"])

    def test_one_unreadable_session_does_not_abort_the_run(self):
        client = self.FakeClient([
            {"trainingId": 1, "startTime": "2026-09-27 10:00:00", "type": 5},
            {"trainingId": 2, "startTime": "2026-09-28 10:00:00", "type": 5},
        ])

        def fetch(record):
            if record["trainingId"] == 1:
                raise RuntimeError("403 from the course endpoint")
            return [detail("Row", 321, [(10, 40)])]

        report = session_stats.reconcile(client, store, {}, "2026-09-01", "2026-09-30", fetch)
        self.assertEqual(report["sessionsAdded"], 1)
        self.assertEqual([f["trainingId"] for f in report["failed"]], [1])
        self.assertFalse(report["upToDate"], "a failure must not read as caught up")


if __name__ == "__main__":
    unittest.main()
