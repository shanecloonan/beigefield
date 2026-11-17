"""Permissive class-gate policy for advanced engines."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.pipeline import ENGINE_ELIGIBLE_CLASSES, run_advanced_engines
from eth_scanner.heuristics.class_gate import (
    ALLOWLIST_CLASSES,
    class_gate_allows,
    class_gate_mode,
    has_risky_surface,
)
from eth_scanner.research.pipeline import should_proceed
from eth_scanner.types import FunnelResult


PLAIN_ERC20 = """
pragma solidity ^0.8.0;
contract Token {
    mapping(address => uint) public balanceOf;
    function transfer(address to, uint amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
    function approve(address, uint) external returns (bool) { return true; }
}
"""

WETH_LIKE = """
pragma solidity ^0.8.0;
contract WETH {
    mapping(address => uint) public balanceOf;
    function deposit() external payable { balanceOf[msg.sender] += msg.value; }
    function withdraw(uint amount) external {
        balanceOf[msg.sender] -= amount;
        payable(msg.sender).transfer(amount);
    }
}
"""

RISKY_TOKEN = """
pragma solidity ^0.8.0;
contract ProxyToken {
    address public implementation;
    function upgradeTo(address next) external { implementation = next; }
    fallback() external payable {
        (bool ok, ) = implementation.delegatecall(msg.data);
        require(ok);
    }
}
"""

UTILITY_SRC = "pragma solidity ^0.8.0; contract Utils { function hash(bytes memory x) external pure returns (bytes32) { return keccak256(x); } }"


class ModeAndPolicy(unittest.TestCase):
    def test_default_is_permissive(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "ETH_SCANNER_CLASS_GATE_MODE"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(class_gate_mode(), "permissive")

    def test_env_modes(self):
        for mode in ("allowlist", "permissive", "off"):
            with mock.patch.dict("os.environ", {"ETH_SCANNER_CLASS_GATE_MODE": mode}, clear=False):
                self.assertEqual(class_gate_mode(), mode)

    def test_allowlist_rejects_utility_and_token(self):
        ok, reason = class_gate_allows("utility", mode="allowlist")
        self.assertFalse(ok)
        self.assertIn("not money-at-risk", reason)
        ok, _ = class_gate_allows("token", source=RISKY_TOKEN, mode="allowlist")
        self.assertFalse(ok)
        ok, _ = class_gate_allows("vault", mode="allowlist")
        self.assertTrue(ok)
        ok, _ = class_gate_allows("custody", mode="allowlist")
        self.assertTrue(ok)

    def test_permissive_allows_utility_and_unknown(self):
        ok, reason = class_gate_allows("utility", source=UTILITY_SRC, mode="permissive")
        self.assertTrue(ok)
        self.assertIn("permissive", reason)
        ok, _ = class_gate_allows("unknown", mode="permissive")
        self.assertTrue(ok)
        ok, _ = class_gate_allows("router", mode="permissive")
        self.assertTrue(ok)

    def test_permissive_denies_plain_token_and_static_nft(self):
        ok, reason = class_gate_allows("token", source=PLAIN_ERC20, mode="permissive")
        self.assertFalse(ok)
        self.assertIn("plain token", reason)
        ok, _ = class_gate_allows("nft", source="pragma solidity ^0.8.0; contract N { function ownerOf(uint) external view returns (address) { return address(0); } }", mode="permissive")
        self.assertFalse(ok)

    def test_permissive_allows_wrap_or_bank_with_withdraw(self):
        # WETH-like and bank-style deposit/withdraw are not "plain static tokens".
        self.assertTrue(has_risky_surface(WETH_LIKE))
        ok, reason = class_gate_allows("wrap-token", source=WETH_LIKE, mode="permissive")
        self.assertTrue(ok)
        self.assertIn("risky surface", reason)

    def test_permissive_allows_token_with_risky_surface(self):
        self.assertTrue(has_risky_surface(RISKY_TOKEN))
        self.assertFalse(has_risky_surface(PLAIN_ERC20))
        ok, reason = class_gate_allows("token", source=RISKY_TOKEN, mode="permissive")
        self.assertTrue(ok)
        self.assertIn("risky surface", reason)

    def test_off_allows_plain_token(self):
        ok, reason = class_gate_allows("token", source=PLAIN_ERC20, mode="off")
        self.assertTrue(ok)
        self.assertEqual(reason, "class gate off")

    def test_allowlist_constant_covers_seven_families(self):
        for klass in ("lending", "vault", "staking", "pool", "bridge", "maker", "custody"):
            self.assertIn(klass, ALLOWLIST_CLASSES)
            self.assertIn(klass, ENGINE_ELIGIBLE_CLASSES)


class PipelineUsesGate(unittest.TestCase):
    def test_plain_token_still_skipped_under_default_permissive(self):
        report = run_advanced_engines(
            address="0x" + "11" * 20,
            source=PLAIN_ERC20,
            contract_class="token",
            funds_usd=10_000,
            verified=True,
        )
        self.assertFalse(report.ran_slither)
        self.assertTrue(any("plain token" in n or "not money-at-risk" in n for n in report.notes))

    def test_utility_runs_under_permissive(self):
        finding_src = "pragma solidity ^0.8.0; contract U {}"
        with mock.patch.dict("os.environ", {"ETH_SCANNER_CLASS_GATE_MODE": "permissive"}, clear=False), \
             mock.patch("eth_scanner.engines.pipeline.run_slither") as slith, \
             mock.patch("eth_scanner.engines.pipeline.run_mythril") as myth, \
             mock.patch("eth_scanner.engines.pipeline.run_lead_fuzz") as fuzz, \
             mock.patch("eth_scanner.engines.pipeline.corroborate_lead"):
            from eth_scanner.deep.runners import EngineRunResult
            slith.return_value = EngineRunResult("slither", "ok", findings=[], note="ok", duration_ms=1)
            myth.return_value = EngineRunResult("mythril", "skipped", note="skip")
            fuzz.return_value = mock.Mock(ran=False, skipped=True, status="skipped")
            report = run_advanced_engines(
                address="0x" + "33" * 20,
                source=finding_src,
                contract_class="utility",
                funds_usd=5_000,
                verified=True,
            )
        self.assertTrue(report.ran_slither)

    def test_allowlist_mode_still_skips_utility(self):
        with mock.patch.dict("os.environ", {"ETH_SCANNER_CLASS_GATE_MODE": "allowlist"}, clear=False):
            report = run_advanced_engines(
                address="0x" + "44" * 20,
                source=UTILITY_SRC,
                contract_class="utility",
                funds_usd=5_000,
                verified=True,
            )
        self.assertFalse(report.ran_slither)
        self.assertTrue(any("not money-at-risk" in n for n in report.notes))

    def test_funds_floor_still_blocks_eligible_class(self):
        report = run_advanced_engines(
            address="0x" + "55" * 20,
            source="pragma solidity ^0.8.0; contract Vault { function deposit() external payable {} }",
            contract_class="vault",
            funds_usd=50,
            verified=True,
            min_funds_usd=100,
        )
        self.assertFalse(report.ran_slither)
        self.assertTrue(any("funds below floor" in n for n in report.notes))

    def test_risky_token_runs_under_permissive_even_when_allowlist_would_skip(self):
        with mock.patch("eth_scanner.engines.pipeline.run_slither") as slith, \
             mock.patch("eth_scanner.engines.pipeline.run_mythril") as myth, \
             mock.patch("eth_scanner.engines.pipeline.run_lead_fuzz") as fuzz, \
             mock.patch("eth_scanner.engines.pipeline.corroborate_lead"):
            from eth_scanner.deep.runners import EngineRunResult
            slith.return_value = EngineRunResult("slither", "ok", findings=[], note="ok", duration_ms=1)
            myth.return_value = EngineRunResult("mythril", "skipped", note="skip")
            fuzz.return_value = mock.Mock(ran=False, skipped=True, status="skipped")
            report = run_advanced_engines(
                address="0x" + "66" * 20,
                source=RISKY_TOKEN,
                contract_class="token",
                funds_usd=8_000,
                verified=True,
            )
        self.assertTrue(report.ran_slither)


class ResearchGate(unittest.TestCase):
    def test_token_without_source_still_stops(self):
        ok, reason = should_proceed(FunnelResult(
            bucket="lane-a-cool", dropped=False, drop_reason=None,
            heat=0, src_confidence="high", ir_confidence="high",
            contract_class="token", scope="demoted-token",
        ))
        self.assertFalse(ok)
        self.assertIn("gated out", reason)

    def test_utility_proceeds_under_permissive(self):
        ok, reason = should_proceed(FunnelResult(
            bucket="lane-a-cool", dropped=False, drop_reason=None,
            heat=0, src_confidence="high", ir_confidence="high",
            contract_class="utility", scope="utility",
        ), source=UTILITY_SRC)
        self.assertTrue(ok)
        self.assertIn("class gate allows", reason)


if __name__ == "__main__":
    unittest.main()
