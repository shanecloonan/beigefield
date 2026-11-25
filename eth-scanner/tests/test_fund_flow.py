"""Cross-contract edges are leads. Heat stays 0 and bodies are not stored."""

from __future__ import annotations

import json
import unittest

from eth_scanner.flow.graph import build_flow, role_of

SOURCE = """
contract Vault {
    function poke() external {
        uint256 price = IOracle(0x1111111111111111111111111111111111111111).latestAnswer();
        IPair(0x2222222222222222222222222222222222222222).getReserves();
        IERC20(0x3333333333333333333333333333333333333333).transfer(msg.sender, price);
        // notStoredBody
    }
    function allow() external {
        token.approve(0x4444444444444444444444444444444444444444, 1);
    }
}
"""


class FundFlowTests(unittest.TestCase):
    def test_roles_follow_the_interface_name(self):
        self.assertEqual(role_of("IOracle.latestAnswer"), "oracle")
        self.assertEqual(role_of("IPair.getReserves"), "amm")
        self.assertEqual(role_of("IBridge.lock"), "bridge")
        self.assertEqual(role_of("helper"), "external")

    def test_a_value_path_is_scored_and_the_body_is_dropped(self):
        report = build_flow(SOURCE, address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(report["heat_contribution"], 0)
        self.assertTrue(report["flow"])
        self.assertGreater(report["flow_score"], 0)
        relations = {edge["relation"] for edge in report["edges"]}
        self.assertIn("approves", relations)
        self.assertIn("moves-value", relations)
        roles = {node["role"] for node in report["nodes"]}
        self.assertIn("oracle", roles)
        self.assertIn("amm", roles)
        self.assertTrue(report["paths"])
        self.assertNotIn("notStoredBody", json.dumps(report))

    def test_bytecode_selectors_are_a_surface_note(self):
        report = build_flow("", selectors=["latestRoundData()", "transfer(address,uint256)"])
        self.assertEqual(report["heat_contribution"], 0)
        ids = [node["id"] for node in report["nodes"]]
        self.assertIn("surface", ids)
        self.assertLessEqual(report["flow_score"], 6)


if __name__ == "__main__":
    unittest.main()
