"""An unsafe storage upgrade is a clash. A clean append adds no heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.logic.upgrade_layout import compare_layouts


def _row(label: str, slot: str, type_name: str, offset: int = 0) -> dict:
    return {"label": label, "slot": slot, "offset": offset, "type": type_name}


class UpgradeLayout(unittest.TestCase):
    def test_an_append_holds(self):
        before = [_row("totalAssets", "0", "uint256")]
        after = before + [_row("locked", "1", "uint256")]
        report = compare_layouts(before, after)
        self.assertEqual(report["status"], "held")
        self.assertEqual(report["heat"], 0)
        self.assertEqual(report["clashes"], [])
        self.assertTrue(report["heat_breakdown"]["upgrade"])

    def test_a_moved_variable_is_a_clash(self):
        before = [_row("balances", "0", "uint256"), _row("totalSupply", "1", "uint256")]
        after = [_row("extra", "0", "uint256"), _row("balances", "1", "uint256"), _row("totalSupply", "2", "uint256")]
        report = compare_layouts(before, after)
        kinds = {row["label"]: row["kind"] for row in report["clashes"]}
        self.assertEqual(kinds["balances"], "moved")
        self.assertEqual(report["heat"], 3)

    def test_a_retype_and_a_removal_are_clashes(self):
        before = [_row("asset", "0", "address"), _row("paused", "1", "bool")]
        after = [_row("asset", "0", "uint256")]
        report = compare_layouts(before, after)
        kinds = {row["label"]: row["kind"] for row in report["clashes"]}
        self.assertEqual(kinds["asset"], "retyped")
        self.assertEqual(kinds["paused"], "removed")
        self.assertEqual(report["heat"], 3)

    def test_a_gap_can_be_replaced_without_moving_later_variables(self):
        before = [
            _row("totalAssets", "0", "uint256"),
            _row("__gap", "1", "uint256[50]"),
            _row("locked", "51", "uint256"),
        ]
        after = [
            _row("totalAssets", "0", "uint256"),
            _row("fee", "1", "uint256"),
            _row("locked", "51", "uint256"),
        ]
        report = compare_layouts(before, after)
        self.assertEqual(report["status"], "held")
        self.assertEqual(report["heat"], 0)

    def test_decimal_and_hex_slots_match(self):
        before = [_row("totalAssets", "1", "uint256")]
        after = [_row("totalAssets", "0x1", "uint256")]
        report = compare_layouts(before, after)
        self.assertEqual(report["status"], "held")
