"""Touched-storage preload. No network. Heat stays zero. Local anvil only."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.chain.cu_budget import CuBudget
from eth_scanner.chain.storage_fidelity import apply_local, decode_word, load_storage, read_snapshot, write_evidence
from eth_scanner.ingest.rpc_client import RpcTransientError

ADDR = "0x" + "cd" * 20
SLOT = "0x" + "11" * 32
VALUE = "0x" + "22" * 32
TX = "0x" + "ab" * 32


class _Rpc:
    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = errors or {}
        self.seen: list[tuple[str, list]] = []

    def __call__(self, url, method, params, timeout_s=8.0):
        self.seen.append((method, list(params)))
        if method in self.errors:
            raise self.errors[method]
        if method not in self.responses:
            raise RuntimeError("method not found: -32601")
        value = self.responses[method]
        return value(params) if callable(value) else value


class StorageFidelity(unittest.TestCase):
    def test_prestate_tracer_records_slots_and_loads_loopback(self):
        rpc = _Rpc(responses={
            "debug_traceTransaction": {"pre": {ADDR: {"storage": {SLOT: VALUE}}}},
            "anvil_setStorageAt": "0x",
        })
        report = load_storage(
            ADDR, "https://eth-mainnet.g.alchemy.com/v2/test",
            tx_hashes=[TX], budget=CuBudget(1500), rpc=rpc,
            local_rpc_url="http://127.0.0.1:8545",
        )
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["slots"][0]["slot"], SLOT)
        self.assertEqual(report["slots"][0]["source"], "debug_traceTransaction")
        self.assertTrue(report["applied_local"])
        self.assertEqual(report["cu"]["spent"], 1000)
        self.assertIn("anvil_setStorageAt", [name for name, _ in rpc.seen])
        with tempfile.TemporaryDirectory() as tmp:
            path = write_evidence(Path(tmp), report)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["slots"][0]["value"], VALUE)

    def test_public_rpc_is_not_written(self):
        rpc = _Rpc()
        applied, note = apply_local("https://eth-mainnet.g.alchemy.com/v2/test", ADDR, [
            {"slot": SLOT, "value": VALUE},
        ], rpc=rpc)
        self.assertFalse(applied)
        self.assertIn("non-local", note)
        self.assertEqual(rpc.seen, [])

    def test_missing_debug_uses_proof_then_storage_at(self):
        rpc = _Rpc(
            responses={"eth_getStorageAt": VALUE},
            errors={
                "debug_traceTransaction": RuntimeError("method not found: -32601"),
                "eth_getProof": RuntimeError("unsupported method"),
            },
        )
        report = load_storage(ADDR, "http://rpc", tx_hashes=[TX], budget=CuBudget(1500), rpc=rpc)
        self.assertEqual(report["source"], "eth_getStorageAt")
        self.assertGreaterEqual(len(report["slots"]), 1)
        self.assertTrue(all(row["source"] == "eth_getStorageAt" for row in report["slots"]))
        self.assertFalse(report["applied_local"])

    def test_proof_slots_are_evidence(self):
        rpc = _Rpc(responses={
            "eth_getProof": {"storageProof": [{"key": SLOT, "value": VALUE}]},
        })
        report = load_storage(ADDR, "http://rpc", budget=CuBudget(1500), rpc=rpc)
        self.assertEqual(report["source"], "eth_getProof")
        self.assertEqual(report["slots"][0]["value"], VALUE)
        self.assertEqual(report["heat_contribution"], 0)

    def test_rate_limit_degrades(self):
        rpc = _Rpc(errors={"debug_traceTransaction": RpcTransientError("429 too many requests")})
        report = load_storage(ADDR, "http://rpc", tx_hashes=[TX], budget=CuBudget(1500), rpc=rpc)
        self.assertEqual(report["slots"], [])
        self.assertTrue(report["degraded"])
        self.assertEqual(report["heat_contribution"], 0)

    def test_snapshot_decode_refuses_a_public_rpc(self):
        rpc = _Rpc()
        report = read_snapshot(ADDR, [
            {"label": "totalAssets", "slot": "0", "offset": 0, "type": "uint256"},
        ], "https://eth-mainnet.g.alchemy.com/v2/SECRET", rpc=rpc)
        self.assertEqual(rpc.seen, [])
        self.assertEqual(report["heat"], 0)
        self.assertNotIn("SECRET", json.dumps(report))

    def test_snapshot_decodes_static_slots_only(self):
        word = "0x" + "00" * 12 + "ab" * 20
        packed = "0x" + format(7 << 128, "064x")
        rpc = _Rpc(responses={
            "eth_getStorageAt": lambda params: word if params[1].endswith("0") else packed,
        })
        report = read_snapshot(ADDR, [
            {"label": "asset", "slot": "0", "offset": 0, "type": "address"},
            {"label": "balances", "slot": "1", "offset": 0, "type": "mapping(address => uint256)"},
            {"label": "high", "slot": "2", "offset": 16, "type": "uint128"},
        ], "http://127.0.0.1:8545", rpc=rpc, budget=CuBudget(1500))
        labels = {row["label"]: row["value"] for row in report["values"]}
        self.assertEqual(labels["asset"], "0x" + "ab" * 20)
        self.assertEqual(labels["high"], "7")
        self.assertNotIn("balances", labels)
        self.assertEqual(len(rpc.seen), 2)
        self.assertEqual(report["heat"], 0)
        self.assertTrue(report["heat_breakdown"]["storage_layout"])
        self.assertEqual(decode_word("0x" + "ff" * 32, "int8", 0), "-1")

    def test_no_rpc_skips(self):
        report = load_storage(ADDR, "", budget=CuBudget(1500), rpc=_Rpc())
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["cu"]["spent"], 0)


if __name__ == "__main__":
    unittest.main()
