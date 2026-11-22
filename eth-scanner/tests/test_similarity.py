"""Structural neighbors are leads. They do not add heat or change detectors."""

from __future__ import annotations

import unittest

from eth_scanner.heat import evidence_heat
from eth_scanner.research.detectors import run_custom_detectors
from eth_scanner.similarity.index import index_sources, search


_RENAMED = """
function collect(address asset, address who, uint256 qty) external {
    Token(asset).transferFrom(who, address(this), qty);
}
"""

_REORDERED = """
function close(address oracle, address asset, address who, uint256 qty) external {
    uint256 paid = qty * quote;
    uint256 quote = IOracle(oracle).latestAnswer();
    Token(asset).transfer(who, paid);
}
"""

_UNRELATED = """
function name() external view returns (string memory) {
    return "plain";
}
"""

_ORACLE = """
function mark(address feed) external {
    uint256 answer = IFeed(feed).latestAnswer();
    require(answer > 0);
}
"""


class SimilarityTests(unittest.TestCase):
    def test_renamed_function_is_a_lead_with_no_heat(self) -> None:
        report = search(_RENAMED)
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["candidates"][0]["neighbor"], "shape:external-transfer-from")
        self.assertGreaterEqual(report["candidates"][0]["score"], 0.72)
        self.assertEqual(report["candidates"][0]["heat_contribution"], 0)

    def test_reordered_body_still_matches_the_shape(self) -> None:
        report = search(_REORDERED)
        self.assertEqual(report["candidates"][0]["neighbor"], "shape:price-then-move")

    def test_unrelated_function_is_not_a_neighbor(self) -> None:
        report = search(_UNRELATED)
        self.assertEqual(report["status"], "no-neighbor")
        self.assertEqual(report["candidates"], [])

    def test_extra_confirmed_text_can_join_the_index(self) -> None:
        catalog = index_sources([{
            "id": "confirmed:1",
            "source": _ORACLE,
        }])
        report = search(
            "function read(address src) external { uint256 v = IFeed(src).latestAnswer(); require(v > 0); }",
            catalog,
        )
        self.assertEqual(report["candidates"][0]["neighbor"], "confirmed:1")
        self.assertEqual(report["heat_contribution"], 0)

    def test_similarity_does_not_change_detector_leads_or_heat(self) -> None:
        before = run_custom_detectors(address="0x" + "11" * 20, source=_RENAMED)
        search(_RENAMED)
        after = run_custom_detectors(address="0x" + "11" * 20, source=_RENAMED)
        self.assertEqual([row.id for row in before], [row.id for row in after])
        total, _ = evidence_heat(
            funds_usd=1_000_000,
            invariant_results=[{"id": "solvency", "status": "failed", "source": "live"}],
        )
        self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
