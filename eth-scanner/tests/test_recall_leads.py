"""Adapter addresses and recall leads. No network and no heat."""

from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark import adapter_join, incident_recall as recall
from eth_scanner.benchmark.leads import has_benchmark_lead


_TOKEN = (
    "contract T { function transfer(address a, uint256 n) public {} "
    "function approve(address a, uint256 n) public {} }"
)
_SHARE = """
contract V {
    function deposit(uint256 assets) external {
        uint256 bal = token.balanceOf(address(this));
        _mint(msg.sender, bal);
    }
    function _mint(address a, uint256 n) internal { totalSupply += n; }
}
"""
_OFFSET = """
contract V {
    function deposit(uint256 assets) external {
        uint256 bal = token.balanceOf(address(this));
        _mint(msg.sender, bal + 10 ** _decimalsOffset());
    }
}
"""
_SPOT = """
contract P {
    function swap(uint256 a) external {
        (uint112 r0, uint112 r1,) = pair.getReserves();
        uint256 out = r0 / r1;
        token.transfer(msg.sender, out);
    }
}
"""
_ORACLE = _SPOT + " function peek() external view returns (uint256) { return feed.latestRoundData(); }"
_REENTER = """
contract R {
    function withdraw(uint256 a) external {
        (bool ok,) = msg.sender.call("");
        balances[msg.sender] = 0;
    }
}
"""
_ORDERED = """
contract R {
    function withdraw(uint256 a) external {
        balances[msg.sender] = 0;
        (bool ok,) = msg.sender.call("");
    }
}
"""
_READONLY = """
contract R {
    function price() external view returns (uint256) {
        return token.balanceOf(address(this));
    }
    function withdraw(uint256 a) external {
        (bool ok,) = msg.sender.call("");
    }
}
"""


class RecallLeads(unittest.TestCase):
    def test_shapes_that_count_and_the_ones_that_do_not(self):
        self.assertTrue(has_benchmark_lead(_SHARE))
        self.assertFalse(has_benchmark_lead(_OFFSET))
        self.assertTrue(has_benchmark_lead(_SPOT))
        self.assertFalse(has_benchmark_lead(_ORACLE))
        self.assertTrue(has_benchmark_lead(_REENTER))
        self.assertFalse(has_benchmark_lead(_ORDERED))
        self.assertTrue(has_benchmark_lead(_READONLY))
        self.assertFalse(has_benchmark_lead(_TOKEN))
        self.assertFalse(recall.score_source("0x" + "11" * 20, _TOKEN))

    def test_adapter_addresses_follow_the_chain_and_skip_the_token(self):
        text = textwrap.dedent("""
        module.exports = {
          ethereum: { vault: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' },
          bsc: { vault: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' },
        }
        """)
        original = adapter_join._fetch_adapter
        adapter_join._fetch_adapter = lambda module: text
        try:
            got = adapter_join.adapter_addresses(
                "example/index.js",
                "ethereum",
                skip="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        finally:
            adapter_join._fetch_adapter = original
        self.assertEqual(got, [])
        adapter_join._fetch_adapter = lambda module: text.replace(
            "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "0xcccccccccccccccccccccccccccccccccccccccc",
        )
        try:
            got = adapter_join.adapter_addresses("example/index.js", "ethereum", skip="0x" + "11" * 20)
        finally:
            adapter_join._fetch_adapter = original
        self.assertEqual(got, ["0xcccccccccccccccccccccccccccccccccccccccc"])

    def test_chain_id_windows_are_kept(self):
        text = (
            "{ chainId: 1, vault: '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' }\n"
            "{ chainId: 56, vault: '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' }\n"
        )
        original = adapter_join._fetch_adapter
        adapter_join._fetch_adapter = lambda module: text
        try:
            got = adapter_join.adapter_addresses("yearn/index.js", "bsc")
        finally:
            adapter_join._fetch_adapter = original
        self.assertEqual(got, ["0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"])

    def test_a_cold_token_can_be_caught_from_the_adapter(self):
        listed = "0x" + "11" * 20
        vault = "0x" + "22" * 20
        rows = [{
            "chain": "ethereum",
            "address": listed,
            "pre_incident": True,
            "classification": "Oracle Manipulation",
            "technique": "Spot Price Manipulation",
            "adapter": "example/index.js",
            "heat_contribution": 0,
        }]

        def fetch(chain, address):
            return _TOKEN if address == listed else _REENTER

        original = adapter_join.adapter_addresses
        adapter_join.adapter_addresses = lambda module, chain, skip="": [vault]
        try:
            recall.mark_scored(rows, fetch_source=fetch, rpc_for=lambda chain: "")
        finally:
            adapter_join.adapter_addresses = original
        self.assertEqual(rows[0]["bucket"], "token")
        self.assertTrue(rows[0]["adapter_hit"])
        self.assertTrue(rows[0]["hot"])
        self.assertEqual(rows[0]["heat_contribution"], 0)
        report = recall.recall_report(rows, incidents=1)
        self.assertEqual(report["adapter_hits"], 1)
        self.assertEqual(report["hot"], 1)
        self.assertEqual(report["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
