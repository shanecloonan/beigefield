"""Conservation fork records: name, pass/fail, value delta, evidence hash."""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.conservation import (
    HIGH_CONFIDENCE_DELTA,
    MAX_CONTRACTS,
    apply_conservation,
    collapse_lines,
    high_confidence,
    make_record,
    run_conservation,
    select_targets,
)


class Records(unittest.TestCase):
    def test_record_keeps_only_the_four_fields(self):
        row = make_record("deposit-redeem", "fail", 5000)
        self.assertEqual(
            set(row),
            {"invariant", "status", "value_delta", "evidence_hash"},
        )
        self.assertEqual(row["status"], "fail")
        self.assertEqual(row["value_delta"], 5000)
        self.assertEqual(len(row["evidence_hash"]), 64)
        again = make_record("deposit-redeem", "fail", 5000)
        self.assertEqual(row["evidence_hash"], again["evidence_hash"])

    def test_trace_lines_are_dropped(self):
        blob = "\n".join([
            "Traces:",
            "[FAIL] testFuzz_deposit_redeem(uint256) (runs: 8)",
            "call 0x" + ("ab" * 40),
            "deposit-redeem fail 2500",
            "unprivileged-value pass 0",
            "unprivileged-value pass 4",
            "donation-price fail 10",
            "donation-price pass 1",
            "reentrant-accounting pass 0",
        ])
        rows = collapse_lines(blob)
        blob_out = " ".join(str(r) for r in rows)
        self.assertNotIn("Traces", blob_out)
        self.assertNotIn("ababab", blob_out)
        by_name = {r["invariant"]: r for r in rows}
        self.assertEqual(by_name["deposit-redeem"]["status"], "fail")
        self.assertEqual(by_name["deposit-redeem"]["value_delta"], 2500)
        self.assertEqual(by_name["unprivileged-value"]["value_delta"], 4)
        self.assertEqual(by_name["donation-price"]["status"], "fail")
        self.assertEqual(by_name["donation-price"]["value_delta"], 10)
        self.assertEqual(high_confidence(rows), ["deposit-redeem"])
        self.assertGreater(by_name["deposit-redeem"]["value_delta"], HIGH_CONFIDENCE_DELTA)

    def test_selects_heat_then_leads_and_caps(self):
        rows = [
            {"address": "0x" + "11" * 20, "heat": 0},
            {"address": "0x" + "22" * 20, "heat": 1, "leads": ["share-balance"]},
            {"address": "0x" + "33" * 20, "heat": 9},
            {"address": "0x" + "33" * 20, "heat": 2},
            {"address": "0x" + "44" * 20, "heat": 0, "leads": ["spot-price", "reentrancy"]},
            {"address": "0x" + "55" * 20, "heat": 4},
            {"address": "0x" + "77" * 20, "heat": 8},
        ]
        picked = select_targets(rows, limit=99)
        self.assertLessEqual(len(picked), MAX_CONTRACTS)
        self.assertEqual(picked[0]["address"], "0x" + "33" * 20)
        self.assertEqual(int(picked[0]["heat"]), 9)
        addrs = [row["address"] for row in picked]
        self.assertNotIn("0x" + "11" * 20, addrs)
        self.assertIn("0x" + "44" * 20, addrs)

    def test_apply_does_not_change_heat(self):
        row = {"address": "0x" + "ab" * 20, "heat": 4, "heat_breakdown": {"total": 4}}
        records = [make_record("donation-price", "fail", 10**18)]
        patched = apply_conservation(row, records)
        self.assertEqual(patched["heat"], 4)
        self.assertEqual(patched["heat_breakdown"]["total"], 4)
        stored = patched["heat_breakdown"]["conservation"]
        self.assertEqual(set(stored[0]), {"invariant", "status", "value_delta", "evidence_hash"})
        self.assertNotIn("sequence", patched["heat_breakdown"])


class ForgeFixtures(unittest.TestCase):
    def setUp(self):
        if not shutil.which("forge") and not (Path.home() / ".foundry" / "bin" / "forge").is_file():
            self.skipTest("forge is not installed")
        if not shutil.which("anvil") and not (Path.home() / ".foundry" / "bin" / "anvil").is_file():
            self.skipTest("anvil is not installed")

    def test_fair_passes_and_overpay_donation_reenter_fail(self):
        fair = run_conservation(fixture="fair", timeout_s=90)
        self.assertTrue(fair["ran"], fair["note"])
        fair_rows = {r["invariant"]: r for r in fair["records"]}
        self.assertEqual(set(fair_rows), {
            "deposit-redeem", "unprivileged-value", "donation-price", "reentrant-accounting",
        })
        self.assertTrue(all(r["status"] == "pass" for r in fair["records"]))
        self.assertEqual(fair["high_confidence"], [])
        self.assertNotIn("sequence", fair)

        over = run_conservation(fixture="overpay", timeout_s=90)
        over_rows = {r["invariant"]: r for r in over["records"]}
        self.assertEqual(over_rows["deposit-redeem"]["status"], "fail")
        self.assertGreater(over_rows["deposit-redeem"]["value_delta"], HIGH_CONFIDENCE_DELTA)
        self.assertIn("deposit-redeem", over["high_confidence"])
        self.assertEqual(over_rows["unprivileged-value"]["status"], "fail")
        self.assertEqual(over_rows["donation-price"]["status"], "pass")

        donated = run_conservation(fixture="donation", timeout_s=90)
        donated_rows = {r["invariant"]: r for r in donated["records"]}
        self.assertEqual(donated_rows["donation-price"]["status"], "fail")
        self.assertGreater(donated_rows["donation-price"]["value_delta"], HIGH_CONFIDENCE_DELTA)
        self.assertEqual(donated_rows["deposit-redeem"]["status"], "pass")

        reentered = run_conservation(fixture="reenter", timeout_s=90)
        re_rows = {r["invariant"]: r for r in reentered["records"]}
        self.assertEqual(re_rows["reentrant-accounting"]["status"], "fail")
        self.assertGreater(re_rows["reentrant-accounting"]["value_delta"], HIGH_CONFIDENCE_DELTA)
        self.assertEqual(re_rows["deposit-redeem"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
