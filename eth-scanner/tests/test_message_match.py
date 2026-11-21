"""Observed message ids can match across chains. They are not replayed."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.message_match import message_match

IDENT = "0x" + "ab" * 32
OTHER = "0x" + "cd" * 32


class MessageMatch(unittest.TestCase):
    def test_the_same_id_on_two_chains_is_a_lead(self):
        result = message_match([
            {"chain": "ethereum", "id": IDENT, "payload": "0x" + "11" * 80},
            {"chain": "arb", "id": IDENT.upper()},
        ])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["multiple"], 1)
        self.assertEqual(result["matches"][0]["chains"], ["arbitrum", "ethereum"])
        self.assertEqual(result["matches"][0]["relation"], "seen-on-multiple-chains")
        self.assertEqual(result["heat_contribution"], 0)
        self.assertNotIn("payload", result["matches"][0])

    def test_one_sighting_stays_seen_once(self):
        result = message_match([{"chain": "base", "id": OTHER}])
        self.assertEqual(result["matches"][0]["relation"], "seen-once")
        self.assertEqual(result["multiple"], 0)
        self.assertEqual(result["heat_contribution"], 0)

    def test_calldata_is_dropped(self):
        result = message_match([{"chain": "ethereum", "id": "0x" + "11" * 80}])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["dropped"], 1)
        self.assertEqual(result["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
