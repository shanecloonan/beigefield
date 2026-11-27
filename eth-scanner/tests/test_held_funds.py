"""Held-funds selection ranks the balance at the address, not protocol TVL."""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.desk import held_funds
from eth_scanner.desk import signal_rerun as rerun
from eth_scanner.ingest.funds import MAJOR_TOKENS
from eth_scanner.store.supabase import MemoryStore


def _addr(byte: str) -> str:
    return "0x" + byte * 20


def _snap(usd: float, status: str = "ok"):
    return {"status": status, "total_usd": usd}


class Rank(unittest.TestCase):
    def test_measured_funds_win_and_tokens_routers_and_eoas_drop(self):
        rich = _addr("11")
        mid = _addr("22")
        dust = _addr("33")
        empty = _addr("44")
        token = MAJOR_TOKENS[0][1]
        router = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
        finished = _addr("55")
        rows = [
            {"address": dust, "protocol": "Dust pool", "kind": "curve-pool", "reported_usd": 9_000_000},
            {"address": rich, "protocol": "Rich vault", "kind": "morpho-vault", "reported_usd": 1},
            {"address": mid, "protocol": "Mid pool", "kind": "curve-pool"},
            {"address": empty, "protocol": "Whale EOA", "kind": "holder"},
            {"address": token, "protocol": "WETH", "kind": "holder"},
            {"address": router, "protocol": "Router", "kind": "holder"},
            {"address": finished, "protocol": "Done", "kind": "beefy-vault"},
            {"address": "not-an-address", "protocol": "Bad", "kind": "curve-pool"},
        ]
        snapshots = {
            rich: _snap(80_000),
            mid: _snap(12_000),
            dust: _snap(4_999),
            empty: _snap(1_000_000),
            token: _snap(50_000_000),
            router: _snap(20_000),
            finished: _snap(30_000),
        }
        codes = {rich: "0x6080", mid: "0x6080", dust: "0x6080", empty: "0x", token: "0x6080", router: "0x6080", finished: "0x6080"}
        chosen = held_funds.rank_held(rows, snapshots, codes, finished={finished}, limit=500)
        self.assertEqual([row["address"] for row in chosen], [rich, mid])
        self.assertEqual(chosen[0]["est_usd_held"], 80000)
        self.assertEqual(chosen[0]["category"], "morpho-vault")
        unknown = held_funds.rank_held(
            [{"address": rich, "protocol": "Rich", "kind": "curve-pool"}],
            {rich: _snap(0, "unknown")},
            {rich: "0x6080"},
        )
        self.assertEqual(unknown, [])

    def test_candidate_file_is_pools_and_vaults_not_the_tokens(self):
        rows = held_funds.load_candidates()
        self.assertGreaterEqual(len(rows), 500)
        kinds = {row["kind"] for row in rows}
        self.assertIn("curve-pool", kinds)
        self.assertIn("morpho-vault", kinds)
        seen = set()
        denied = set(held_funds.DENY_ADDRESSES)
        for row in rows:
            addr = rerun.safe_address(row["address"])
            self.assertTrue(addr)
            self.assertNotIn(addr, seen)
            self.assertNotIn(addr, denied)
            seen.add(addr)
        self.assertIn("0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7", seen)

    def test_dry_run_orders_by_the_measured_balance(self):
        rich = _addr("ab")
        poor = _addr("cd")
        report = held_funds.run_held_funds_batch(
            MemoryStore(),
            object(),
            dry_run=True,
            candidates=[
                {"address": poor, "protocol": "Poor", "kind": "curve-pool", "reported_usd": 1000000},
                {"address": rich, "protocol": "Rich", "kind": "morpho-vault", "reported_usd": 10},
            ],
            snapshots={poor: _snap(6000), rich: _snap(40000)},
            codes={poor: "0x60", rich: "0x60"},
        )
        self.assertEqual(report["status"], "dry-run")
        self.assertEqual(report["mode"], "held-funds")
        self.assertEqual([row["address"] for row in report["selected_rows"]], [rich, poor])
        self.assertTrue(any("under-$5k queues were not read" in note for note in report["notes"]))
        self.assertEqual(report["cu_used"], 0)


class Scan(unittest.TestCase):
    def test_fork_runs_only_after_heat(self):
        cold = _addr("10")
        hot = _addr("20")
        calls = []

        def scan_one(address, settings=None, store=None, **kwargs):
            full = os.environ.get("ETH_SCANNER_FULL_PATH") == "1"
            calls.append((address, full, os.environ.get("ETH_SCANNER_FORK_VERIFY")))
            result = type("Result", (), {})()
            result.heat = 0
            result.heat_breakdown = {"eoa_admin": 3} if address == hot else {}
            result.notes = []
            result.contract_name = "Vault"
            result.invariant_results = []
            result.bucket = "lane-a"
            result.funds_usd = 40000 if address == hot else 9000
            result.drop_reason = ""
            result.stage_trace = []
            result.hypotheses = []
            result.value_movers = []
            result.contract_class = ""
            result.scope = ""
            result.src_confidence = "low"
            result.ir_confidence = "low"
            result.dropped = False
            result.funds_breakdown = []
            result.funds_status = "ok"
            result.funds_checked_at = None
            result.engine_leads = []
            result.confirmed_findings = []
            result.engine_timing = {}
            if full:
                from eth_scanner.stages.fusion import annotate_stages
                result.heat_breakdown = annotate_stages({
                    "eoa_admin": 3,
                    "exploit_poc": {"ran": True, "status": "ok", "drainable": False, "attacker_up": 0, "target_down": 0},
                    "fuzz": {"ran": True, "status": "ok", "tool": "forge", "properties_checked": 2, "failures": []},
                }, heat=3)
            else:
                self.assertIsNone(os.environ.get("ETH_SCANNER_FULL_PATH"))
                self.assertIsNone(os.environ.get("ETH_SCANNER_FORK_VERIFY"))
            return result

        class Settings:
            def __init__(self):
                self.eth_rpc_url = "http://127.0.0.1:9"
                self.range_min_usd = None
                self.range_max_usd = None

        os.environ["ETH_SCANNER_FORK_VERIFY"] = "1"
        os.environ["ETH_SCANNER_FULL_PATH"] = "1"
        try:
            report = held_funds.run_held_funds_batch(
                MemoryStore(),
                Settings(),
                budget_cu=400_000,
                deadline_s=120,
                lease_wait_s=2,
                scan_one=scan_one,
                candidates=[
                    {"address": cold, "protocol": "Cold", "kind": "curve-pool"},
                    {"address": hot, "protocol": "Hot", "kind": "morpho-vault"},
                ],
                snapshots={cold: _snap(9000), hot: _snap(40000)},
                codes={cold: "0x60", hot: "0x60"},
            )
        finally:
            os.environ.pop("ETH_SCANNER_FORK_VERIFY", None)
            os.environ.pop("ETH_SCANNER_FULL_PATH", None)
        self.assertEqual(report["mode"], "held-funds")
        self.assertEqual(report["found"], 2)
        self.assertEqual(report["scanned"], 2)
        self.assertEqual(report["verdict_counts"], {"no": 1, "maybe": 1})
        self.assertEqual([item[0] for item in calls if not item[1]], [hot, cold])
        self.assertEqual([item[0] for item in calls if item[1]], [hot])
        self.assertEqual(report["drainable"], [])
        self.assertEqual(report["full_path_ran"], 1)

    def test_provider_stop_during_measure_writes_nothing(self):
        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": 429, "message": "Monthly capacity limit exceeded"},
                }).encode("utf-8")
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        scanned = []

        def scan_one(address, **kwargs):
            scanned.append(address)
            raise AssertionError("scanned after a provider stop")

        class Settings:
            def __init__(self, url):
                self.eth_rpc_url = url
                self.range_min_usd = None
                self.range_max_usd = None

        store = MemoryStore()
        from eth_scanner.ingest.rpc_client import reset_rpc_circuits
        try:
            report = held_funds.run_held_funds_batch(
                store,
                Settings("http://127.0.0.1:%d" % server.server_address[1]),
                budget_cu=400_000,
                deadline_s=60,
                lease_wait_s=2,
                scan_one=scan_one,
                candidates=[{"address": _addr("a1"), "protocol": "Pool", "kind": "curve-pool"}],
            )
        finally:
            reset_rpc_circuits()
            server.shutdown()
            server.server_close()
        self.assertEqual(report["status"], "monthly capacity")
        self.assertEqual(scanned, [])
        self.assertEqual(report.get("scanned") or 0, 0)
        self.assertFalse(any(str(row.get("status") or "") == "done" for row in store.test_runs))


class Workflow(unittest.TestCase):
    def test_mode_does_not_start_a_queue(self):
        self.assertEqual(rerun.run_mode_for_changed_files([rerun.HELD_FUNDS_TRIGGER]), "held-funds")
        self.assertEqual(
            rerun.run_mode_for_changed_files([rerun.Q1_TRIGGER, rerun.HELD_FUNDS_TRIGGER, rerun.HIGH_PROB_TRIGGER]),
            "held-funds",
        )
        self.assertEqual(
            rerun.run_mode_for_changed_files([rerun.HELD_FUNDS_TRIGGER, rerun.FULL_PATH_TRIGGER]),
            "full-path",
        )

    def test_workflow_command_is_not_an_under_5k_batch(self):
        text = (ROOT.parent / ".github/workflows/eth-scanner-signal-rerun.yml").read_text(encoding="utf-8")
        self.assertIn("eth-scanner/held-funds.trigger", text)
        branch = text.split('elif [ "${MODE}" = "held-funds" ]', 1)[1].split("elif", 1)[0]
        self.assertIn("held-funds-batch --limit 500 --budget-cu 400000 --deadline-minutes 300", branch)
        self.assertNotIn("--small-value-batch", branch)
        self.assertNotIn("--queue", branch)
        self.assertNotIn("timeout 60m", branch)
        cli = (ROOT / "src/eth_scanner/cli.py").read_text(encoding="utf-8")
        handler = cli.split('if args.cmd == "held-funds-batch":', 1)[1].split("if args.cmd", 1)[0]
        self.assertNotIn("ETH_SCANNER_FORK_VERIFY", handler)
        self.assertNotIn("small_value", handler)
