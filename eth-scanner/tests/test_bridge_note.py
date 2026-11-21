"""A bridge name is a witness. No call is built and heat stays 0."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.advanced.bridge_note import bridge_note


class BridgeNote(unittest.TestCase):
    def test_a_bridge_role_is_a_witness(self):
        result = bridge_note(["vault", "bridge"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["roles"], ["bridge"])
        self.assertEqual(result["heat_contribution"], 0)
        self.assertNotIn("calldata", result)
        self.assertNotIn("data", result)

    def test_a_source_word_is_kept_and_the_source_is_not(self):
        result = bridge_note([], "contract Inbox { function messenger() external {} }")
        self.assertEqual(result["names"], ["inbox", "messenger"])
        self.assertNotIn("function", " ".join(result["names"]))
        self.assertEqual(result["heat_contribution"], 0)

    def test_no_name_skips(self):
        result = bridge_note(["vault"], "contract Vault { function totalAssets() external {} }")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["heat_contribution"], 0)


if __name__ == "__main__":
    unittest.main()
