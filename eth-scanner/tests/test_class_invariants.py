"""Class routing and the Lane B heat-12 false-positive fix.

BentoBoxV1 is audited Sushi code and stays cold, like LINK/SAND/HEX.
Harness setUp failures and engine output do not add heat.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.classify import classify_contract, engine_config_for_class
from eth_scanner.engines.fuzz_runner import FuzzFailure, FuzzReport, fuzz_failures_as_invariants
from eth_scanner.funnel.s0_s7 import FunnelConfig, FunnelContext, run_lane_a
from eth_scanner.heat import evidence_heat
from eth_scanner.invariants.live import donation_inflation_status
from eth_scanner.known_safe import is_known_safe
from eth_scanner.types import IRDocument, SourceArtifact, Target

BENTO = "0xf5bce5077908a1b7370b9ae04adc565ebd643966"
LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"


class ClassifyMasterList(unittest.TestCase):
    def test_families(self):
        klass, conf = classify_contract(
            name="Vault", source="function totalAssets() function convertToAssets(uint256)", category="Yield",
        )
        self.assertEqual(klass, "erc4626-vault")
        self.assertIn(conf, {"high", "med"})
        klass, _ = classify_contract(name="CToken", source="function exchangeRateStored()", forked_from="Compound")
        self.assertEqual(klass, "compound-lending")
        klass, _ = classify_contract(name="Pool", source="function getReserves() function kLast()", forked_from="Uniswap V2")
        self.assertEqual(klass, "uniswap-amm")
        klass, _ = classify_contract(name="BentoBoxV1", source="contract BentoBoxV1 {}", category="Dexs")
        self.assertEqual(klass, "custom-amm")
        klass, conf = classify_contract(name="Mystery", source="contract X {}")
        self.assertEqual(klass, "other")
        self.assertEqual(conf, "low")
        self.assertEqual(engine_config_for_class("other")["fuzz_template"], "generic")
        self.assertNotEqual(engine_config_for_class("erc4626-vault")["slither_detect"], "all")


class DonationFlag(unittest.TestCase):
    def test_heat_only_when_assets_sit_in_a_near_empty_vault(self):
        self.assertEqual(donation_inflation_status(10**18, 10**18), "held")
        self.assertEqual(donation_inflation_status(10, 0), "unknown")
        self.assertEqual(donation_inflation_status(10, 10**18), "failed")


class LaneBHeatFix(unittest.TestCase):
    def test_setup_failure_and_engine_output_add_zero_heat(self):
        report = FuzzReport(
            ran=True, skipped=False, tool="forge", status="failed",
            failures=[
                FuzzFailure("setUp()", "forge", "setup reverted", "property failed: setUp()"),
                FuzzFailure("setUp()", "forge", "setup reverted", "property failed: setUp()"),
                FuzzFailure("solvency_assets_cover_shares", "forge", "seq", "property failed: test_solvency"),
            ],
        )
        rows = fuzz_failures_as_invariants(report)
        self.assertEqual(len(rows), 2)
        setup = next(r for r in rows if "setup" in r["id"].lower())
        self.assertEqual(setup["status"], "unknown")
        heat, bd = evidence_heat(funds_usd=193_000, invariant_results=rows, corroborated=[{
            "lead_id": "fuzz-setUp()", "confirmed": True, "method": "fuzz", "live_confirmed": False,
        }])
        self.assertEqual(heat, 0)
        self.assertEqual(bd["invariants_failed"], 0)
        self.assertEqual(bd["corroborated_leads"], 0)

    def test_live_eth_call_failure_still_heats(self):
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=[{"id": "erc4626-solvency", "status": "failed", "evidence": "convertToAssets above totalAssets"}],
        )
        self.assertGreater(heat, 0)
        self.assertGreater(bd["invariants_failed"], 0)

    def test_duplicate_live_rule_counts_once(self):
        rows = [
            {"id": "erc4626-solvency", "status": "failed"},
            {"id": "erc4626-solvency", "status": "failed"},
        ]
        _, bd = evidence_heat(funds_usd=50_000, invariant_results=rows)
        self.assertEqual(bd["invariants_failed"], 3)

    def test_bentobox_stays_cold_like_link(self):
        for addr, name in ((LINK, "LinkToken"), (BENTO, "BentoBoxV1")):
            ok, _ = is_known_safe(address=addr, contract_name=name)
            self.assertTrue(ok, msg=name)
            result = run_lane_a(FunnelContext(
                target=Target(address=addr, has_code=True, funds_usd=200_000, tvl_usd=200_000),
                artifact=SourceArtifact(
                    kind="source", language="solidity",
                    content="pragma solidity ^0.8.0; contract T {}",
                    src_confidence="high", contract_name=name,
                ),
                ir=IRDocument(ir_confidence="high", src_confidence="high", contract_class="lending"),
                config=FunnelConfig(skip_live_invariants=True, min_funds_usd=2_000),
            ))
            self.assertEqual(result.heat, 0, msg=name)
            self.assertEqual(result.drop_reason, "known-safe", msg=name)


if __name__ == "__main__":
    unittest.main()
