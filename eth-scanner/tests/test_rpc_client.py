"""RPC circuit breaker: hard provider errors skip; healthy calls proceed."""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.discover.fresh import run_fresh_deploy_discovery
from eth_scanner.engines.fork_verify import run_fork_verify, should_run_fork_verify
from eth_scanner.engines.fuzz_runner import run_lead_fuzz
from eth_scanner.ingest.rpc_client import (
    RpcTransientError,
    RpcUnavailable,
    classify_rpc_failure,
    host_only,
    is_rpc_usable,
    probe_rpc,
    reset_rpc_circuits,
    rpc_call,
    rpc_unusable_reason,
)
from eth_scanner.store.supabase import MemoryStore

FAKE_RPC = "https://eth-mainnet.example.invalid/v2/test-key-not-real"
CAPACITY_MSG = "Monthly capacity limit exceeded"
CAPACITY_BODY = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "error": {"code": 429, "message": CAPACITY_MSG},
})
HEALTHY_BODY = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x12d687"})


class _Resp:
    def __init__(self, payload: str, status: int = 200):
        self.status = status
        self._payload = payload.encode("utf-8") if isinstance(payload, str) else payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, body: str, url: str = FAKE_RPC) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "Error", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


class ClassifyFailure(unittest.TestCase):
    def test_jsonrpc_monthly_capacity_is_hard(self):
        kind, detail = classify_rpc_failure(200, json.loads(CAPACITY_BODY))
        self.assertEqual(kind, "hard")
        self.assertIn("capacity", detail.lower())

    def test_http_429_capacity_is_hard(self):
        kind, detail = classify_rpc_failure(429, CAPACITY_BODY)
        self.assertEqual(kind, "hard")
        self.assertIn("capacity", detail.lower())

    def test_ordinary_429_is_transient(self):
        kind, _ = classify_rpc_failure(429, "Too Many Requests")
        self.assertEqual(kind, "transient")
        kind, _ = classify_rpc_failure(429, "exceeded its compute units per second capacity")
        self.assertEqual(kind, "transient")

    def test_auth_is_hard(self):
        self.assertEqual(classify_rpc_failure(401, "Must be authenticated")[0], "hard")
        self.assertEqual(classify_rpc_failure(403, "invalid api key")[0], "hard")

    def test_execution_revert_unauthorized_is_not_provider_auth(self):
        kind, detail = classify_rpc_failure(
            200, {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted: UNAUTHORIZED"}},
        )
        self.assertEqual(kind, "other")
        self.assertNotEqual(kind, "hard")
        self.assertIn("reverted", detail.lower())

    def test_5xx_is_server(self):
        self.assertEqual(classify_rpc_failure(503, "unavailable")[0], "server")

    def test_host_only_strips_key_path(self):
        self.assertEqual(host_only(FAKE_RPC), "eth-mainnet.example.invalid")
        self.assertNotIn("test-key", host_only(FAKE_RPC))


class CircuitBreaker(unittest.TestCase):
    def setUp(self):
        reset_rpc_circuits()

    def tearDown(self):
        reset_rpc_circuits()

    def test_capacity_jsonrpc_opens_circuit_and_skips_later_calls(self):
        hits = {"n": 0}

        def _urlopen(req, timeout=None):
            hits["n"] += 1
            return _Resp(CAPACITY_BODY)

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            with self.assertRaises(RpcUnavailable) as ctx:
                rpc_call(FAKE_RPC, "eth_blockNumber", [])
            self.assertIn("unusable", ctx.exception.reason.lower())
            self.assertFalse(is_rpc_usable(FAKE_RPC))
            reason = rpc_unusable_reason(FAKE_RPC)
            self.assertIn("unusable", reason)
            self.assertIn("eth-mainnet.example.invalid", reason)
            self.assertNotIn("test-key", reason)
            # Second call must not hit the network.
            with self.assertRaises(RpcUnavailable):
                rpc_call(FAKE_RPC, "eth_blockNumber", [])
        self.assertEqual(hits["n"], 1)

    def test_healthy_response_proceeds(self):
        def _urlopen(req, timeout=None):
            return _Resp(HEALTHY_BODY)

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            result = rpc_call(FAKE_RPC, "eth_blockNumber", [])
        self.assertEqual(result, "0x12d687")
        self.assertTrue(is_rpc_usable(FAKE_RPC))
        ok, reason = True, ""
        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            ok, reason = probe_rpc(FAKE_RPC)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_ordinary_429_retries_then_raises_without_opening_circuit(self):
        hits = {"n": 0}

        def _urlopen(req, timeout=None):
            hits["n"] += 1
            raise _http_error(429, "Too Many Requests")

        with mock.patch.dict(os.environ, {
            "ETH_SCANNER_RPC_TRANSIENT_RETRIES": "2",
            "ETH_SCANNER_RPC_TRANSIENT_BACKOFF_S": "0",
        }):
            with mock.patch("eth_scanner.ingest.rpc_client.time.sleep", return_value=None):
                with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
                    with self.assertRaises(RpcTransientError):
                        rpc_call(FAKE_RPC, "eth_blockNumber", [])
        self.assertEqual(hits["n"], 3)
        self.assertTrue(is_rpc_usable(FAKE_RPC))

    def test_repeated_5xx_opens_circuit(self):
        def _urlopen(req, timeout=None):
            raise _http_error(502, "bad gateway")

        with mock.patch.dict(os.environ, {
            "ETH_SCANNER_RPC_TRANSIENT_RETRIES": "0",
            "ETH_SCANNER_RPC_5XX_THRESHOLD": "3",
            "ETH_SCANNER_RPC_TRANSIENT_BACKOFF_S": "0",
        }):
            with mock.patch("eth_scanner.ingest.rpc_client.time.sleep", return_value=None):
                with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
                    for _ in range(2):
                        with self.assertRaises(Exception):
                            rpc_call(FAKE_RPC, "eth_blockNumber", [], max_retries=0)
                    self.assertTrue(is_rpc_usable(FAKE_RPC))
                    with self.assertRaises(RpcUnavailable):
                        rpc_call(FAKE_RPC, "eth_blockNumber", [], max_retries=0)
        self.assertFalse(is_rpc_usable(FAKE_RPC))
        self.assertIn("5xx", rpc_unusable_reason(FAKE_RPC))


class StageSkips(unittest.TestCase):
    def setUp(self):
        reset_rpc_circuits()

    def tearDown(self):
        reset_rpc_circuits()

    def test_fresh_deploy_skips_on_capacity_429_without_raising(self):
        store = MemoryStore()

        def _urlopen(req, timeout=None):
            return _Resp(CAPACITY_BODY)

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            stats = run_fresh_deploy_discovery(store=store, rpc_url=FAKE_RPC)
        self.assertEqual(stats.status, "noop")
        self.assertTrue(stats.rpc_configured)
        self.assertIn("unusable", stats.message.lower())
        self.assertIsNone(store.get_backfill("fresh-deploys-head"))
        self.assertEqual(store.targets, {})

    def test_fresh_deploy_proceeds_on_healthy_rpc(self):
        store = MemoryStore()
        hits = {"n": 0}

        def _urlopen(req, timeout=None):
            hits["n"] += 1
            return _Resp(HEALTHY_BODY)

        def discover(lo, hi):
            return [], type("S", (), {"source": "mock", "creates": 0, "errors": []})()

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            # Do not inject head_fn so the real probe + head_block path runs.
            stats = run_fresh_deploy_discovery(
                store=store,
                rpc_url=FAKE_RPC,
                discover_fn=discover,
                probe_fn=lambda addrs, **kw: {},
            )
        self.assertNotEqual(stats.status, "noop")
        self.assertGreaterEqual(hits["n"], 1)
        self.assertGreater(stats.head_block, 0)
        self.assertIn(stats.status, {"done", "error"})  # empty walk still "done"

    def test_fork_verify_skips_on_capacity_429_without_raising(self):
        def _urlopen(req, timeout=None):
            return _Resp(CAPACITY_BODY)

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            report = run_fork_verify(
                address="0x" + "11" * 20,
                rpc_url=FAKE_RPC,
                heat=12,
                force=True,
            )
        self.assertTrue(report.skipped)
        self.assertFalse(report.drainable)
        self.assertIn("unusable", (report.skip_reason or "").lower())

        # Circuit already open: gate itself refuses without another probe.
        ok, reason = should_run_fork_verify(heat=12, rpc_url=FAKE_RPC, enabled=True)
        self.assertFalse(ok)
        self.assertIn("unusable", reason.lower())

    def test_fork_verify_healthy_probe_reaches_tool_gate(self):
        def _urlopen(req, timeout=None):
            return _Resp(HEALTHY_BODY)

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            report = run_fork_verify(
                address="0x" + "11" * 20,
                rpc_url=FAKE_RPC,
                heat=12,
                force=True,
            )
        # A healthy RPC is allowed through; CI may still skip if forge/anvil
        # are missing, but it must not be treated as an unusable key.
        self.assertNotIn("unusable", (report.skip_reason or "").lower())
        self.assertNotIn("capacity", (report.skip_reason or "").lower())
        if report.skipped:
            self.assertIn("forge", (report.skip_reason or " ".join(report.notes)).lower())

    def test_fuzz_skips_on_capacity_429_without_raising(self):
        def _urlopen(req, timeout=None):
            return _Resp(CAPACITY_BODY)

        with mock.patch("eth_scanner.ingest.rpc_client.urllib.request.urlopen", side_effect=_urlopen):
            report = run_lead_fuzz(
                address="0x" + "11" * 20,
                contract_class="vault",
                rpc_url=FAKE_RPC,
                timeout_s=5,
            )
        self.assertTrue(report.skipped)
        self.assertEqual(report.status, "skipped")
        self.assertTrue(any("unusable" in n.lower() for n in report.notes))


if __name__ == "__main__":
    unittest.main()
