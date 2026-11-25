"""Optimism, Polygon, per-chain lease, fork plan, and source lookup."""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chain.cu_budget import CuBudget, discover_run_cap
from eth_scanner.chains.evm_discover import discover
from eth_scanner.chains.evm_semantics import interpret_block
from eth_scanner.chains.fork_plan import plan_fork
from eth_scanner.chains.source_verify import source_status
from eth_scanner.feed.runner import (
    CYCLE_CURSOR_ID,
    acquire_scan_cycle,
    cycle_cursor_id,
    release_scan_cycle,
)
from eth_scanner.store.supabase import MemoryStore

ADDR = "0x" + "ab" * 20


class ExtraChains(unittest.TestCase):
    def test_optimism_tvl_stays_off_the_ethereum_row(self):
        report = discover("op", fetch=lambda _url: [{
            "name": "Op Vault",
            "address": "optimism:" + ADDR,
            "chains": ["Optimism", "Ethereum"],
            "chainTvls": {"Optimism": 4200, "Ethereum": 9},
        }], rpc=lambda *_args: "0x1234")
        self.assertEqual(report["chain"], "optimism")
        self.assertEqual(report["chain_id"], 10)
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["candidates"][0]["funds_usd"], 4200.0)
        self.assertTrue(report["candidates"][0]["has_code"])
        self.assertGreater(report["cu_spent"], 0)
        self.assertLessEqual(report["cu_spent"], report["cu_cap"])

    def test_polygon_block_is_its_own_head_and_optimism_is_an_l2(self):
        polygon = interpret_block("matic", {"number": "0x10"})
        optimism = interpret_block("optimism", {"number": "0x10"})
        self.assertEqual(polygon["head_kind"], "chain")
        self.assertEqual(polygon["heat_contribution"], 0)
        self.assertEqual(optimism["head_kind"], "l2")
        self.assertEqual(optimism["l1_source"], "L1Block-precompile")

    def test_discover_cap_stops_before_the_next_code_read(self):
        guard = CuBudget(19)
        self.assertTrue(guard.allow("eth_getCode"))
        guard.charge("eth_getCode")
        self.assertFalse(guard.allow("eth_getCode"))
        self.assertEqual(discover_run_cap("ethereum"), 0)
        self.assertEqual(discover_run_cap("polygon"), 2000)


class ChainLease(unittest.TestCase):
    def test_another_chain_does_not_take_the_ethereum_lease(self):
        store = MemoryStore()
        self.assertEqual(cycle_cursor_id("ethereum"), CYCLE_CURSOR_ID)
        self.assertEqual(cycle_cursor_id("op"), "scan-cycle:optimism")
        optimism = acquire_scan_cycle(store, wait_s=0.2, poll_s=0.05, chain="optimism")
        ethereum = acquire_scan_cycle(store, wait_s=0.2, poll_s=0.05)
        self.assertEqual(store.get_backfill("scan-cycle:optimism")["id"], "scan-cycle:optimism")
        self.assertEqual(store.get_backfill(CYCLE_CURSOR_ID)["id"], CYCLE_CURSOR_ID)
        self.assertEqual(store.get_backfill("scan-cycle:optimism")["stats"]["lease_owner"], optimism)
        self.assertEqual(store.get_backfill(CYCLE_CURSOR_ID)["stats"]["lease_owner"], ethereum)
        release_scan_cycle(store, optimism, chain="optimism")
        release_scan_cycle(store, ethereum)
        held = MemoryStore()
        until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        held.upsert_backfill({
            "id": CYCLE_CURSOR_ID,
            "stats": {"lease_owner": "monitor", "lease_until": until},
        })
        base = acquire_scan_cycle(held, wait_s=0.2, poll_s=0.05, chain="base")
        self.assertEqual(held.get_backfill("scan-cycle:base")["stats"]["lease_owner"], base)
        with self.assertRaises(TimeoutError):
            acquire_scan_cycle(held, wait_s=0.15, poll_s=0.05)
        release_scan_cycle(held, base, chain="base")


class ForkAndSource(unittest.TestCase):
    def test_fork_plan_hides_the_url_and_binds_loopback(self):
        previous = os.environ.get("OPTIMISM_RPC_URL")
        os.environ["OPTIMISM_RPC_URL"] = "https://opt-mainnet.g.alchemy.com/v2/hidden-key"
        seen = []

        def runner(argv):
            seen.append(argv)
            return {"chain_id": 10, "sent": False}

        try:
            planned = plan_fork("optimism")
            ran = plan_fork("optimism", execute=True, runner=runner, binary="/tmp/anvil")
        finally:
            if previous is None:
                os.environ.pop("OPTIMISM_RPC_URL", None)
            else:
                os.environ["OPTIMISM_RPC_URL"] = previous
        self.assertNotIn("hidden-key", json.dumps(planned))
        self.assertNotIn("hidden-key", json.dumps(ran))
        self.assertEqual(planned["argv"][planned["argv"].index("--fork-url") + 1], "<rpc>")
        self.assertEqual(seen[0][seen[0].index("--host") + 1], "127.0.0.1")
        self.assertEqual(seen[0][seen[0].index("--accounts") + 1], "0")
        self.assertNotIn("sendTransaction", " ".join(seen[0]))
        self.assertEqual(ran["heat_contribution"], 0)
        self.assertFalse(ran["refused"])

    def test_ethereum_fork_stays_unset_without_its_own_url(self):
        previous = os.environ.pop("ETH_RPC_URL", None)
        try:
            report = plan_fork("ethereum")
        finally:
            if previous is not None:
                os.environ["ETH_RPC_URL"] = previous
        self.assertEqual(report["rpc_source"], "unset")
        self.assertTrue(report["skipped"])
        self.assertEqual(report["heat_contribution"], 0)

    def test_source_lookup_uses_etherscan_then_sourcify_without_leaking_the_key(self):
        previous = os.environ.pop("ETHERSCAN_API_KEYS", None)
        previous_one = os.environ.pop("ETHERSCAN_API_KEY", None)
        try:
            os.environ["ETHERSCAN_API_KEYS"] = "secret-key"

            def etherscan(url):
                self.assertIn("secret-key", url)
                self.assertIn("chainid=137", url)
                return {"status": "1", "result": [{"SourceCode": "contract C {}", "ContractName": "C"}]}

            keyed = source_status("polygon", ADDR, fetch=etherscan)
            os.environ.pop("ETHERSCAN_API_KEYS", None)

            def sourcify(url):
                self.assertIn("sourcify.dev", url)
                self.assertIn("/8453/", url)
                return {"match": "exact_match"}

            free = source_status("base", ADDR, fetch=sourcify)
        finally:
            if previous is None:
                os.environ.pop("ETHERSCAN_API_KEYS", None)
            else:
                os.environ["ETHERSCAN_API_KEYS"] = previous
            if previous_one is None:
                os.environ.pop("ETHERSCAN_API_KEY", None)
            else:
                os.environ["ETHERSCAN_API_KEY"] = previous_one
        self.assertTrue(keyed["verified"])
        self.assertEqual(keyed["via"], "etherscan-v2")
        self.assertNotIn("secret-key", json.dumps(keyed))
        self.assertEqual(keyed["heat_contribution"], 0)
        self.assertTrue(free["verified"])
        self.assertEqual(free["via"], "sourcify")


if __name__ == "__main__":
    unittest.main()
