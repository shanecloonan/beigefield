"""Advanced engines: Slither leads never add heat without corroboration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.clones import match_known_bad
from eth_scanner.engines.pipeline import AdvancedEngineReport, run_advanced_engines
from eth_scanner.heat import corroborated_heat, evidence_heat
from eth_scanner.deep.runners import EngineRunResult
from eth_scanner.deep.findings import EngineFinding


class SlitherLeadNoHeat(unittest.TestCase):
    def test_slither_only_lead_adds_zero_heat(self):
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=[],
            corroborated=[
                {"lead_id": "L2-slither-reentrancy-eth-1", "confirmed": False, "method": "none", "evidence": "lead only"},
            ],
        )
        self.assertEqual(heat, 0)
        self.assertEqual(bd["corroborated_leads"], 0)
        self.assertEqual(bd["funds_in_heat"], 0)

    def test_corroborated_lead_adds_heat(self):
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=[],
            corroborated=[
                {
                    "lead_id": "L2-slither-arbitrary-send-eth-1",
                    "confirmed": True,
                    "method": "eth_call",
                    "evidence": "eth_call succeeded selector=0x40c10f19",
                },
            ],
        )
        self.assertGreater(heat, 0)
        self.assertEqual(bd["corroborated_leads"], 3)

    def test_corroborated_heat_helper(self):
        self.assertEqual(corroborated_heat([]), 0)
        self.assertEqual(corroborated_heat([{"confirmed": False}]), 0)
        self.assertEqual(corroborated_heat([{"confirmed": True}, {"confirmed": True}, {"confirmed": True}]), 6)


class CloneFingerprint(unittest.TestCase):
    def test_unprotected_initializer_marker(self):
        src = """
        pragma solidity ^0.8.0;
        contract VulnerableProxy {
            function initialize(address admin) public {
                owner = admin;
            }
            address public owner;
        }
        """
        leads = match_known_bad(source=src, contract_name="VulnerableProxy")
        ids = {l.id for l in leads}
        self.assertTrue(any("initializer" in i or "disable" in i for i in ids))


class PipelineGating(unittest.TestCase):
    def test_custody_is_engine_eligible(self):
        from eth_scanner.engines.pipeline import ENGINE_ELIGIBLE_CLASSES
        self.assertIn("custody", ENGINE_ELIGIBLE_CLASSES)
        self.assertIn("vault", ENGINE_ELIGIBLE_CLASSES)

    def test_skips_when_not_money_at_risk(self):
        report = run_advanced_engines(
            address="0x" + "11" * 20,
            source="pragma solidity ^0.8.0; contract T {}",
            contract_class="token",
            funds_usd=10_000,
            verified=True,
        )
        self.assertFalse(report.ran_slither)
        self.assertIn("not money-at-risk", " ".join(report.notes))

    def test_slither_leads_cached_and_not_auto_heat(self):
        finding = EngineFinding(
            id="slither-1",
            engine="slither",
            rule="reentrancy-eth",
            title="Slither reentrancy-eth",
            severity="high",
            confidence="medium",
            funds_class="reentrancy",
            evidence="reentrancy lead",
            generic=False,
        )
        fake = EngineRunResult("slither", "ok", findings=[finding], note="ok", duration_ms=12)
        with mock.patch("eth_scanner.engines.pipeline.run_slither", return_value=fake), \
             mock.patch("eth_scanner.engines.pipeline.run_mythril", return_value=EngineRunResult("mythril", "skipped", note="skip")), \
             mock.patch("eth_scanner.engines.pipeline.corroborate_lead") as corr, \
             mock.patch("eth_scanner.engines.pipeline.run_lead_fuzz") as fuzz:
            from eth_scanner.engines.corroborate import Corroboration
            from eth_scanner.engines.fuzz_runner import FuzzReport
            corr.return_value = Corroboration("slither-1", False, "eth_call", "reverted")
            fuzz.return_value = FuzzReport(ran=False, skipped=True, status="skipped")
            report = run_advanced_engines(
                address="0x" + "22" * 20,
                source="pragma solidity ^0.8.0; contract Vault { function deposit() external payable {} }",
                bytecode_hash="abc123",
                contract_class="vault",
                funds_usd=25_000,
                verified=True,
                rpc_url="https://example.invalid",
            )
        self.assertTrue(report.ran_slither)
        self.assertGreaterEqual(len(report.leads), 1)
        self.assertEqual(report.confirmed_count, 0)
        heat, _ = evidence_heat(
            funds_usd=25_000,
            invariant_results=[],
            corroborated=report.confirmed,
        )
        self.assertEqual(heat, 0)


class MonitorEngineRollup(unittest.TestCase):
    def test_aggregate_counts_from_drain_rows(self):
        from eth_scanner.cli import _aggregate_engine_stats

        rows = [
            {
                "address": "0x1",
                "heat": 0,
                "engine_leads": [{"id": "a"}],
                "confirmed_findings": [],
                "engine_timing": {
                    "ran_slither": True,
                    "slither_status": "ok",
                    "slither_executed": True,
                    "slither_skipped": False,
                    "slither_ms": 12,
                    "ran_mythril": False,
                    "mythril_status": "skipped",
                    "mythril_executed": False,
                    "mythril_skipped": True,
                    "ran_halmos": True,
                    "halmos_status": "compile-skip",
                    "halmos_executed": False,
                    "halmos_skipped": True,
                    "halmos_properties": 16,
                    "halmos_properties_executed": 0,
                    "clone_executed": True,
                },
            },
            {
                "address": "0x2",
                "heat": 40,
                "engine_leads": [{"id": "b"}, {"id": "c"}],
                "confirmed_findings": [
                    {"lead_id": "b", "confirmed": True},
                    {"lead_id": "c", "confirmed": False},
                ],
                "engine_timing": {
                    "ran_slither": True,
                    "slither_status": "ok",
                    "slither_executed": True,
                    "slither_skipped": False,
                    "slither_ms": 40,
                    "ran_mythril": True,
                    "mythril_status": "ok",
                    "mythril_executed": True,
                    "mythril_skipped": False,
                    "mythril_ms": 90,
                    "ran_halmos": True,
                    "halmos_status": "ok",
                    "halmos_executed": True,
                    "halmos_skipped": False,
                    "halmos_properties": 5,
                    "halmos_properties_executed": 5,
                    "halmos_properties_skipped": 0,
                    "fuzz_executed": True,
                    "fuzz_skipped": False,
                    "ran_fuzz": True,
                    "oracle_executed": True,
                    "admin_executed": True,
                    "storage_executed": False,
                    "storage_skipped": True,
                    "clone_executed": True,
                },
            },
        ]
        stats = _aggregate_engine_stats(rows)
        self.assertEqual(stats["slither_run"], 2)
        self.assertEqual(stats["slither_executed"], 2)
        self.assertEqual(stats["mythril_run"], 1)
        self.assertEqual(stats["mythril_executed"], 1)
        self.assertEqual(stats["mythril_skipped"], 1)
        self.assertEqual(stats["halmos_run"], 2)
        self.assertEqual(stats["halmos_executed"], 1)
        self.assertEqual(stats["halmos_skipped"], 1)
        self.assertEqual(stats["halmos_properties_executed"], 5)
        self.assertEqual(stats["fuzz_executed"], 1)
        self.assertEqual(stats["clone_executed"], 2)
        self.assertEqual(stats["leads"], 3)
        self.assertEqual(stats["confirmed"], 1)
        self.assertEqual(stats["heat_gt0"], 1)


if __name__ == "__main__":
    unittest.main()
