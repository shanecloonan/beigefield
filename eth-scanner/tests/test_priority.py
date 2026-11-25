"""Admin-only heat stays under 6. Unprotected, proxy, and fresh value add evidence."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.conservation import make_record
from eth_scanner.engines.rescore import adjust_heat
from eth_scanner.heat import evidence_heat
from eth_scanner.logic.priority import (
    fresh_deployment,
    unprotected_value_mover,
    unverified_upgradeable_proxy,
)

_OPEN = """
contract Vault {
    function pay(address to, uint256 amount) external {
        token.transfer(to, amount);
    }
}
"""

_WITHDRAW = """
contract Vault {
    function withdraw(uint256 amount) external {
        token.transfer(msg.sender, amount);
    }
}
"""

_OWNED = """
contract Vault {
    function withdraw(uint256 amount) external onlyOwner {
        token.transfer(msg.sender, amount);
    }
}
"""

_SHARE = """
contract Vault {
    function deposit(uint256 assets) external {
        uint256 bal = token.balanceOf(address(this));
        _mint(msg.sender, bal);
    }
}
"""


class Detectors(unittest.TestCase):
    def test_open_transfer_counts_and_an_owner_guard_does_not(self):
        self.assertTrue(unprotected_value_mover(_OPEN))
        self.assertFalse(unprotected_value_mover(_OWNED))
        self.assertFalse(unprotected_value_mover(_WITHDRAW))

    def test_proxy_requires_an_unverified_marker(self):
        self.assertFalse(unverified_upgradeable_proxy(verified=True, bytecode="3659cfe6"))
        self.assertFalse(unverified_upgradeable_proxy(verified=False, bytecode="60806040"))
        self.assertTrue(unverified_upgradeable_proxy(verified=False, bytecode="3659cfe6"))

    def test_fresh_is_thirty_days_and_high_value(self):
        now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        recent = (now - timedelta(days=10)).date().isoformat()
        old = (now - timedelta(days=40)).date().isoformat()
        self.assertTrue(fresh_deployment(200_000, recent, now=now))
        self.assertFalse(fresh_deployment(200_000, old, now=now))
        self.assertFalse(fresh_deployment(50_000, recent, now=now))


class Scoring(unittest.TestCase):
    def test_admin_and_a_shape_lead_stay_under_six(self):
        heat, bd = evidence_heat(
            funds_usd=200_000,
            invariant_results=[],
            eoa_admin=True,
            source=_SHARE,
        )
        self.assertEqual(bd["eoa_admin"], 3)
        self.assertEqual(bd["gated_leads"], 2)
        self.assertEqual(heat, 5)
        self.assertTrue(bd["admin_capped"])

    def test_fork_backed_leads_still_reach_six(self):
        failure = [make_record("donation-price", "fail", 10**18)]
        heat, bd = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            lead_ids=["share-balance", "spot-price", "reentrancy"],
            conservation=failure,
        )
        self.assertEqual(bd["gated_leads"], 6)
        self.assertEqual(heat, 6)
        self.assertFalse(bd["admin_capped"])

    def test_privileged_and_a_live_lead_still_reach_seven(self):
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
        )
        self.assertEqual(bd["privileged_callable"], 4)
        self.assertEqual(bd["corroborated_leads"], 3)
        self.assertEqual(heat, 7)

    def test_unprotected_proxy_and_fresh_add_points(self):
        now = datetime(2026, 11, 25, tzinfo=timezone.utc)
        deployed = (now - timedelta(days=3)).date().isoformat()
        heat, bd = evidence_heat(
            funds_usd=250_000,
            invariant_results=[],
            unprotected_value=True,
            unverified_proxy=True,
            deployed_at=deployed,
            now=now,
        )
        self.assertEqual(bd["unprotected_evidence"], 3)
        self.assertEqual(bd["proxy_evidence"], 2)
        self.assertEqual(bd["fresh_evidence"], 2)
        self.assertEqual(heat, 7)

    def test_sequence_and_oracle_are_labels(self):
        _, bd = evidence_heat(
            funds_usd=None,
            invariant_results=[
                {"id": "share-price-monotonic", "status": "failed"},
                {"id": "profit-chainlink-answer", "status": "failed"},
            ],
        )
        self.assertTrue(bd["sequence"])
        self.assertTrue(bd["oracle"])

    def test_rescore_lowers_admin_noise_and_keeps_static_points(self):
        lowered = adjust_heat(
            heat=6,
            breakdown={"eoa_admin": 3, "gated_leads": 3, "gated_lead_ids": ["share-balance"]},
            eoa_stands=None,
            privileged_stands=None,
        )
        self.assertEqual(lowered["heat"], 5)
        kept = adjust_heat(
            heat=6,
            breakdown={"eoa_admin": 3, "static_evidence": 3, "gated_leads": 0},
            eoa_stands=None,
            privileged_stands=None,
        )
        self.assertEqual(kept["heat"], 6)
        quiet = adjust_heat(
            heat=3,
            breakdown={"static_evidence": 3},
            eoa_stands=None,
            privileged_stands=None,
        )
        self.assertEqual(quiet["heat"], 3)


if __name__ == "__main__":
    unittest.main()
