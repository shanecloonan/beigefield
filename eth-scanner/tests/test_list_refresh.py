"""Fresh list picks stay above the floor and out of exploited notes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.feed.list_refresh import chain_of_reason, choose_lists


def _row(address: str, usd: float, **extra):
    base = {
        "address": address,
        "protocol": "Example",
        "usd": usd,
        "chain": "ethereum",
        "verified": True,
        "has_code": True,
        "reason": "vault;upgradeable-proxy",
        "dollars_source": "defillama",
        "not_recently_scanned": True,
    }
    base.update(extra)
    return base


class ListRefresh(unittest.TestCase):
    def test_drops_exploited_and_thin_rows(self):
        rows = [
            _row("0x" + "11" * 20, 5000),
            _row("0x" + "22" * 20, 80),
            _row("0x" + "33" * 20, 4000, reason="past-hack;vault"),
            _row("0x" + "44" * 20, 400, verified=False, has_code=False),
            _row("0x" + "55" * 20, 700, verified=False, has_code=True, reason="oracle;lending"),
        ]
        picked = choose_lists(rows, list1_count=5, list2_count=5)
        one = [row["address"] for row in picked["list-1"]]
        two = [row["address"] for row in picked["list-2"]]
        self.assertEqual(one, ["0x" + "11" * 20])
        self.assertEqual(two, ["0x" + "55" * 20])
        self.assertIn("signals=oracle,lending", picked["list-2"][0]["candidate_reason"])
        self.assertIn("not-exploited", picked["list-1"][0]["candidate_reason"])
        self.assertNotIn("past-hack", picked["list-1"][0]["candidate_reason"])

    def test_a_chain_row_can_fill_either_band(self):
        picked = choose_lists([
            _row("0x" + "ab" * 20, 2500, chain="base", reason="vault", dollars_source="defillama-base"),
            _row("0x" + "cd" * 20, 150, chain="arbitrum", reason="oracle", dollars_source="defillama-arbitrum"),
        ], list1_count=2, list2_count=2)
        self.assertEqual(picked["list-1"][0]["chain"], "base")
        self.assertEqual(picked["list-2"][0]["chain"], "arbitrum")
        self.assertIn("chain=base", picked["list-1"][0]["candidate_reason"])
        self.assertEqual(chain_of_reason(picked["list-1"][0]["candidate_reason"]), "base")
        self.assertEqual(chain_of_reason("verified;signals=vault"), "ethereum")


if __name__ == "__main__":
    unittest.main()
