"""Phase F monitor fingerprinting / alert dedupe (no live RPC required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.monitor.watch import MonitorAlert, _fp
from eth_scanner.store.supabase import MemoryStore


class MonitorUnit(unittest.TestCase):
    def test_fingerprint_stable(self):
        self.assertEqual(_fp("a", 1), _fp("a", 1))
        self.assertNotEqual(_fp("a", 1), _fp("a", 2))

    def test_memory_alert_dedupe(self):
        store = MemoryStore()
        a = MonitorAlert(
            address="0x1111111111111111111111111111111111111111",
            kind="upgrade",
            fingerprint="abc",
            detail="impl changed",
        ).to_dict()
        self.assertEqual(store.save_alerts([a]), 1)
        self.assertEqual(store.save_alerts([a]), 0)
        self.assertEqual(len(store.list_alerts()), 1)


if __name__ == "__main__":
    unittest.main()
