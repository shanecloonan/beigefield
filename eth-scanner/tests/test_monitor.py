"""Phase F monitor fingerprinting / alert dedupe (no live RPC required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.discover.recent import DiscoveredContract, discover_recent_deployments
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


class DiscoveryVerifiedFilter(unittest.TestCase):
    def test_prefer_verified_skips_unverified_when_keys_set(self):
        fake = [
            DiscoveredContract(address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", deployed_block=10),
            DiscoveredContract(address="0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", deployed_block=9),
        ]

        def _verify(addr: str, _key: str):
            if addr.lower().startswith("0xaaaa"):
                return True, "VerifiedA"
            return False, None

        with mock.patch("eth_scanner.discover.recent._discover_via_rpc", return_value=fake), \
             mock.patch("eth_scanner.discover.recent._etherscan_verified", side_effect=_verify), \
             mock.patch("eth_scanner.discover.recent._pick_rpc", return_value="https://example.invalid"):
            rows, stats = discover_recent_deployments(
                etherscan_keys="test-key",
                prefer_verified=True,
                max_results=10,
                max_blocks=1,
            )
        self.assertTrue(stats.prefer_verified)
        self.assertTrue(stats.keys_configured)
        self.assertEqual(stats.creates_found, 2)
        self.assertEqual(stats.verified_kept, 1)
        self.assertEqual(stats.unverified_skipped, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract_name, "VerifiedA")
        self.assertEqual(rows[0].source, "etherscan-verified")

    def test_no_keys_keeps_creates_without_verified_filter(self):
        fake = [
            DiscoveredContract(address="0xcccccccccccccccccccccccccccccccccccccccc", deployed_block=5),
        ]
        with mock.patch("eth_scanner.discover.recent._discover_via_rpc", return_value=fake), \
             mock.patch("eth_scanner.discover.recent._pick_rpc", return_value="https://example.invalid"):
            rows, stats = discover_recent_deployments(
                etherscan_keys="",
                prefer_verified=None,
                max_results=10,
                max_blocks=1,
            )
        self.assertFalse(stats.prefer_verified)
        self.assertFalse(stats.keys_configured)
        self.assertEqual(len(rows), 1)
        self.assertEqual(stats.unverified_skipped, 0)


if __name__ == "__main__":
    unittest.main()
