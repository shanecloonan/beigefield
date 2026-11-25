"""EVM chain config. Ethereum keeps chain id 1 and does not gain a public RPC."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chains.evm import (
    call_with_backoff,
    describe_all,
    detect_features,
    evm_chain,
    rpc_choice,
)
from eth_scanner.chains.registry import normalize_chain
from eth_scanner.ingest.etherscan import CHAIN_ID, EtherscanClient, explorer_query
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import Target

ETH = "0x" + "ab" * 20
BSC = "0x" + "CD" * 20


class EvmChains(unittest.TestCase):
    def test_ids_and_aliases(self):
        self.assertEqual(evm_chain("ethereum").chain_id, 1)
        self.assertEqual(evm_chain("bsc").chain_id, 56)
        self.assertEqual(evm_chain("arbitrum").chain_id, 42161)
        self.assertEqual(evm_chain("base").chain_id, 8453)
        self.assertEqual(evm_chain("optimism").chain_id, 10)
        self.assertEqual(evm_chain("polygon").chain_id, 137)
        self.assertEqual(normalize_chain("bnb"), "bsc")
        self.assertEqual(normalize_chain("arb"), "arbitrum")
        self.assertEqual(normalize_chain("op"), "optimism")
        self.assertEqual(normalize_chain("matic"), "polygon")
        self.assertEqual(normalize_chain("eth"), "ethereum")
        self.assertEqual(evm_chain("bsc").native_symbol, "BNB")
        self.assertEqual(evm_chain("base").native_price_id, "ethereum")

    def test_ethereum_rpc_stays_unset_without_a_public_fallback(self):
        previous = os.environ.pop("ETH_RPC_URL", None)
        try:
            choice = rpc_choice("ethereum")
        finally:
            if previous is not None:
                os.environ["ETH_RPC_URL"] = previous
        self.assertEqual(choice["source"], "unset")
        self.assertEqual(choice["url"], "")

    def test_other_chains_use_the_env_or_a_public_endpoint(self):
        previous = os.environ.pop("BSC_RPC_URL", None)
        previous_eth = os.environ.pop("ETH_RPC_URL", None)
        previous_key = os.environ.pop("ALCHEMY_API_KEY", None)
        try:
            public = rpc_choice("bsc")
            os.environ["BSC_RPC_URL"] = "https://bnb-mainnet.g.alchemy.com/v2/secret-value"
            configured = rpc_choice("bnb")
            summary = json.dumps(describe_all())
        finally:
            if previous is None:
                os.environ.pop("BSC_RPC_URL", None)
            else:
                os.environ["BSC_RPC_URL"] = previous
            if previous_eth is None:
                os.environ.pop("ETH_RPC_URL", None)
            else:
                os.environ["ETH_RPC_URL"] = previous_eth
            if previous_key is None:
                os.environ.pop("ALCHEMY_API_KEY", None)
            else:
                os.environ["ALCHEMY_API_KEY"] = previous_key
        self.assertEqual(public["source"], "public")
        self.assertTrue(public["url"].startswith("https://bsc-dataseed"))
        self.assertEqual(configured["source"], "configured")
        self.assertNotIn("secret-value", summary)
        self.assertNotIn("http", summary)

    def test_explorer_chainid_defaults_to_ethereum(self):
        query = explorer_query({"module": "contract", "action": "getsourcecode"}, api_key="k")
        self.assertEqual(query["chainid"], 1)
        self.assertEqual(query["chainid"], CHAIN_ID)
        other = explorer_query({"module": "contract"}, chain_id=56, api_key="k")
        self.assertEqual(other["chainid"], 56)
        client = EtherscanClient(["k"], min_interval_s=0)
        self.assertEqual(client.chain_id, 1)
        other_client = EtherscanClient(["k"], min_interval_s=0, chain_id=8453)
        self.assertEqual(other_client.chain_id, 8453)

    def test_feature_detect_does_not_guess_through_a_429(self):
        def rpc(method, params):
            if method == "eth_chainId":
                return "0x38"
            if method == "debug_traceTransaction":
                raise RuntimeError("method not found")
            if method == "trace_filter":
                raise RuntimeError("HTTP 429")
            raise RuntimeError("transaction not found")

        report = detect_features("bsc", rpc)
        self.assertEqual(report["methods"]["eth_chainId"], "supported")
        self.assertEqual(report["methods"]["debug_traceTransaction"], "unsupported")
        self.assertEqual(report["methods"]["trace_filter"], "unknown")
        self.assertEqual(report["methods"]["eth_getProof"], "supported")
        from eth_scanner.chains.evm import classify_method_error
        self.assertEqual(
            classify_method_error(RuntimeError("http 401 rejected due to request filter settings")),
            "unknown",
        )
        self.assertEqual(report["heat_contribution"], 0)
        self.assertTrue(report["degraded"])

    def test_backoff_retries_once_and_ethereum_has_no_public_url(self):
        pauses = []
        calls = []

        def rpc(url, method, params):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError("HTTP 429")
            return "0x1"

        previous = os.environ.pop("BASE_RPC_URL", None)
        previous_eth = os.environ.pop("ETH_RPC_URL", None)
        previous_key = os.environ.pop("ALCHEMY_API_KEY", None)
        try:
            result = call_with_backoff("base", "eth_chainId", [], rpc=rpc, pause=pauses.append)
        finally:
            if previous is None:
                os.environ.pop("BASE_RPC_URL", None)
            else:
                os.environ["BASE_RPC_URL"] = previous
            if previous_eth is None:
                os.environ.pop("ETH_RPC_URL", None)
            else:
                os.environ["ETH_RPC_URL"] = previous_eth
            if previous_key is None:
                os.environ.pop("ALCHEMY_API_KEY", None)
            else:
                os.environ["ALCHEMY_API_KEY"] = previous_key
        self.assertEqual(result, "0x1")
        self.assertEqual(pauses, [1.0])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("alchemy" not in url for url in calls))

        def refuse(url, method, params):
            raise AssertionError("ethereum must not call a public RPC")

        previous_eth = os.environ.pop("ETH_RPC_URL", None)
        try:
            with self.assertRaises(RuntimeError):
                call_with_backoff("ethereum", "eth_chainId", [], rpc=refuse, pause=lambda _s: None)
        finally:
            if previous_eth is not None:
                os.environ["ETH_RPC_URL"] = previous_eth

    def test_an_evm_worker_does_not_take_an_ethereum_row(self):
        store = MemoryStore()
        store.upsert_target(Target(address=ETH, status="pending"))
        store.upsert_target(Target(address=BSC, chain="bsc", status="pending"))
        eth = store.claim_pending(10, "eth-worker")
        self.assertEqual([row["address"] for row in eth], [ETH])
        bsc = store.claim_pending(10, "bsc-worker", chain="bnb")
        self.assertEqual(bsc[0]["address"], BSC.lower())
        self.assertEqual(bsc[0]["chain"], "bsc")

    def test_a_shared_alchemy_key_is_reused_and_never_described(self):
        previous = {name: os.environ.pop(name, None) for name in ("OPTIMISM_RPC_URL", "ETH_RPC_URL", "ALCHEMY_API_KEY")}
        try:
            os.environ["ETH_RPC_URL"] = "https://eth-mainnet.g.alchemy.com/v2/shared-key"
            choice = rpc_choice("op")
            summary = json.dumps(describe_all())
            eth = rpc_choice("ethereum")
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(choice["source"], "alchemy")
        self.assertTrue(choice["url"].startswith("https://opt-mainnet.g.alchemy.com/v2/"))
        self.assertNotIn("shared-key", summary)
        self.assertNotIn("http", summary)
        self.assertEqual(eth["source"], "configured")
        self.assertTrue(eth["url"].endswith("/v2/shared-key"))


if __name__ == "__main__":
    unittest.main()
