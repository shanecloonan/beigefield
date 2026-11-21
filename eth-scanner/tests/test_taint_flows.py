"""Taint leads name a sink. They do not add heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.taint import taint_report, trace_source


class TaintFlows(unittest.TestCase):
    def test_a_variable_delegatecall_is_a_lead(self):
        source = "contract C { function poke(address impl) public { impl.delegatecall(''); } }"
        flows = trace_source(source)
        self.assertEqual(flows, [{
            "function": "poke",
            "sink": "delegatecall",
            "detail": "impl",
            "heat_contribution": 0,
        }])

    def test_delegatecall_to_this_is_quiet(self):
        source = "contract C { function poke() public { address(this).delegatecall(''); } }"
        self.assertEqual(trace_source(source), [])

    def test_an_oracle_read_before_a_value_move_is_a_lead(self):
        source = (
            "contract C { function pay(address payable to) public {"
            " (, int price,,,) = feed.latestRoundData();"
            " to.transfer(uint(price)); } }"
        )
        report = taint_report(source)
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["flows"][0]["sink"], "value-after-oracle")
        self.assertEqual(report["flows"][0]["function"], "pay")

    def test_a_value_move_without_an_oracle_is_quiet(self):
        source = "contract C { function pay(address payable to) public { to.transfer(1); } }"
        self.assertEqual(trace_source(source), [])


if __name__ == "__main__":
    unittest.main()
