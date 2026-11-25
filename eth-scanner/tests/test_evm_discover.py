"""BNB, Arbitrum, and Base discovery. Ethereum rows and the CU example stay put."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chain.cu_budget import MONTHLY_SCAN_EXAMPLE, chain_daily_scans, multi_chain_monthly_cu
from eth_scanner.chains.evm_discover import discover, enqueue, select_work
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import Target

ETH = "0x" + "ab" * 20
BSC_TOKEN = "0x" + "11" * 20
BSC_CODE = "0x" + "22" * 20
SHARED = "0x" + "33" * 20


def _protocols():
    return [
        {
            "name": "Only BNB",
            "address": "bsc:" + BSC_CODE,
            "chains": ["Binance", "Ethereum"],
            "chainTvls": {"Binance": 250000, "Ethereum": 9_000_000},
        },
        {
            "name": "Dust",
            "address": "bsc:" + BSC_TOKEN,
            "chains": ["Binance"],
            "chainTvls": {"Binance": 40},
        },
        {
            "name": "Multi bare",
            "address": "0x" + "44" * 20,
            "chains": ["Binance", "Ethereum"],
            "chainTvls": {"Binance": 800000},
        },
        {
            "name": "Single",
            "address": "0x" + "55" * 20,
            "chains": ["Binance"],
            "chainTvls": {"Binance": 1500, "total": 1500},
        },
    ]


class EvmDiscover(unittest.TestCase):
    def test_ethereum_discovery_is_refused(self):
        report = discover("ethereum", fetch=lambda _url: _protocols(), rpc=lambda *_a: "0x6001")
        self.assertTrue(report["refused"])
        self.assertEqual(report["candidates"], [])
        self.assertEqual(report["heat_contribution"], 0)

    def test_chain_tvl_ignores_bare_multi_chain_addresses(self):
        def rpc(url, method, params):
            self.assertNotIn("alchemy", url)
            self.assertEqual(method, "eth_getCode")
            if params[0] == BSC_CODE:
                return "0x60806040"
            return "0x"

        report = discover("bnb", fetch=lambda _url: _protocols(), rpc=rpc)
        names = [row["name"] for row in report["candidates"]]
        self.assertEqual(names, ["Only BNB", "Single"])
        self.assertEqual(report["candidates"][0]["funds_usd"], 250000)
        self.assertTrue(report["candidates"][0]["has_code"])
        self.assertFalse(report["candidates"][1]["has_code"])
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["ethereum_monthly_cu"], MONTHLY_SCAN_EXAMPLE["monthly_cu"])
        self.assertTrue(report["within_cap"])
        self.assertLess(report["monthly_cu"], MONTHLY_SCAN_EXAMPLE["org_cap_cu"])

    def test_enqueue_does_not_change_an_ethereum_row(self):
        store = MemoryStore()
        store.upsert_target(Target(address=SHARED, status="pending", funds_usd=10))
        report = discover(
            "bsc",
            fetch=lambda _url: [{
                "name": "Shared",
                "address": "bsc:" + SHARED,
                "chains": ["Binance"],
                "chainTvls": {"Binance": 5000},
            }],
            rpc=lambda *_a: "0x6080",
        )
        saved = enqueue(store, report)
        self.assertEqual(saved["enqueued"], [SHARED])
        eth = store.get_target(SHARED)
        self.assertEqual(eth["chain"], "ethereum")
        self.assertEqual(eth["funds_usd"], 10)
        self.assertEqual(eth["status"], "pending")
        bsc = store.get_target(SHARED, chain="bsc")
        self.assertEqual(bsc["chain"], "bsc")
        self.assertEqual(bsc["funds_usd"], 5000)
        self.assertEqual(bsc["heat"], 0)
        claimed = store.claim_pending(10, "eth-worker")
        self.assertEqual([row["address"] for row in claimed], [SHARED])
        self.assertEqual(store.get_target(SHARED, chain="bsc")["status"], "pending")

    def test_no_code_is_not_queued_and_the_daily_cap_holds(self):
        store = MemoryStore()
        report = discover("base", fetch=lambda _url: [{
            "name": "Empty",
            "address": "base:" + BSC_TOKEN,
            "chains": ["Base"],
            "chainTvls": {"Base": 9000},
        }], rpc=lambda *_a: "0x")
        saved = enqueue(store, report)
        self.assertEqual(saved["enqueued"], [])
        self.assertEqual(chain_daily_scans("ethereum"), 50)
        self.assertEqual(chain_daily_scans("arbitrum"), 8)
        self.assertEqual(chain_daily_scans("optimism"), 4)
        self.assertEqual(chain_daily_scans("polygon"), 4)
        rows = [{"address": "0x%040x" % i, "chain": "arbitrum", "status": "pending"} for i in range(1, 12)]
        rows.append({"address": ETH, "chain": "ethereum", "status": "pending"})
        picked = select_work(rows, "arbitrum")
        self.assertEqual(len(picked), 8)
        self.assertEqual(select_work(rows, "ethereum"), [])
        plan = multi_chain_monthly_cu()
        self.assertEqual(plan["ethereum_monthly_cu"], MONTHLY_SCAN_EXAMPLE["monthly_cu"])
        self.assertTrue(plan["within_cap"])


if __name__ == "__main__":
    unittest.main()
