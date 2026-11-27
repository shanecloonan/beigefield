"""The next high-probability batch stays off the under-$5k queues."""

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

from eth_scanner.desk import high_prob
from eth_scanner.desk import signal_rerun as rerun
from eth_scanner.store.supabase import MemoryStore


def _addr(byte: str) -> str:
    return "0x" + byte * 20


def _bare():
    class Result:
        heat = 0
        heat_breakdown = {}
        notes = []
        contract_name = "Candidate"
        invariant_results = []
        bucket = "lane-a-cool"
        funds_usd = None
        drop_reason = ""
        stage_trace = []
        hypotheses = []
        value_movers = []
        contract_class = ""
        scope = ""
        src_confidence = "low"
        ir_confidence = "low"
        dropped = False
        funds_breakdown = []
        funds_status = ""
        funds_checked_at = None
        engine_leads = []
        confirmed_findings = []
        engine_timing = {}

    return Result()


class Settings:
    def __init__(self, url: str = "http://127.0.0.1:9"):
        self.eth_rpc_url = url
        self.range_min_usd = None
        self.range_max_usd = None


class Select(unittest.TestCase):
    def test_master_order_then_tranche_skips_finished_and_the_floor(self):
        finished = _addr("aa")
        first = _addr("11")
        second = _addr("22")
        low = _addr("33")
        extra = _addr("44")
        store = MemoryStore()
        store.test_runs = [{"address": finished, "status": "done", "heat": 0}]
        master = [
            {"address": first, "est_usd_held": 8000, "protocol": "First", "drain_probability": 0.4, "category": "Lending"},
            {"address": finished, "est_usd_held": 90000, "protocol": "Done", "drain_probability": 0.9, "category": "Lending"},
            {"address": low, "est_usd_held": 4000, "protocol": "Small", "drain_probability": 0.9, "category": "Lending"},
            {"address": second, "est_usd_held": 6000, "protocol": "Second", "drain_probability": 0.2, "category": "Yield"},
        ]
        path = ROOT / "data" / "high_prob_next_test.json"
        path.write_text(json.dumps({"candidates": [
            {"address": second, "est_usd_held": 6000, "protocol": "Second"},
            {"address": extra, "est_usd_held": 12000, "protocol": "Extra", "category": "Vault"},
            {"address": low, "est_usd_held": 1000, "protocol": "Still small"},
        ]}), encoding="utf-8")
        try:
            chosen = high_prob.select_high_prob(store, limit=3, master=master, tranche_path=path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(chosen["status"], "ok")
        self.assertEqual([row["address"] for row in chosen["selected"]], [first, second, extra])
        self.assertEqual(chosen["from_master"], 2)
        self.assertEqual(chosen["from_tranche"], 1)
        self.assertEqual(chosen["skipped_finished"], 1)
        self.assertNotIn(low, [row["address"] for row in chosen["selected"]])

    def test_unreadable_board_scans_nothing(self):
        class Bad:
            def _req(self, *args, **kwargs):
                raise RuntimeError("https://secret.example/db down")

        def boom(address, **kwargs):
            raise AssertionError("scanned %s" % address)

        report = high_prob.run_high_prob_batch(
            Bad(),
            Settings(),
            dry_run=True,
            scan_one=boom,
            master=[],
        )
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["selected"], 0)
        self.assertNotIn("secret.example", json.dumps(report))
        self.assertIn("[url]", json.dumps(report))

    def test_committed_tranche_is_the_expansion(self):
        from eth_scanner.feed.master_list import load_master_candidates

        rows = high_prob.load_tranche()
        self.assertGreaterEqual(len(rows), 300)
        master = {item.address for item in load_master_candidates()}
        seen = set()
        for row in rows:
            addr = rerun.safe_address(row["address"])
            self.assertTrue(addr)
            self.assertNotIn(addr, seen)
            self.assertNotIn(addr, master)
            self.assertGreaterEqual(float(row["est_usd_held"]), 5000)
            self.assertLessEqual(float(row["est_usd_held"]), 9_000_000)
            seen.add(addr)


class Run(unittest.TestCase):
    def test_dry_run_does_not_scan_or_read_a_queue(self):
        store = MemoryStore()
        master = [{"address": _addr("ab"), "est_usd_held": 25000, "protocol": "Vault"}]

        def boom(address, **kwargs):
            raise AssertionError("dry-run scanned")

        report = high_prob.run_high_prob_batch(
            store,
            Settings(),
            dry_run=True,
            scan_one=boom,
            master=master,
            tranche_path=ROOT / "data" / "missing-tranche.json",
        )
        self.assertEqual(report["mode"], "high-prob")
        self.assertEqual(report["status"], "dry-run")
        self.assertEqual(report["selected"], 1)
        self.assertEqual(report["cu_used"], 0)
        self.assertTrue(any("under-$5k queues were not read" in note for note in report["notes"]))
        self.assertIsNone(os.environ.get("ETH_SCANNER_FULL_PATH"))

    def test_normal_scan_then_fork_only_when_heat_is_above_zero(self):
        from eth_scanner.stages.fusion import annotate_stages

        cold = _addr("10")
        warm = _addr("20")
        hot = _addr("30")
        funds = {cold: 900000, warm: 50000, hot: 8000}
        calls = []

        def scan_one(address, settings=None, store=None, **kwargs):
            full = os.environ.get("ETH_SCANNER_FULL_PATH") == "1"
            calls.append((address, full, os.environ.get("ETH_SCANNER_FORK_VERIFY"), os.environ.get("ETH_SCANNER_FUZZ_MIN_HEAT")))
            result = _bare()
            result.funds_usd = funds[address]
            result.contract_name = address[-4:]
            if not full:
                self.assertIsNone(os.environ.get("ETH_SCANNER_FORK_VERIFY"))
                self.assertIsNone(os.environ.get("ETH_SCANNER_FULL_PATH"))
                self.assertEqual(os.environ.get("ETH_SCANNER_FUZZ_MIN_HEAT"), "8")
                if address == hot:
                    result.heat_breakdown = {"eoa_admin": 3, "invariants_failed": 3}
                elif address == warm:
                    result.heat_breakdown = {"eoa_admin": 3}
                return result
            self.assertEqual(os.environ.get("ETH_SCANNER_FORK_VERIFY"), "1")
            self.assertEqual(os.environ.get("ETH_SCANNER_FORK_VERIFY_REDACT"), "1")
            self.assertEqual(os.environ.get("ETH_SCANNER_FUZZ_MIN_HEAT"), "0")
            evidence = {"eoa_admin": 3, "invariants_failed": 3} if address == hot else {"eoa_admin": 3}
            drainable = address == warm
            result.heat_breakdown = annotate_stages({
                **evidence,
                "drainable": drainable,
                "exploit_poc": {
                    "ran": True,
                    "status": "ok",
                    "drainable": drainable,
                    "attacker_up": 0,
                    "target_down": 0,
                },
                "fuzz": {
                    "ran": True,
                    "status": "failed" if drainable else "ok",
                    "tool": "forge",
                    "properties_checked": 4,
                    "failures": [{"property_id": "solvency_assets_cover_shares"}] if drainable else [],
                },
            }, heat=6 if address == hot else 3)
            result.notes = ["fork-verify ok"]
            return result

        os.environ["ETH_SCANNER_FORK_VERIFY"] = "1"
        os.environ["ETH_SCANNER_FUZZ_MIN_HEAT"] = "0"
        os.environ["ETH_SCANNER_FULL_PATH"] = "1"
        try:
            report = high_prob.run_high_prob_batch(
                MemoryStore(),
                Settings(),
                budget_cu=400_000,
                deadline_s=120,
                lease_wait_s=2,
                scan_one=scan_one,
                master=[
                    {"address": cold, "est_usd_held": funds[cold], "protocol": "Cold"},
                    {"address": warm, "est_usd_held": funds[warm], "protocol": "Warm"},
                    {"address": hot, "est_usd_held": funds[hot], "protocol": "Hot"},
                ],
                tranche_path=ROOT / "data" / "missing-tranche.json",
            )
        finally:
            self.assertEqual(os.environ.get("ETH_SCANNER_FORK_VERIFY"), "1")
            self.assertEqual(os.environ.get("ETH_SCANNER_FUZZ_MIN_HEAT"), "0")
            self.assertEqual(os.environ.get("ETH_SCANNER_FULL_PATH"), "1")
            os.environ.pop("ETH_SCANNER_FORK_VERIFY", None)
            os.environ.pop("ETH_SCANNER_FUZZ_MIN_HEAT", None)
            os.environ.pop("ETH_SCANNER_FULL_PATH", None)

        self.assertEqual(report["status"], "done")
        self.assertEqual(report["scanned"], 3)
        self.assertEqual(report["verdict_counts"], {"no": 1, "maybe": 2})
        self.assertEqual(report["heat_counts"]["0"], 1)
        self.assertEqual(report["full_path_ran"], 2)
        phase1 = [item for item in calls if not item[1]]
        phase2 = [item for item in calls if item[1]]
        self.assertEqual([item[0] for item in phase1], [cold, warm, hot])
        self.assertEqual([item[0] for item in phase2], [hot, warm])
        by_addr = {row["address"]: row for row in report["rerun"]}
        self.assertEqual(by_addr[cold]["new_verdict"], "no")
        self.assertEqual(by_addr[cold]["fork"]["status"], "not-run")
        self.assertEqual(by_addr[hot]["new_heat"], 6)
        self.assertEqual(by_addr[hot]["new_verdict"], "maybe")
        self.assertFalse(by_addr[hot]["fork"]["drainable"])
        self.assertNotIn("fork", by_addr[hot]["pending_stages"])
        self.assertIn("hevm", by_addr[hot]["pending_stages"])
        self.assertEqual(by_addr[warm]["new_verdict"], "maybe")
        self.assertTrue(by_addr[warm]["fork"]["drainable"])
        self.assertNotIn("balance rose", by_addr[warm]["fork"]["plain"])
        self.assertEqual(report["drainable"], [warm])
        self.assertIn("solvency_assets_cover_shares", by_addr[warm]["fuzz"]["properties_failed"])
        self.assertNotIn("0x", by_addr[warm]["fuzz"]["plain"])

    def test_provider_stop_writes_no_verdict(self):
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
        upstream = "http://127.0.0.1:%d" % server.server_address[1]
        store = MemoryStore()

        def scan_one(address, settings=None, store=None, **kwargs):
            import urllib.error
            import urllib.request
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).encode("utf-8")
            req = urllib.request.Request(settings.eth_rpc_url, data=payload, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp.read()
            except urllib.error.HTTPError:
                pass
            if store is not None:
                store.save_result(address, _bare())
            return _bare()

        try:
            report = high_prob.run_high_prob_batch(
                store,
                Settings(upstream),
                budget_cu=400_000,
                deadline_s=60,
                lease_wait_s=2,
                scan_one=scan_one,
                master=[
                    {"address": _addr("a1"), "est_usd_held": 20000, "protocol": "A"},
                    {"address": _addr("b2"), "est_usd_held": 15000, "protocol": "B"},
                ],
                tranche_path=ROOT / "data" / "missing-tranche.json",
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(report["status"], "monthly capacity")
        self.assertEqual(report["rerun_count"], 0)
        self.assertEqual(report["scanned"], 0)
        self.assertGreaterEqual(len(report["unfinished"]), 1)
        self.assertEqual(store.results, [])
        self.assertFalse(any(str(row.get("status") or "") == "done" for row in store.test_runs))

    def test_cu_budget_scans_none_and_writes_nothing(self):
        store = MemoryStore()
        called = []

        def scan_one(address, **kwargs):
            called.append(address)
            return _bare()

        report = high_prob.run_high_prob_batch(
            store,
            Settings(),
            budget_cu=100,
            deadline_s=60,
            lease_wait_s=2,
            scan_one=scan_one,
            master=[{"address": _addr("c3"), "est_usd_held": 20000, "protocol": "C"}],
            tranche_path=ROOT / "data" / "missing-tranche.json",
        )
        self.assertEqual(called, [])
        self.assertEqual(report["status"], "cu budget")
        self.assertEqual(report["scanned"], 0)
        self.assertEqual(report["unfinished"][0]["address"], _addr("c3"))
        self.assertFalse(any(str(row.get("status") or "") == "done" for row in store.test_runs))


class Workflow(unittest.TestCase):
    def test_mode_does_not_start_a_queue(self):
        self.assertEqual(rerun.run_mode_for_changed_files([rerun.HIGH_PROB_TRIGGER]), "high-prob")
        self.assertEqual(
            rerun.run_mode_for_changed_files([rerun.Q1_TRIGGER, rerun.HIGH_PROB_TRIGGER, rerun.Q2_TRIGGER]),
            "high-prob",
        )
        self.assertEqual(
            rerun.run_mode_for_changed_files([rerun.HIGH_PROB_TRIGGER, rerun.FULL_PATH_TRIGGER]),
            "full-path",
        )
        self.assertEqual(rerun.run_mode_for_changed_files([rerun.Q2_TRIGGER]), "queue")

    def test_workflow_command_is_not_an_under_5k_batch(self):
        text = (ROOT.parent / ".github/workflows/eth-scanner-signal-rerun.yml").read_text(encoding="utf-8")
        self.assertIn("eth-scanner/high-prob.trigger", text)
        branch = text.split('elif [ "${MODE}" = "high-prob" ]', 1)[1].split("elif", 1)[0]
        self.assertIn("high-prob-batch --limit 300 --budget-cu 400000 --deadline-minutes 300", branch)
        self.assertNotIn("--small-value-batch", branch)
        self.assertNotIn("--queue", branch)
        self.assertNotIn("timeout 60m", branch)
        cli = (ROOT / "src/eth_scanner/cli.py").read_text(encoding="utf-8")
        handler = cli.split('if args.cmd == "high-prob-batch":', 1)[1].split("if args.cmd", 1)[0]
        self.assertNotIn("ETH_SCANNER_FORK_VERIFY", handler)
        self.assertNotIn("small_value", handler)
