"""Certora stays an external CLI. Violations are rule names and heat."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from eth_scanner.logic.certora_prover import PIN, parse_violations, run_certora, spec_path

ADDR = "0x1111111111111111111111111111111111111111"
SOURCE = "contract Target { function totalSupply() external pure returns (uint256) { return 0; } }\n"


class CertoraTests(unittest.TestCase):
    def test_pin_is_unlinked_gpl_and_specs_are_ours(self):
        self.assertEqual(PIN["license"], "GPL-3.0")
        self.assertFalse(PIN["link"])
        module = Path(__file__).resolve().parents[1] / "src" / "eth_scanner" / "logic" / "certora_prover.py"
        text = module.read_text(encoding="utf-8")
        self.assertNotIn("import certora", text)
        self.assertNotIn(".jar", text)
        erc20 = spec_path("erc20").read_text(encoding="utf-8")
        erc4626 = spec_path("erc4626").read_text(encoding="utf-8")
        self.assertIn("strangerCannotReduceBalance", erc20)
        self.assertIn("approveSetsAllowance", erc20)
        self.assertIn("assetsCoverClaims", erc4626)
        self.assertIn("roundingFavorsVault", erc4626)
        self.assertIn("zeroDepositMintsNothing", erc4626)
        self.assertIn("strangerCannotReduceShares", erc4626)
        self.assertIn("SPDX-License-Identifier: MIT", erc20)

    def test_shortlist_and_verified_source_are_required(self):
        off = run_certora(address=ADDR, source=SOURCE, kind="erc20", on_shortlist=False, verified=True)
        self.assertEqual(off["status"], "skipped")
        self.assertEqual(off["heat"], 0)
        unverified = run_certora(address=ADDR, source=SOURCE, kind="erc20", on_shortlist=True, verified=False)
        self.assertIn("verified", unverified["note"])
        self.assertFalse(unverified["ran"])

    def test_a_violation_adds_heat_and_drops_calldata(self):
        output = "\n".join([
            "strangerCannotReduceBalance - violated",
            "call sequence 0xdeadbeefcafebabe",
            "assetsCoverClaims: violated",
        ])
        report = run_certora(
            address=ADDR,
            source=SOURCE,
            kind="erc4626",
            on_shortlist=True,
            verified=True,
            output=output,
        )
        self.assertEqual(report["status"], "violated")
        self.assertEqual(report["heat"], 6)
        self.assertEqual(report["heat_breakdown"]["certora_evidence"], 6)
        ids = [row["id"] for row in report["violated"]]
        self.assertEqual(ids, ["strangerCannotReduceBalance", "assetsCoverClaims"])
        self.assertNotIn("deadbeef", json.dumps(report["violated"]))

    def test_a_hold_adds_no_heat(self):
        report = run_certora(
            address=ADDR,
            source=SOURCE,
            kind="erc20",
            on_shortlist=True,
            verified=True,
            output="all rules passed",
        )
        self.assertEqual(report["status"], "held")
        self.assertEqual(report["heat"], 0)
        self.assertTrue(report["heat_breakdown"]["certora"])

    def test_parser_ignores_a_bare_word(self):
        self.assertEqual(parse_violations("no rules here"), [])


if __name__ == "__main__":
    unittest.main()
