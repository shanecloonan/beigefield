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
             mock.patch("eth_scanner.engines.pipeline.corroborate_lead") as corr:
            from eth_scanner.engines.corroborate import Corroboration
            corr.return_value = Corroboration("slither-1", False, "eth_call", "reverted")
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


if __name__ == "__main__":
    unittest.main()
