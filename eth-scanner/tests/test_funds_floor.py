"""Unit tests for the live funds floor (read-only; no network in unit path)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from eth_scanner.ingest.funds import (
    DEFAULT_MIN_FUNDS_USD,
    FundsSnapshot,
    format_funds_floor_reason,
    probe_contract_funds,
)
from eth_scanner.config import Settings
from eth_scanner.lane_a.worker import run_one
from eth_scanner.store.supabase import MemoryStore


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gated_vault.sol"


class FundsFloorFormatTests(unittest.TestCase):
    def test_reason_wording(self) -> None:
        self.assertEqual(
            format_funds_floor_reason(0.0, 100.0),
            "below funds floor ($0 < $100)",
        )
        self.assertEqual(
            format_funds_floor_reason(12.5, 100.0),
            "below funds floor ($12.50 < $100)",
        )
        self.assertEqual(
            format_funds_floor_reason(12.5, 2000.0),
            "below funds floor ($12.50 < $2,000)",
        )

    def test_default_floor(self) -> None:
        self.assertEqual(DEFAULT_MIN_FUNDS_USD, 100.0)


class FundsFloorWorkerTests(unittest.TestCase):
    def test_local_fixture_skips_live_probe(self) -> None:
        settings = Settings(dry_run=True, work_dir=Path("/tmp/eth-scanner-test-funds"))
        store = MemoryStore()
        with mock.patch("eth_scanner.lane_a.worker.probe_contract_funds") as probe:
            result = run_one(
                "0x1111111111111111111111111111111111111111",
                settings=settings,
                store=store,
                source_path=FIXTURE if FIXTURE.exists() else None,
                source_text="pragma solidity ^0.8.0; contract V { function deposit() external {} }",
                tvl_usd=None,
            )
            probe.assert_not_called()
        self.assertFalse(result.dropped and (result.drop_reason or "").startswith("below funds floor"))
        self.assertTrue(any(t.stage == "funds" for t in result.stage_trace))

    def test_manual_tvl_override_skips_probe_and_keeps(self) -> None:
        settings = Settings(dry_run=True, work_dir=Path("/tmp/eth-scanner-test-funds"))
        store = MemoryStore()
        with mock.patch("eth_scanner.lane_a.worker.probe_contract_funds") as probe:
            result = run_one(
                "0x1111111111111111111111111111111111111111",
                settings=settings,
                store=store,
                source_text="pragma solidity ^0.8.0; contract V {}",
                tvl_usd=50_000.0,
            )
            probe.assert_not_called()
        self.assertEqual(result.funds_status, "override")
        self.assertFalse(result.dropped)

    def test_below_floor_drops_without_source_fetch(self) -> None:
        settings = Settings(dry_run=True, work_dir=Path("/tmp/eth-scanner-test-funds"), min_funds_usd=100.0)
        store = MemoryStore()
        snap = FundsSnapshot(
            status="ok",
            total_usd=12.0,
            breakdown=[],
            checked_at="2026-01-01T00:00:00+00:00",
            notes=[],
        )
        with mock.patch("eth_scanner.lane_a.worker.probe_contract_funds", return_value=snap):
            with mock.patch("eth_scanner.lane_a.worker._ingest") as ingest:
                result = run_one(
                    "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
                    settings=settings,
                    store=store,
                )
                ingest.assert_not_called()
        self.assertTrue(result.dropped)
        self.assertEqual(result.bucket, "lane-a-cool")
        self.assertIn("below funds floor", result.drop_reason or "")
        self.assertEqual(result.funds_usd, 12.0)
        self.assertEqual(result.funds_status, "ok")
        self.assertEqual(result.stage_trace[0].stage, "funds")
        self.assertEqual(result.stage_trace[0].decision, "drop")

    def test_unknown_funds_continues(self) -> None:
        settings = Settings(dry_run=True, work_dir=Path("/tmp/eth-scanner-test-funds"), min_funds_usd=100.0)
        store = MemoryStore()
        snap = FundsSnapshot(
            status="unknown",
            total_usd=None,
            breakdown=[],
            error="rpc down",
            notes=["funds lookup failed — continuing without a floor drop"],
        )
        from eth_scanner.types import SourceArtifact

        art = SourceArtifact(
            kind="source",
            language="solidity",
            content="pragma solidity ^0.8.0; contract V { function withdraw() external {} }",
            src_confidence="high",
            verified_match="exact",
            tool="test",
        )
        with mock.patch("eth_scanner.lane_a.worker.probe_contract_funds", return_value=snap):
            with mock.patch(
                "eth_scanner.lane_a.worker._ingest",
                return_value=(art, "0x6000", None, False, ""),
            ):
                result = run_one(
                    "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
                    settings=settings,
                    store=store,
                )
        self.assertEqual(result.funds_status, "unknown")
        self.assertFalse((result.drop_reason or "").startswith("below funds floor"))
        self.assertTrue(any("funds lookup unknown" in n or "funds lookup failed" in n for n in result.notes))


class ProbeSoftFailTests(unittest.TestCase):
    def test_all_rpcs_fail_returns_unknown(self) -> None:
        with mock.patch("eth_scanner.ingest.funds.resolve_rpc_urls", return_value=["http://127.0.0.1:9"]):
            with mock.patch("eth_scanner.ingest.funds._probe_via_rpc", side_effect=RuntimeError("boom")):
                snap = probe_contract_funds("0x0000000000000000000000000000000000000001")
        self.assertEqual(snap.status, "unknown")
        self.assertIsNone(snap.total_usd)


if __name__ == "__main__":
    unittest.main()
