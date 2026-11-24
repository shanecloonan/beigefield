"""Shape leads add heat only when an independent fact or a fork failure backs them."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.conservation import make_record
from eth_scanner.engines.rescore import adjust_heat
from eth_scanner.heat import evidence_heat


_SHARE = """
contract Vault {
    function deposit(uint256 assets) external {
        uint256 bal = token.balanceOf(address(this));
        _mint(msg.sender, bal);
    }
    function withdraw(uint256) external {}
}
"""


class Gate(unittest.TestCase):
    def test_bare_lead_adds_no_heat(self):
        heat, bd = evidence_heat(funds_usd=1_000_000, invariant_results=[], source=_SHARE)
        self.assertEqual(heat, 0)
        self.assertEqual(bd["gated_leads"], 0)
        self.assertEqual(bd["gated_lead_ids"], ["share-balance"])

    def test_failed_invariant_backs_the_lead_once(self):
        inv = [{"id": "erc4626-asset-shortfall", "status": "failed", "evidence": "short"}]
        heat, bd = evidence_heat(funds_usd=50_000, invariant_results=inv, source=_SHARE)
        plain, plain_bd = evidence_heat(funds_usd=50_000, invariant_results=inv)
        self.assertEqual(plain_bd["invariants_failed"], 3)
        self.assertEqual(bd["gated_leads"], 3)
        self.assertEqual(heat, plain + 3)
        again, again_bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=inv,
            source=_SHARE,
            lead_ids=["share-balance", "share-balance"],
        )
        self.assertEqual(again, heat)
        self.assertEqual(again_bd["gated_lead_ids"], ["share-balance"])

    def test_fork_failure_backs_a_lead_without_other_evidence(self):
        failure = [make_record("deposit-redeem", "fail", 5000)]
        heat, bd = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            lead_ids=["reentrancy"],
            conservation=failure,
        )
        self.assertEqual(bd["invariants_failed"], 0)
        self.assertEqual(bd["gated_leads"], 3)
        self.assertEqual(heat, 3)

    def test_small_or_passing_fork_delta_does_not_back_the_lead(self):
        dust = [make_record("deposit-redeem", "fail", 10)]
        held = [make_record("donation-price", "pass", 0)]
        for records in (dust, held):
            heat, bd = evidence_heat(
                funds_usd=None,
                invariant_results=[],
                lead_ids=["spot-price"],
                conservation=records,
            )
            self.assertEqual(heat, 0, records)
            self.assertEqual(bd["gated_leads"], 0)

    def test_three_leads_share_the_corroboration_cap(self):
        failure = [make_record("donation-price", "fail", 10**18)]
        heat, bd = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            lead_ids=["share-balance", "spot-price", "reentrancy"],
            conservation=failure,
        )
        self.assertEqual(bd["gated_leads"], 6)
        self.assertEqual(heat, 6)

    def test_same_fact_is_not_counted_twice(self):
        heat, bd = evidence_heat(
            funds_usd=200_000,
            invariant_results=[],
            privileged_callable=True,
            corroborated=[{
                "lead_id": "share-balance",
                "confirmed": True,
                "method": "eth_call",
                "live_confirmed": True,
            }],
            lead_ids=["share-balance"],
        )
        self.assertEqual(bd["privileged_callable"], 4)
        self.assertEqual(bd["corroborated_leads"], 3)
        self.assertEqual(bd["gated_leads"], 0)
        self.assertEqual(heat, 7)


class Rescore(unittest.TestCase):
    def test_existing_lead_does_not_raise_without_fork_evidence(self):
        adjusted = adjust_heat(
            heat=3,
            breakdown={
                "invariants_failed": 3,
                "gated_lead_ids": ["share-balance"],
                "gated_leads": 0,
            },
            eoa_stands=None,
            privileged_stands=None,
        )
        self.assertEqual(adjusted["heat"], 3)
        self.assertEqual(adjusted["gated_leads"], 0)

    def test_fork_failure_may_raise_the_gated_lead(self):
        adjusted = adjust_heat(
            heat=0,
            breakdown={
                "invariants_failed": 0,
                "gated_lead_ids": ["reentrancy"],
                "conservation": [make_record("reentrant-accounting", "fail", 10**18)],
            },
            eoa_stands=None,
            privileged_stands=None,
        )
        self.assertEqual(adjusted["heat"], 3)
        self.assertEqual(adjusted["gated_leads"], 3)

    def test_contradicted_points_still_fall_when_a_fork_failure_is_present(self):
        adjusted = adjust_heat(
            heat=4,
            breakdown={
                "privileged_callable": 4,
                "gated_lead_ids": ["spot-price"],
                "conservation": [make_record("donation-price", "fail", 5000)],
            },
            eoa_stands=None,
            privileged_stands=False,
        )
        self.assertEqual(adjusted["privileged_callable"], 0)
        self.assertEqual(adjusted["heat"], 3)


if __name__ == "__main__":
    unittest.main()
