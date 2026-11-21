"""Latest-heat staleness requeue. No network."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.desk.stale_rescan import apply_stale, plan_stale
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import Target

ADDR = "0x" + "ab" * 20
NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)


class StaleRescan(unittest.TestCase):
    def test_latest_heat_and_peak_drive_the_queue(self):
        planned = plan_stale([
            {"address": ADDR, "heat": 9, "status": "done", "created_at": "2026-01-01T00:00:00Z"},
            {"address": ADDR, "heat": 2, "status": "done", "created_at": "2026-10-01T00:00:00Z"},
        ], now=NOW)
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0]["heat"], 2)
        self.assertEqual(planned[0]["peak_heat"], 9)

    def test_a_fresh_scan_and_a_drained_row_stay_out(self):
        fresh = "2026-11-20T00:00:00Z"
        planned = plan_stale([
            {"address": ADDR, "heat": 8, "status": "done", "created_at": fresh},
            {
                "address": "0x" + "cd" * 20,
                "heat": 12,
                "status": "done",
                "created_at": "2026-01-01T00:00:00Z",
                "heat_breakdown": {"liveness": {"status": "dead"}},
            },
        ], now=NOW)
        self.assertEqual(planned, [])

    def test_apply_marks_the_target_pending(self):
        store = MemoryStore()
        store.upsert_target(Target(address=ADDR, status="done"))
        done = apply_stale(store, [ADDR])
        self.assertEqual(done, [ADDR])
        self.assertEqual(store.get_target(ADDR)["status"], "pending")
        store.targets[ADDR]["status"] = "running"
        self.assertEqual(apply_stale(store, [ADDR]), [])


if __name__ == "__main__":
    unittest.main()
