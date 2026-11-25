"""Original weird-token accounting probes. No vendored suite."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from eth_scanner.logic.weird_tokens import (
    adapter_mode,
    approval_mode,
    run_weird_probes,
    token_behaviors,
)

VAULT = "0x1111111111111111111111111111111111111111"
ASSET = "0x2222222222222222222222222222222222222222"
NOMINAL = "function deposit(uint256 assets, address receiver) external { _mint(receiver, assets); }"
MEASURED = "function deposit(uint256 assets, address receiver) external { uint256 got = token.balanceOf(address(this)); }"
FEE = "uint256 public _fee; function takeFee(uint256 amount) public returns (uint256) { return amount - _fee; }"
REBASE = "function rebase(uint256 supply) external { _rOwned[msg.sender] = supply; }"
MISSING = "function transfer(address to, uint256 amount) public { balances[msg.sender] -= amount; }"
PAUSED = "modifier whenNotPaused() { require(!paused()); _; }"
BLOCKED = "mapping(address => bool) blacklist;"
RESET = "token.forceApprove(spender, amount);"
DOUBLE = "token.approve(spender, first); token.approve(spender, second);"
ONCE = "token.approve(spender, amount);"


class WeirdTokenTests(unittest.TestCase):
    def test_module_does_not_vendor_the_unlicensed_suite(self):
        text = Path(__file__).resolve().parents[1].joinpath(
            "src", "eth_scanner", "logic", "weird_tokens.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("d-xo", text)
        self.assertNotIn("github.com/", text)

    def test_nominal_fee_is_a_shortfall_and_measured_holds(self):
        self.assertEqual(adapter_mode(NOMINAL), "nominal")
        self.assertEqual(adapter_mode(MEASURED), "measured")
        self.assertIn("fee-on-transfer", token_behaviors(FEE))
        failed = run_weird_probes(vault=VAULT, vault_source=NOMINAL, asset_source=FEE)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["results"][0]["id"], "weird-fee-on-transfer")
        self.assertNotIn("0x", failed["results"][0]["evidence"])
        self.assertGreater(failed["heat"], 0)
        self.assertTrue(failed["heat_breakdown"]["weird_tokens"])
        held = run_weird_probes(vault=VAULT, vault_source=MEASURED, asset_source=FEE)
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["heat"], 0)
        self.assertTrue(held["heat_breakdown"]["weird_tokens"])

    def test_unknown_adapter_adds_no_heat(self):
        report = run_weird_probes(vault=VAULT, vault_source="", asset_source=FEE)
        self.assertEqual(report["results"][0]["status"], "unknown")
        self.assertEqual(report["heat"], 0)

    def test_rebase_pause_blocklist_and_missing_return(self):
        source = "\n".join([REBASE, MISSING, PAUSED, BLOCKED])
        report = run_weird_probes(vault=VAULT, vault_source=NOMINAL, asset_source=source)
        ids = {row["id"] for row in report["results"] if row["status"] == "failed"}
        self.assertEqual(
            ids,
            {"weird-rebasing", "weird-missing-return", "weird-pausable", "weird-blocklist"},
        )
        measured = run_weird_probes(vault=VAULT, vault_source=MEASURED, asset_source=source)
        self.assertTrue(all(row["status"] == "held" for row in measured["results"]))
        self.assertEqual(measured["heat"], 0)

    def test_low_and_high_decimals(self):
        low = run_weird_probes(vault=VAULT, vault_source=NOMINAL, decimals=0)
        self.assertIn("decimals", low["behaviors"])
        self.assertEqual(low["results"][0]["status"], "failed")
        high = run_weird_probes(vault=VAULT, vault_source=NOMINAL, decimals=24)
        self.assertEqual(high["results"][0]["status"], "failed")
        self.assertIn("minted no shares", high["results"][0]["evidence"])
        normal = run_weird_probes(vault=VAULT, vault_source=NOMINAL, decimals=18)
        self.assertEqual(normal["status"], "clean")
        self.assertEqual(normal["heat"], 0)
        self.assertFalse(normal["heat_breakdown"]["weird_tokens"])
        measured = run_weird_probes(vault=VAULT, vault_source=MEASURED, decimals=0)
        self.assertEqual(measured["heat"], 0)

    def test_approval_race_needs_two_approves(self):
        self.assertEqual(approval_mode(DOUBLE), "replace")
        self.assertEqual(approval_mode(RESET), "reset")
        self.assertEqual(approval_mode(ONCE), "single")
        failed = run_weird_probes(vault=VAULT, vault_source=DOUBLE)
        self.assertEqual(failed["results"][0]["status"], "failed")
        self.assertGreater(failed["heat"], 0)
        reset = run_weird_probes(vault=VAULT, vault_source=RESET)
        self.assertEqual(reset["heat"], 0)
        once = run_weird_probes(vault=VAULT, vault_source=ONCE)
        self.assertEqual(once["results"][0]["status"], "held")
        self.assertEqual(once["heat"], 0)

    def test_public_fork_is_refused_before_a_call(self):
        called = []

        def caller(token, data):
            called.append((token, data))
            return "0x0"

        report = run_weird_probes(
            vault=VAULT,
            asset=ASSET,
            fork_url="https://eth.example/v2/SECRETKEY",
            caller=caller,
        )
        self.assertEqual(report["status"], "refused")
        self.assertEqual(called, [])
        self.assertNotIn("SECRETKEY", json.dumps(report))

    def test_local_fork_decimals_are_one_read(self):
        def caller(token, data):
            self.assertEqual(token, ASSET)
            self.assertEqual(data, "0x313ce567")
            return "0x0"

        report = run_weird_probes(
            vault=VAULT,
            vault_source=NOMINAL,
            asset=ASSET,
            fork_url="http://127.0.0.1:8545",
            caller=caller,
        )
        self.assertEqual(report["status"], "failed")
        self.assertIn("decimals", report["behaviors"])
        self.assertNotIn("127.0.0.1", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
