"""Chain names default to ethereum. Solana does not enter the ETH claim path."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chains.registry import normalize_chain, normalize_solana_address, row_chain
from eth_scanner.store.supabase import MemoryStore, normalize_address
from eth_scanner.types import Target

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ETH = "0x" + "ab" * 20


class ChainRegistry(unittest.TestCase):
    def test_blank_chain_is_ethereum(self):
        self.assertEqual(normalize_chain(None), "ethereum")
        self.assertEqual(normalize_chain(" ETH "), "ethereum")
        self.assertEqual(row_chain({}), "ethereum")
        self.assertEqual(normalize_chain("solana"), "solana")

    def test_solana_address_keeps_its_case(self):
        self.assertEqual(normalize_solana_address(TOKEN_PROGRAM), TOKEN_PROGRAM)
        with self.assertRaises(ValueError):
            normalize_solana_address("not-a-program")
        self.assertEqual(normalize_address(ETH), ETH)

    def test_ethereum_claim_skips_a_solana_target(self):
        store = MemoryStore()
        store.upsert_target(Target(address=ETH, status="pending"))
        store.upsert_target(Target(address=TOKEN_PROGRAM, chain="solana", status="pending"))
        claimed = store.claim_pending(10, "eth-worker")
        self.assertEqual([row["address"] for row in claimed], [ETH])
        self.assertEqual(store.get_target(TOKEN_PROGRAM, chain="solana")["status"], "pending")
        self.assertEqual(store.get_target(TOKEN_PROGRAM, chain="solana")["chain"], "solana")


if __name__ == "__main__":
    unittest.main()
