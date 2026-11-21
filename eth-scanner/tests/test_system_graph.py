"""A cross-chain protocol graph records roles and adds no heat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.system_graph import system_graph

ETH = "0x" + "ab" * 20
ARB = "0x" + "cd" * 20


class SystemGraph(unittest.TestCase):
    def test_two_chains_make_one_cross_chain_edge(self):
        result = system_graph([
            {"chain": "ethereum", "address": ETH, "role": "vault", "message": "0xdead"},
            {"chain": "arb", "address": ARB, "role": "strategy"},
        ])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["heat_contribution"], 0)
        self.assertEqual(result["cross_chain"], 1)
        self.assertEqual(result["edges"][0]["relation"], "cross-chain")
        self.assertNotIn("message", result)
        self.assertNotIn("calldata", result["nodes"][0])

    def test_one_chain_stays_same_chain(self):
        other = "0x" + "11" * 20
        result = system_graph([
            {"chain": "ethereum", "address": ETH, "role": "vault"},
            {"chain": "eth", "address": other, "role": "oracle"},
        ])
        self.assertEqual(result["edges"][0]["relation"], "same-chain")
        self.assertEqual(result["cross_chain"], 0)
        self.assertEqual(result["heat_contribution"], 0)

    def test_an_alias_collapses_onto_one_node(self):
        result = system_graph([
            {"chain": "arbitrum", "address": ARB, "role": "vault"},
            {"chain": "arb", "address": ARB.upper(), "role": "oracle"},
        ])
        self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(result["nodes"][0]["roles"], ["vault", "oracle"])
        self.assertEqual(result["edges"], [])

    def test_empty_input_skips(self):
        result = system_graph([{"chain": "ethereum", "address": "not-an-address"}])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(result["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
