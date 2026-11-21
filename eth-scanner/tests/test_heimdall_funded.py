"""Unverified funded decompile stays low confidence and adds no heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.decompile.heimdall import decompile, decompile_unverified_funded

ADDR = "0x00000000000000000000000000000000000000aa"
CODE = "0x60806040"


class FundedDecompile(unittest.TestCase):
    def test_verified_and_unfunded_do_not_run(self):
        calls = []

        def runner(address, bytecode):
            calls.append(address)
            return "contract X {}"

        verified = decompile_unverified_funded(ADDR, funds_usd=1_000, verified=True, heimdall=runner)
        poor = decompile_unverified_funded(ADDR, funds_usd=50, heimdall=runner)
        unknown = decompile_unverified_funded(ADDR, funds_usd=None, heimdall=runner)
        self.assertEqual(calls, [])
        self.assertEqual(verified["skipped"], "verified")
        self.assertEqual(poor["skipped"], "unfunded")
        self.assertEqual(unknown["skipped"], "unfunded")
        self.assertTrue(all(row["src_confidence"] == "low" and row["heat_contribution"] == 0 for row in (verified, poor, unknown)))

    def test_heimdall_then_panoramix_then_stub(self):
        heimdall = decompile_unverified_funded(
            ADDR, funds_usd=250, bytecode=CODE, heimdall=lambda a, b: "contract FromHeimdall {}", panoramix=lambda a, b: "nope",
        )
        self.assertEqual(heimdall["tool"], "heimdall")
        self.assertIn("FromHeimdall", heimdall["content"])
        self.assertTrue(heimdall["lower_confidence"])
        self.assertEqual(heimdall["heat_contribution"], 0)

        fell = decompile_unverified_funded(
            ADDR, funds_usd=250, heimdall=lambda a, b: "", panoramix=lambda a, b: "contract FromPanoramix {}",
        )
        self.assertEqual(fell["tool"], "panoramix")
        self.assertIn("FromPanoramix", fell["content"])

        def boom(address, bytecode):
            raise RuntimeError("tool failed")

        stub = decompile_unverified_funded(ADDR, funds_usd=250, heimdall=boom, panoramix=lambda a, b: "")
        self.assertEqual(stub["tool"], "none")
        self.assertEqual(stub["skipped"], "no-tool")
        self.assertEqual(stub["content"], "")
        self.assertEqual(stub["heat_contribution"], 0)

    def test_missing_clis_stay_low_confidence(self):
        art = decompile(ADDR, CODE)
        self.assertEqual(art.src_confidence, "low")
        self.assertEqual(art.kind, "decompile")
        self.assertIn(art.tool, {"none", "heimdall", "panoramix"})


if __name__ == "__main__":
    unittest.main()
