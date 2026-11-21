"""Incident names and dates only. Writeups never leave the parser."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark.defihacklabs import index_report, parse_index

FIXTURE = """
[20220101 ExampleProtocol](#20220101-exampleprotocol---the attacker flash-borrows and calls a function)
[20220101 ExampleProtocol](#duplicate)
[20220202 Bad.sol](#drop-code)
function steal() public {}
[20221340 BrokenDate](#no)
[20220303 Second](#second---calldata 0xdeadbeef)
"""


class DefiHackLabsIndex(unittest.TestCase):
    def test_only_name_and_date_are_kept(self):
        rows = parse_index(FIXTURE)
        self.assertEqual(rows, [
            {"date": "2022-01-01", "name": "ExampleProtocol"},
            {"date": "2022-03-03", "name": "Second"},
        ])
        blob = json.dumps(rows)
        self.assertNotIn("flash", blob)
        self.assertNotIn("function", blob)
        self.assertNotIn(".sol", blob)
        self.assertNotIn("0xdead", blob)

    def test_overlap_does_not_score_safe_rows(self):
        labeled = [
            {"name": "ExampleProtocol", "label": "affected", "address": "0x1"},
            {"name": "DAI", "label": "safe", "address": "0x2"},
        ]
        report = index_report(labeled, text=FIXTURE)
        self.assertEqual(report["incidents"], 2)
        self.assertEqual(report["labeled_affected"], 1)
        self.assertEqual(report["matched_affected"], 1)
        self.assertEqual(report["heat_contribution"], 0)
        self.assertTrue(report["metadata_only"])
        self.assertFalse(report["degraded"])

    def test_a_failed_fetch_stays_empty(self):
        def boom():
            raise TimeoutError("down")

        report = index_report([], fetch=boom)
        self.assertEqual(report["incidents"], 0)
        self.assertTrue(report["degraded"])
        self.assertEqual(report["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
