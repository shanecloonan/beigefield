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

    def test_shortlist_triage_keeps_leads_and_drops_the_text(self):
        from eth_scanner.decompile.heimdall import HEIMDALL_PIN, decompile_shortlist

        calls = []

        def runner(address, bytecode):
            calls.append(address)
            return "function withdraw() public { feeOnTransfer(amount); }"

        off = decompile_shortlist(ADDR, on_shortlist=False, heimdall=runner)
        self.assertEqual(off["skipped"], "not-shortlist")
        self.assertEqual(calls, [])
        verified = decompile_shortlist(ADDR, on_shortlist=True, verified=True, heimdall=runner)
        self.assertEqual(verified["skipped"], "verified")
        self.assertEqual(calls, [])
        report = decompile_shortlist(ADDR, on_shortlist=True, bytecode=CODE, heimdall=runner)
        self.assertTrue(report["ran"])
        self.assertEqual(report["heat"], 0)
        self.assertTrue(report["heat_breakdown"]["decompile_triage"])
        ids = [row["id"] for row in report["leads"]]
        self.assertIn("fee-on-transfer-rebase", ids)
        self.assertIn("value-moving-withdraw", ids)
        self.assertNotIn("content", report)
        self.assertNotIn("feeOnTransfer", str(report["leads"]))
        self.assertEqual(report["pin"]["version"], "0.9.3")
        self.assertTrue(HEIMDALL_PIN["url"].endswith("heimdall-linux-amd64"))
        self.assertNotIn("install", HEIMDALL_PIN["url"])

    def test_pin_matches_the_workflow_download(self):
        from eth_scanner.decompile.heimdall import HEIMDALL_PIN

        workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "eth-scanner-deep.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertIn(HEIMDALL_PIN["url"], text)
        self.assertNotIn("install.sh", text)
        self.assertNotIn("| bash", text)


if __name__ == "__main__":
    unittest.main()
