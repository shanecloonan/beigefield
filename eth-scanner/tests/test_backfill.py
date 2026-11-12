"""Backfill cursor + funds-gate unit tests (no live RPC)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.backfill.runner import run_backfill_job
from eth_scanner.config import Settings
from eth_scanner.discover.creates import CreateChunkStats
from eth_scanner.discover.recent import DiscoveredContract as DC
from eth_scanner.ingest.funds import FundsSnapshot
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import FunnelResult


class BackfillCursor(unittest.TestCase):
    def test_memory_backfill_upsert_roundtrip(self):
        store = MemoryStore()
        row = store.upsert_backfill({
            "id": "mainnet-30d",
            "start_block": 100,
            "end_block": 200,
            "cursor_block": 99,
            "status": "running",
        })
        self.assertEqual(row["id"], "mainnet-30d")
        got = store.get_backfill("mainnet-30d")
        self.assertEqual(got["cursor_block"], 99)

    def test_noop_when_done_and_caught_up(self):
        store = MemoryStore()
        store.upsert_backfill({
            "id": "mainnet-30d",
            "start_block": 1,
            "end_block": 1000,
            "cursor_block": 5000,
            "status": "done",
            "discovered": 10,
            "funds_ge_floor": 1,
            "fully_scanned": 1,
            "heat_positive": 0,
        })
        settings = Settings(dry_run=True, etherscan_api_keys=[], eth_rpc_url="https://example.invalid")
        with mock.patch("eth_scanner.backfill.runner.head_block", return_value=1000):
            progress = run_backfill_job(settings=settings, store=store, deadline_minutes=1)
        self.assertEqual(progress.status, "noop")

    def test_chunk_advances_cursor_and_skips_below_floor(self):
        store = MemoryStore()
        settings = Settings(dry_run=True, etherscan_api_keys=[], eth_rpc_url="https://example.invalid")
        creates = [
            DC(address="0x%040x" % 1, deployed_block=1010),
            DC(address="0x%040x" % 2, deployed_block=1011),
        ]
        funds = {
            "0x%040x" % 1: FundsSnapshot(status="ok", total_usd=50.0, breakdown=[]),
            "0x%040x" % 2: FundsSnapshot(status="ok", total_usd=5000.0, breakdown=[]),
        }
        fake_fr = FunnelResult(
            bucket="lane-a-cool", dropped=True, drop_reason="unit", heat=0,
            src_confidence="low", ir_confidence="low",
        )
        with mock.patch("eth_scanner.backfill.runner.head_block", return_value=1015), \
             mock.patch("eth_scanner.backfill.runner.discover_creates_in_range", return_value=(
                 creates, CreateChunkStats(from_block=1000, to_block=1015, creates=2, source="trace_filter")
             )), \
             mock.patch("eth_scanner.backfill.runner.probe_funds_batch", return_value=funds), \
             mock.patch("eth_scanner.backfill.runner.lane_a.run_one", return_value=fake_fr), \
             mock.patch("eth_scanner.backfill.runner.open_store", return_value=store):
            # Seed cursor just before window
            store.upsert_backfill({
                "id": "mainnet-30d",
                "start_block": 1000,
                "end_block": 1015,
                "cursor_block": 999,
                "status": "running",
                "discovered": 0,
                "deduped": 0,
                "funds_ge_floor": 0,
                "funds_below_floor": 0,
                "funds_unknown": 0,
                "fully_scanned": 0,
                "heat_positive": 0,
            })
            progress = run_backfill_job(
                settings=settings,
                store=store,
                chunk_blocks=20,
                workers=2,
                deadline_minutes=5,
                max_full_scans=10,
            )
        self.assertGreaterEqual(progress.cursor_block, 1000)
        self.assertEqual(progress.funds_below_floor_this_job, 1)
        self.assertEqual(progress.funds_ge_floor_this_job, 1)
        self.assertEqual(progress.fully_scanned_this_job, 1)
        self.assertEqual(progress.source, "trace_filter")
        row = store.get_backfill("mainnet-30d")
        self.assertGreaterEqual(int(row["cursor_block"]), 1000)


class CreateDiscoveryHelpers(unittest.TestCase):
    def test_approx_blocks(self):
        from eth_scanner.discover.creates import approx_blocks_for_days
        self.assertAlmostEqual(approx_blocks_for_days(30), 216000, delta=5000)


if __name__ == "__main__":
    unittest.main()
