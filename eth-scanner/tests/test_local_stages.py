"""Local stages finish without changing evidence heat."""

from __future__ import annotations

import unittest

from eth_scanner.stages.fusion import annotate_stages
from eth_scanner.stages.local import finish_local_stages

_SOURCE = """
contract Pool {
    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
contract Router {
    function deposit(address to, uint256 amount) external {
        Pool(pool).mint(to, amount);
    }
    function collect(address asset, address who, uint256 qty) external {
        Token(asset).transferFrom(who, address(this), qty);
    }
}
"""


class LocalStageTests(unittest.TestCase):
    def test_a_neighbor_and_a_path_do_not_change_heat(self) -> None:
        start = annotate_stages({"privileged_callable": 4, "total": 4}, heat=4)
        done = finish_local_stages(start, _SOURCE)
        self.assertEqual(done["fused_heat"], 4)
        self.assertNotIn("similarity", done["pending_stages"])
        self.assertNotIn("cross-contract", done["pending_stages"])
        self.assertIn("halmos", done["pending_stages"])
        self.assertEqual(done["score_state"], "provisional")
        self.assertTrue(done["cross_contract"]["leads"])
        self.assertEqual(done["cross_contract"]["heat_contribution"], 0)
        self.assertEqual(done["similarity"]["heat_contribution"], 0)

    def test_missing_source_skips_the_local_stages(self) -> None:
        start = annotate_stages({"invariants_failed": 3, "total": 3}, heat=3)
        done = finish_local_stages(start, "")
        self.assertEqual(done["fused_heat"], 3)
        self.assertNotIn("similarity", done["pending_stages"])
        self.assertNotIn("cross-contract", done["pending_stages"])
        self.assertIn("fuzz", done["pending_stages"])


if __name__ == "__main__":
    unittest.main()
