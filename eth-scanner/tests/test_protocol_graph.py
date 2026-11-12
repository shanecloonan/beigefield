"""Phase C protocol graph + risk scoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.invariants.live import LiveInvariantResult
from eth_scanner.protocol_graph.builder import build_protocol_graph
from eth_scanner.protocol_graph.risk import score_graph_risks


class GraphBuild(unittest.TestCase):
    def test_proxy_token_oracle_edges(self):
        with mock.patch(
            "eth_scanner.protocol_graph.builder.run_live_invariants",
            return_value=[
                LiveInvariantResult(
                    "roles-owner", "owner", "held", "owner=0x2222 kind=eoa",
                    extras={"owner": "0x2222222222222222222222222222222222222222", "kind": "eoa"},
                )
            ],
        ):
            g = build_protocol_graph(
                "0x1111111111111111111111111111111111111111",
                source="interface Aggregator { function latestAnswer() external; }\n",
                is_proxy=True,
                implementation="0x3333333333333333333333333333333333333333",
                funds_breakdown=[{"token": "0x4444444444444444444444444444444444444444", "symbol": "USDC", "usd": 1e6}],
                contract_class="vault",
            )
        kinds = {n.kind for n in g.nodes}
        self.assertIn("implementation", kinds)
        self.assertIn("admin", kinds)
        self.assertIn("token", kinds)
        self.assertIn("oracle", kinds)
        risks = score_graph_risks(g, funds_usd=1_000_000, source="uses chainlink Aggregator")
        ids = {f["id"] for f in risks["factors"]}
        self.assertIn("eoa-admin-large-funds", ids)
        self.assertIn("oracle-dependency", ids)
        self.assertGreater(risks["funds_times_likelihood"], 0)


if __name__ == "__main__":
    unittest.main()
