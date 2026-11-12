"""Phase F monitor fingerprinting / alert dedupe (no live RPC required)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import Settings
from eth_scanner.discover.recent import DiscoveredContract, discover_recent_deployments
from eth_scanner.ingest.etherscan import KeyRotator
from eth_scanner.lane_a.worker import claim_and_drain
from eth_scanner.monitor.watch import MonitorAlert, _fp
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import FunnelResult, Target


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


class ParallelDrain(unittest.TestCase):
    def test_claim_and_drain_empties_pending_with_workers(self):
        store = MemoryStore()
        addrs = ["0x%040x" % (i + 1) for i in range(12)]
        for a in addrs:
            store.upsert_target(Target(address=a, status="pending", has_code=True, deployed_block=100))

        settings = Settings(dry_run=True, etherscan_api_keys=[], eth_rpc_url="", worker_id="test-drain")
        fake = FunnelResult(
            bucket="lane-a-cool", dropped=True, drop_reason="unit", heat=0,
            src_confidence="low", ir_confidence="low",
        )

        with mock.patch("eth_scanner.lane_a.worker.run_one", return_value=fake), \
             mock.patch("eth_scanner.lane_a.worker.open_store", return_value=store):
            out = claim_and_drain(
                max_scans=1000,
                workers=4,
                deadline_monotonic=time.monotonic() + 30,
                settings=settings,
                store=store,
                batch_size=4,
            )
        self.assertEqual(len(out), 12)
        pending = [r for r in store.list_targets(limit=50) if r.get("status") == "pending"]
        self.assertEqual(pending, [])

    def test_claim_and_drain_respects_deadline(self):
        store = MemoryStore()
        for i in range(20):
            store.upsert_target(Target(
                address="0x%040x" % (i + 1),
                status="pending",
                has_code=True,
                deployed_block=200 - i,
            ))
        settings = Settings(dry_run=True, etherscan_api_keys=[], eth_rpc_url="", worker_id="test-deadline")
        fake = FunnelResult(
            bucket="lane-a-cool", dropped=True, drop_reason="unit", heat=0,
            src_confidence="low", ir_confidence="low",
        )

        def _slow(*_a, **_k):
            time.sleep(0.15)
            return fake

        # Hard deadline hits mid-drain: first batch may start, later batches stop.
        with mock.patch("eth_scanner.lane_a.worker.run_one", side_effect=_slow), \
             mock.patch("eth_scanner.lane_a.worker.open_store", return_value=store):
            out = claim_and_drain(
                max_scans=1000,
                workers=2,
                deadline_monotonic=time.monotonic() + 0.35,
                settings=settings,
                store=store,
                batch_size=4,
            )
        self.assertGreater(len(out), 0)
        self.assertLess(len(out), 20)

    def test_key_rotator_thread_safe_spacing(self):
        rotator = KeyRotator(keys=["k1"], min_interval_s=0.05)
        got: list[float] = []
        lock = threading.Lock()

        def _grab():
            rotator.acquire()
            with lock:
                got.append(time.monotonic())

        threads = [threading.Thread(target=_grab) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(got), 5)
        ordered = sorted(got)
        for a, b in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(b - a, 0.04)


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
