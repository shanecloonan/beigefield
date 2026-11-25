"""SWC and incident-family patterns. No writeups and no exploit text."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.benchmark.defihacklabs import incident_family, parse_index
from eth_scanner.heat import evidence_heat
from eth_scanner.logic.corpus import corpus_report, load_families, scan_source


class Patterns(unittest.TestCase):
    def test_unguarded_initializer_counts(self):
        source = "function initialize() public { owner = msg.sender; }"
        rows = scan_source(source)
        self.assertEqual([row["rule"] for row in rows], ["unprotected-initializer"])
        report = corpus_report(source)
        self.assertEqual(report["corpus_evidence"], 3)
        self.assertGreater(report["families_loaded"], 0)

    def test_initializer_guard_and_only_owner_are_dropped(self):
        guarded = "function initialize() public initializer { owner = msg.sender; }"
        owned = "function upgradeTo(address next) external onlyOwner { }"
        self.assertEqual(scan_source(guarded), [])
        self.assertEqual(scan_source(owned), [])

    def test_spot_needs_a_transfer_near_the_reserves_read(self):
        alone = "function price() external view returns (uint256) { return pair.getReserves(); }"
        paired = "function settle() external { pair.getReserves(); token.transfer(to, amount); }"
        self.assertEqual(scan_source(alone), [])
        self.assertEqual(scan_source(paired)[0]["rule"], "spot-price-value")

    def test_inflation_shape(self):
        source = "if (totalSupply() == 0) { _mint(msg.sender, shares); }"
        self.assertEqual(scan_source(source)[0]["rule"], "share-inflation-empty")

    def test_catalog_has_titles_only(self):
        rows = load_families()
        self.assertTrue(any(row["id"] == "defihacklabs-erc4626-inflation" for row in rows))
        blob = " ".join(row["title"] for row in rows).lower()
        self.assertNotIn("function ", blob)

    def test_incident_titles_do_not_gain_fields(self):
        rows = parse_index("[20220101 OracleProtocol](#x)\n[20220202 Example](#y)\n")
        self.assertEqual(rows[0], {"date": "2022-01-01", "name": "OracleProtocol"})
        self.assertEqual(incident_family("OracleProtocol"), "spot-price-value")
        self.assertEqual(incident_family("Example"), "")

    def test_same_rule_is_not_scored_twice(self):
        finding = {"engine": "corpus", "rule": "unprotected-initializer", "evidence": "pattern"}
        heat, bd = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            static_findings=[dict(finding, engine="slither")],
            corpus_findings=[finding],
        )
        self.assertEqual(bd["static_evidence"], 3)
        self.assertEqual(bd["corpus_evidence"], 0)
        self.assertEqual(heat, 3)


if __name__ == "__main__":
    unittest.main()
