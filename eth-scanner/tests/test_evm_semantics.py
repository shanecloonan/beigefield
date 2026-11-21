"""Arbitrum block meaning, precompiles, and BNB fork flags. No heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chains.evm_semantics import (
    ARBSYS,
    interpret_block,
    is_precompile,
    scan_bsc_forks,
)

UNI = """
contract UniswapV2Pair {
    function getReserves() external view returns (uint112, uint112, uint32) {}
    uint256 constant FEE = 997;
}
"""
PANCAKE = """
contract PancakePair {
    function getReserves() external view returns (uint112, uint112, uint32) {}
}
"""
VENUS = """
contract VToken {
    function borrow(uint256 amount) external returns (uint256) {}
}
"""
COMPOUND = """
contract CToken {
    function borrow(uint256 amount) external returns (uint256) {}
}
"""


class EvmSemantics(unittest.TestCase):
    def test_arbitrum_keeps_l2_and_l1_apart(self):
        report = interpret_block("arbitrum", {"number": "0x10", "l1BlockNumber": "0x20"})
        self.assertEqual(report["head_kind"], "l2")
        self.assertEqual(report["head"], 16)
        self.assertEqual(report["l1_block"], 32)
        self.assertEqual(report["l1_source"], "l1BlockNumber")
        self.assertEqual(report["number_opcode"], "l1")
        self.assertEqual(report["heat_contribution"], 0)
        self.assertFalse(report["degraded"])

    def test_a_missing_l1_block_stays_unknown(self):
        report = interpret_block("arb", {"number": "0x10"})
        self.assertIsNone(report["l1_block"])
        self.assertEqual(report["l1_source"], "unknown")
        self.assertTrue(report["degraded"])
        self.assertEqual(report["heat_contribution"], 0)

    def test_ethereum_and_bsc_are_not_treated_as_l2(self):
        eth = interpret_block("ethereum", {"number": "0x5"})
        bsc = interpret_block("bsc", {"number": "0x5", "l1BlockNumber": "0x9"})
        self.assertEqual(eth["head_kind"], "chain")
        self.assertEqual(eth["l1_source"], "not-an-l2")
        self.assertIsNone(eth["l1_block"])
        self.assertEqual(bsc["l1_source"], "not-an-l2")
        self.assertFalse(is_precompile("ethereum", ARBSYS))
        self.assertFalse(is_precompile("bsc", "0x64"))
        self.assertTrue(is_precompile("arbitrum", "0x64"))
        self.assertTrue(is_precompile("base", "0x4200000000000000000000000000000000000015"))
        self.assertFalse(is_precompile("bsc", "0x4200000000000000000000000000000000000015"))

    def test_fork_flags_are_evidence_only(self):
        pancake = scan_bsc_forks(PANCAKE)
        venus = scan_bsc_forks(VENUS)
        self.assertEqual(pancake[0]["rule"], "pancake-fork")
        self.assertEqual(venus[0]["rule"], "venus-fork")
        self.assertTrue(all(row["heat_contribution"] == 0 for row in pancake + venus))
        self.assertEqual(scan_bsc_forks(UNI), [])
        self.assertEqual(scan_bsc_forks(COMPOUND), [])


if __name__ == "__main__":
    unittest.main()
