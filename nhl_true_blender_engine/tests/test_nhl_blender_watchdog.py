"""Do not dispatch competing or endlessly repeated Blender live jobs."""
import unittest
from datetime import datetime, timedelta, timezone
from scripts.nhl_blender_watchdog import evaluate


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,11,19,7,0,tzinfo=timezone.utc)
    def record(self, mins, status):
        return {"created_at": (self.now-timedelta(minutes=mins)).isoformat(),
                "status": status}
    def test_all_active_states_block_dispatch(self):
        for status in ("queued","pending","in_progress","requested","waiting"):
            with self.subTest(status=status):
                self.assertFalse(evaluate([self.record(80,status)],self.now)["dispatch"])
    def test_new_verified_revision_dispatches_after_old_failed_run(self):
        latest = self.record(3,"completed")
        latest["head_sha"]="old-engine"
        result=evaluate([latest],self.now,verified_sha="new-tested-engine")
        self.assertTrue(result["dispatch"])
        self.assertEqual(result["reason"],"NEW_VERIFIED_ENGINE_REVISION")

    def test_same_revision_does_not_force_second_run(self):
        latest = self.record(3,"completed")
        latest["head_sha"]="same-engine"
        self.assertFalse(evaluate([latest],self.now,verified_sha="same-engine")["dispatch"])

    def test_recent_attempt_waits(self):
        self.assertFalse(evaluate([self.record(20,"completed")],self.now)["dispatch"])
    def test_stale_attempt_dispatches(self):
        self.assertTrue(evaluate([self.record(40,"completed")],self.now)["dispatch"])
    def test_no_prior_run_dispatches(self):
        self.assertTrue(evaluate([],self.now)["dispatch"])
    def test_missing_inventory_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(None,self.now)
