"""Solana discovery records dollars and adds no heat. No network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chains.solana_discover import RpcLimited, _program_id, discover, enqueue
from eth_scanner.store.supabase import MemoryStore

MARINADE = "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
WSOL = "So11111111111111111111111111111111111111112"


def _protocols():
    return [
        {"name": "Marinade", "address": MARINADE, "chains": ["Solana"], "tvl": 250_000, "category": "Liquid Staking"},
        {"name": "Dust", "address": TOKEN, "chains": ["Solana"], "tvl": 40},
        {"name": "Multi", "address": WSOL, "chains": ["Ethereum", "Solana"], "tvl": 9_000_000, "chainTvls": {"Solana": 1_500}},
        {"name": "Eth only", "address": "0x" + "ab" * 20, "chains": ["Ethereum"], "tvl": 5_000_000},
    ]


class SolanaDiscover(unittest.TestCase):
    def test_keeps_solana_dollars_and_adds_no_heat(self):
        calls = []

        def rpc(method, params):
            calls.append(method)
            if method == "getAccountInfo" and params[0] == WSOL:
                raise RpcLimited("429")
            if method == "getAccountInfo":
                return {"value": {"executable": True, "owner": "BPFLoaderUpgradeab1e11111111111111111111111", "lamports": 42}}
            if method == "getProgramAccounts":
                return [{"pubkey": WSOL}]
            if method == "getTokenAccountBalance":
                return {"value": {"amount": "1000", "uiAmount": 0.001, "decimals": 6}}
            raise AssertionError(method)

        report = discover(limit=10, fetch=lambda _url: _protocols(), rpc=rpc, pause=lambda _s: None)
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["degraded"], True)
        names = [row["name"] for row in report["candidates"]]
        self.assertEqual(names, ["Marinade", "Multi"])
        self.assertEqual(report["candidates"][0]["funds_usd"], 250000)
        self.assertEqual(report["candidates"][0]["executable"], True)
        self.assertEqual(report["candidates"][0]["token_accounts"][0]["ui_amount"], 0.001)
        self.assertTrue(all(row["heat_contribution"] == 0 for row in report["candidates"]))
        self.assertNotIn("sendTransaction", calls)
        multi = report["candidates"][1]
        self.assertEqual(multi["funds_usd"], 1500)
        self.assertTrue(multi["degraded"])

        store = MemoryStore()
        enqueue(store, report)
        self.assertEqual(store.claim_pending(10, "eth"), [])
        saved = store.get_target(MARINADE, chain="solana")
        self.assertEqual(saved["chain"], "solana")
        self.assertEqual(saved["funds_usd"], 250000)
        self.assertEqual(saved["heat"], 0)
        self.assertEqual(_program_id("solana:" + MARINADE), MARINADE)


if __name__ == "__main__":
    unittest.main()
