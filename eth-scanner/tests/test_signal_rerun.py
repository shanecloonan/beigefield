"""Historical Maybe / heat selection, the CU cut, and a read-only rerun plan."""

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

from datetime import datetime, timedelta, timezone

from eth_scanner.desk import signal_rerun as rerun
from eth_scanner.engines.fork_verify import ForkVerifyReport
from eth_scanner.feed.runner import CYCLE_CURSOR_ID, acquire_scan_cycle, release_scan_cycle
from eth_scanner.store.supabase import MemoryStore


def _row(**kwargs):
    base = {
        "chain": "ethereum",
        "address": "0x" + "11" * 20,
        "heat": 0,
        "blend_heat": 0,
        "blend_bucket": "",
        "heat_breakdown": {},
        "created_at": "2026-01-01T00:00:00Z",
    }
    base.update(kwargs)
    return base


class Selection(unittest.TestCase):
    def test_downgraded_peak_is_kept_and_deduped(self):
        older = _row(heat=3, blend_bucket="maybe", created_at="2026-01-01T00:00:00Z", contract_name="Vault")
        newer = _row(
            heat=0,
            blend_bucket="no",
            heat_breakdown={"original_peak": 3, "rescore": "evidence-read"},
            created_at="2026-02-01T00:00:00Z",
        )
        folded, other = rerun.fold_signals([older, newer, newer])
        self.assertEqual(other, [])
        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["peak"], 3)
        self.assertEqual(folded[0]["latest"]["blend_bucket"], "no")
        self.assertEqual(rerun.desk_verdict(folded[0]["latest"]), "no")

    def test_current_verdict_wins_when_a_later_row_has_no_breakdown(self):
        older = _row(heat=3, blend_bucket="maybe", created_at="2026-01-01T00:00:00Z")
        newer = _row(heat=0, blend_bucket="", created_at="2026-03-01T00:00:00Z")
        folded, _other = rerun.fold_signals([older, newer])
        self.assertEqual(len(folded), 1)
        self.assertEqual(folded[0]["peak"], 3)
        self.assertEqual(rerun.desk_verdict(folded[0]["latest"]), "no")

    def test_zero_row_is_not_a_signal(self):
        self.assertFalse(rerun.is_signal(_row()))

    def test_other_chains_are_not_scanned_here(self):
        eth, other = rerun.fold_signals([
            _row(chain="base", address="0x" + "22" * 20, heat=4),
        ])
        self.assertEqual(eth, [])
        self.assertEqual(other[0]["chain"], "base")

    def test_budget_keeps_the_hottest_prefix(self):
        rows = [
            {"chain": "ethereum", "address": "0x" + "aa" * 20, "peak": 1},
            {"chain": "ethereum", "address": "0x" + "bb" * 20, "peak": 9},
            {"chain": "ethereum", "address": "0x" + "cc" * 20, "peak": 4},
        ]
        rows.sort(key=lambda item: -item["peak"])
        selected, deferred = rerun.prioritize(rows, budget_cu=rerun.PER_CONTRACT_CU * 2)
        self.assertEqual([item["peak"] for item in selected], [9, 4])
        self.assertEqual(deferred[0]["peak"], 1)
        self.assertEqual(deferred[0]["reason"], "cu budget")

    def test_full_list_estimate_over_four_million_is_cut(self):
        count = (rerun.DEFAULT_BUDGET_CU // rerun.PER_CONTRACT_CU) + 3
        rows = [
            {"chain": "ethereum", "address": "0x" + ("%040x" % n), "peak": count - n}
            for n in range(count)
        ]
        selected, deferred = rerun.prioritize(rows, budget_cu=rerun.DEFAULT_BUDGET_CU)
        self.assertEqual(len(selected), rerun.DEFAULT_BUDGET_CU // rerun.PER_CONTRACT_CU)
        self.assertEqual(rerun.estimate_cu(len(selected))["estimated_cu"] <= rerun.DEFAULT_BUDGET_CU, True)
        self.assertGreater(len(deferred), 0)
        self.assertGreater(selected[0]["peak"], selected[-1]["peak"])

    def test_seed_includes_the_public_maybe(self):
        folded, _other = rerun.fold_signals(rerun.load_seed())
        addresses = {row["address"] for row in folded}
        self.assertIn("0x1b2cb79a4564206f53ba80b4d780f251b4ae6765", addresses)
        self.assertGreaterEqual(len(folded), 8)


class ForkWords(unittest.TestCase):
    def test_outcomes_do_not_carry_call_data(self):
        held = rerun.explain_fork("ok", False)
        broke = rerun.explain_fork("broken", True, 10**18, 10**18)
        bare = rerun.explain_fork("broken", True)
        inconclusive = rerun.explain_fork("inconclusive", False)
        self.assertNotIn("0x", held)
        self.assertNotIn("0x", broke)
        self.assertIn("did not take", held)
        self.assertIn("Nothing was broadcast", broke)
        self.assertIn("rose by", broke)
        self.assertNotIn("rose", bare)
        self.assertNotIn("fell", bare)
        self.assertNotIn("rose", inconclusive)
        self.assertIn("no heat", inconclusive)

    def test_redact_drops_the_stored_sequence(self):
        os.environ["ETH_SCANNER_FORK_VERIFY_REDACT"] = "1"
        try:
            report = ForkVerifyReport(drainable=True, status="broken", sequence="0x" + "ab" * 40)
            report.failures = []
            stored = report.exploit_poc_dict()
            self.assertEqual(stored["sequence"], "")
            self.assertTrue(stored["drainable"])
            self.assertNotIn("0xab", json.dumps(report.as_invariant_row()))
        finally:
            os.environ.pop("ETH_SCANNER_FORK_VERIFY_REDACT", None)


class LeaseAndProxy(unittest.TestCase):
    def test_lease_is_exclusive(self):
        store = MemoryStore()
        until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        store.upsert_backfill({
            "id": CYCLE_CURSOR_ID,
            "stats": {"lease_owner": "backfill", "lease_until": until},
        })
        with self.assertRaises(TimeoutError):
            acquire_scan_cycle(store, wait_s=0.25, poll_s=0.05)
        store.upsert_backfill({
            "id": CYCLE_CURSOR_ID,
            "stats": {"lease_owner": None, "lease_until": None},
        })
        owner = acquire_scan_cycle(store, wait_s=0.5, poll_s=0.05)
        release_scan_cycle(store, owner)
        again = acquire_scan_cycle(store, wait_s=0.5, poll_s=0.05)
        release_scan_cycle(store, again)

    def test_proxy_stops_at_the_cu_cap_and_hides_the_upstream(self):
        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                body = b'{"jsonrpc":"2.0","id":1,"result":"0x1"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        upstream = "http://127.0.0.1:%d" % server.server_address[1]
        proxy = rerun.CuProxy(upstream, cap=30)
        try:
            local = proxy.start()
            self.assertTrue(local.startswith("http://127.0.0.1"))
            first, status = proxy.forward({"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": []})
            self.assertEqual(status, 200)
            self.assertEqual(first.get("result"), "0x1")
            second, _status = proxy.forward({"jsonrpc": "2.0", "id": 2, "method": "eth_call", "params": []})
            self.assertEqual(proxy.stop_reason, "cu budget")
            self.assertIn("cu budget", json.dumps(second))
            self.assertNotIn(str(server.server_address[1]), json.dumps(second))
        finally:
            proxy.stop()
            server.shutdown()
            server.server_close()

    def test_monthly_capacity_stops_without_retrying_as_transient(self):
        body = {"error": {"code": 429, "message": "Monthly capacity limit exceeded"}}
        self.assertFalse(rerun._is_transient_429(429, body))
        self.assertEqual(rerun._provider_stop(429, body), "monthly capacity")
        # A 403 capacity response is the plan limit, not an auth failure.
        denied = {"error": {"code": 403, "message": "Monthly capacity limit exceeded"}}
        self.assertEqual(rerun._provider_stop(403, denied), "monthly capacity")

    def test_vault_unauthorized_reverts_are_not_provider_auth(self):
        ownable = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": 3,
                "message": (
                    "execution reverted: OwnableUnauthorizedAccount("
                    "0x0000000000000000000000000000000000000001)"
                ),
                "data": "0x118cdaa7" + "00" * 31 + "01",
            },
        }
        access = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": 3,
                "message": (
                    "execution reverted: AccessControlUnauthorizedAccount("
                    "0x0000000000000000000000000000000000000001, 0x1234)"
                ),
                "data": "0xe2517d3f",
            },
        }
        name_only = {
            "error": {"code": 3, "message": "OwnableUnauthorizedAccount"},
        }
        access_in_data = {
            "error": {
                "message": "execution reverted",
                "data": "AccessControlUnauthorizedAccount(0x0000000000000000000000000000000000000001)",
            },
        }
        bare_reason = {
            "error": {"code": 3, "message": "execution reverted: UNAUTHORIZED"},
        }
        forbidden_reason = {
            "error": {"message": "execution reverted: forbidden", "data": "0x08c379a0"},
        }
        with self.assertNoLogs("eth_scanner.signal_rerun", level="WARNING"):
            for body in (ownable, access, name_only, access_in_data, bare_reason, forbidden_reason):
                self.assertEqual(rerun._provider_stop(200, body), "")

    def test_http_401_is_provider_auth_and_logs_redacted(self):
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": 401,
                "message": (
                    "Must be authenticated! "
                    "https://eth-mainnet.g.alchemy.com/v2/demoKeyNotReal0123456789"
                ),
            },
        }
        with self.assertLogs("eth_scanner.signal_rerun", level="WARNING") as caught:
            self.assertEqual(rerun._provider_stop(401, body), "auth")
        text = " ".join(caught.output)
        self.assertIn("401", text)
        self.assertIn("Must be authenticated", text)
        self.assertNotIn("alchemy", text.lower())
        self.assertNotIn("demoKeyNotReal", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        # Credential wording on HTTP 200 is still auth. A transport 403 is auth.
        missing = {"error": {"code": -32600, "message": "invalid api key"}}
        self.assertEqual(rerun._provider_stop(200, missing), "auth")
        self.assertEqual(
            rerun._provider_stop(403, {"error": {"message": "Forbidden"}}),
            "auth",
        )
        self.assertEqual(
            rerun._provider_stop(200, {"error": {"message": "Unauthorized"}}),
            "auth",
        )


class EvidenceHeat(unittest.TestCase):
    def test_a_stored_peak_does_not_become_the_new_heat(self):
        class Result:
            def __init__(self):
                self.heat = 6
                self.heat_breakdown = {"original_peak": 3, "peak_heat": 3, "total": 6}

        result = Result()
        parts = rerun.apply_evidence_heat(result, 3)
        self.assertEqual(parts["total"], 0)
        self.assertEqual(result.heat, 0)
        self.assertEqual(result.heat_breakdown["original_peak"], 3)

    def test_failed_invariants_are_kept(self):
        class Result:
            def __init__(self):
                self.heat = 6
                self.heat_breakdown = {
                    "invariants_failed": 3,
                    "gated_leads": 3,
                    "original_peak": 3,
                    "total": 6,
                }

        result = Result()
        parts = rerun.apply_evidence_heat(result, 3)
        self.assertEqual(parts["total"], 6)
        self.assertEqual(result.heat, 6)
        self.assertEqual(result.heat_breakdown["original_peak"], 3)
        self.assertEqual(rerun.desk_verdict({"heat": 0, "heat_breakdown": {"original_peak": 6}}), "no")

    def test_pages_past_the_old_forty_thousand_cap(self):
        class Store:
            def __init__(self):
                self.calls = 0

            def _req(self, method, table, query=None):
                self.calls += 1
                if self.calls < 41:
                    return [{"address": "0x" + "11" * 20, "heat": 0, "created_at": str(self.calls)}] * 1000
                return [{"address": "0x" + "22" * 20, "heat": 1, "created_at": "end"}]

        rows, err = rerun._page(Store(), "eth_scan_results", "address,heat")
        self.assertEqual(err, "")
        self.assertEqual(len(rows), 40_001)

    def test_desk_row_uses_evidence_heat(self):
        store = MemoryStore()

        class Result:
            def __init__(self):
                self.heat = 6
                self.heat_breakdown = {"original_peak": 3, "total": 6}
                self.notes = []
                self.contract_name = "Vault"
                self.invariant_results = []
                self.bucket = "lane-a-cool"
                self.funds_usd = None
                self.drop_reason = ""

        result = Result()
        parts = rerun.apply_evidence_heat(result, 3)
        err = rerun.persist_desk(store, result, "0x" + "11" * 20, parts, 3)
        self.assertEqual(err, "")
        saved = store.test_runs[0]
        self.assertEqual(saved["heat"], 0)
        self.assertEqual(saved["blend_bucket"], "no")
        self.assertEqual(saved["heat_breakdown"]["original_peak"], 3)


class DryRun(unittest.TestCase):
    def test_dry_run_does_not_scan(self):
        store = MemoryStore()
        called = []

        def boom(address, **kwargs):
            called.append(address)
            raise AssertionError("dry-run scanned")

        class Settings:
            eth_rpc_url = "http://127.0.0.1:1"
            range_min_usd = None
            range_max_usd = None

        report = rerun.run_signal_rerun(
            store,
            Settings(),
            budget_cu=rerun.DEFAULT_BUDGET_CU,
            dry_run=True,
            scan_one=boom,
        )
        self.assertEqual(called, [])
        self.assertEqual(report["status"], "dry-run")
        self.assertGreaterEqual(report["signals"], 8)
        self.assertEqual(report["cu_used"], 0)


def _bare_result():
    class Result:
        heat = 0
        heat_breakdown = {}
        notes = []
        contract_name = "Skipped"
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


class ProviderStop(unittest.TestCase):
    def test_release_drops_empty_done_and_keeps_real_heat(self):
        store = MemoryStore()
        empty = "0xa0b9cc50c460dde28321c34fcd7161434655a38f"
        hot = "0x00000069abbb0b1ad6975bcf753eee15d318a0bf"
        store.test_runs = [
            {
                "dedupe_key": "signal-rerun:%s" % empty,
                "address": empty,
                "status": "done",
                "discovery_source": "signal_rerun",
                "heat": 0,
                "blend_heat": 0,
                "blend_bucket": "no",
                "heat_breakdown": {"original_peak": 5, "total": 0},
            },
            {
                "dedupe_key": "signal-rerun:%s" % hot,
                "address": hot,
                "status": "done",
                "discovery_source": "signal_rerun",
                "heat": 4,
                "blend_heat": 4,
                "blend_bucket": "maybe",
                "heat_breakdown": {"invariants_failed": 4, "total": 4},
            },
        ]
        report = rerun.release_false_finished(store, [empty, hot])
        self.assertEqual([row["address"] for row in report["released"]], [empty])
        self.assertEqual([row["address"] for row in store.test_runs], [hot])

    def test_capacity_stop_does_not_write_a_finished_verdict(self):
        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
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

            def log_message(self, fmt: str, *args) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        upstream = "http://127.0.0.1:%d" % server.server_address[1]
        store = MemoryStore()
        saved = []

        def scan_one(address, settings=None, store=None, **kwargs):
            import urllib.error
            import urllib.request
            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_chainId",
                "params": [],
            }).encode("utf-8")
            req = urllib.request.Request(
                settings.eth_rpc_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp.read()
            except urllib.error.HTTPError:
                pass
            result = _bare_result()
            if store is not None:
                store.save_result(address, result)
            saved.append(address)
            return result

        class Settings:
            def __init__(self):
                self.eth_rpc_url = upstream
                self.range_min_usd = None
                self.range_max_usd = None

        try:
            report = rerun.run_signal_rerun(
                store,
                Settings(),
                budget_cu=250_000,
                deadline_s=120,
                lease_wait_s=2,
                small_value_batch=True,
                batch_size=75,
                scan_one=scan_one,
            )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(report["status"], "monthly capacity")
        self.assertEqual(report["stop_reason"], "monthly capacity")
        self.assertEqual(report["rerun_count"], 0)
        self.assertEqual(len(saved), 1)
        self.assertGreaterEqual(len(report["unfinished"]), 1)
        self.assertEqual(report["unfinished"][0]["address"], saved[0])
        self.assertEqual(store.results, [])
        self.assertFalse(any(str(row.get("status") or "") == "done" for row in store.test_runs))

    def test_a_finished_scan_still_persists(self):
        store = MemoryStore()

        def scan_one(address, settings=None, store=None, **kwargs):
            return _bare_result()

        class Settings:
            eth_rpc_url = "http://127.0.0.1:9"
            range_min_usd = None
            range_max_usd = None

        report = rerun.run_signal_rerun(
            store,
            Settings(),
            budget_cu=rerun.PER_CONTRACT_CU,
            deadline_s=120,
            lease_wait_s=2,
            scan_one=scan_one,
        )
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["rerun_count"], 1)
        self.assertEqual(len(store.test_runs), 1)
        self.assertEqual(store.test_runs[0]["status"], "done")


class TriggerQueue(unittest.TestCase):
    def test_queue_1_push_stays_on_queue_1(self):
        event = {"commits": [{"modified": [rerun.Q1_TRIGGER]}]}
        self.assertEqual(rerun.queue_id_for_github_event(event, "push"), "1")

    def test_queue_2_file_alone_selects_queue_2(self):
        event = {"head_commit": {"added": [rerun.Q2_TRIGGER]}}
        self.assertEqual(rerun.queue_id_for_github_event(event, "push"), "2")

    def test_queue_1_file_wins_when_both_change(self):
        event = {
            "commits": [
                {"modified": [rerun.Q2_TRIGGER]},
                {"modified": [rerun.Q1_TRIGGER]},
            ]
        }
        self.assertEqual(rerun.queue_id_for_github_event(event, "push"), "1")

    def test_an_unrelated_push_stays_on_queue_1(self):
        event = {"commits": [{"modified": ["README.md"]}]}
        self.assertEqual(rerun.queue_id_for_github_event(event, "push"), "1")
        self.assertEqual(rerun.queue_id_for_github_event({}, "push"), "1")
        self.assertEqual(rerun.queue_id_for_github_event(None, ""), "1")

    def test_dispatch_uses_its_queue_input(self):
        self.assertEqual(
            rerun.queue_id_for_github_event({"inputs": {"queue": "2", "mode": "small-value-batch"}}, "workflow_dispatch"),
            "2",
        )
        self.assertEqual(
            rerun.queue_id_for_github_event({"inputs": {"queue": "1"}}, "workflow_dispatch"),
            "1",
        )
        self.assertEqual(
            rerun.queue_id_for_github_event({"inputs": {}}, "workflow_dispatch"),
            "1",
        )

    def test_workflow_keeps_both_triggers_and_the_queue_1_command(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / ".github/workflows/eth-scanner-signal-rerun.yml").read_text(encoding="utf-8")
        self.assertIn("eth-scanner/signal-rerun.trigger", text)
        self.assertIn("eth-scanner/signal-rerun-q2.trigger", text)
        self.assertIn("queue_id_for_github_event", text)
        self.assertIn("python -m eth_scanner signal-rerun --small-value-batch --batch-size 75 --budget-cu 250000", text)
        self.assertIn("python -m eth_scanner signal-rerun --small-value-batch --queue 2 --batch-size 75 --budget-cu 250000", text)
        queue1 = text.split("else", 1)[1]
        self.assertNotIn("--queue 2", queue1)
        self.assertIn('elif [ "${RERUN_QUEUE}" = "2" ]', text)
        self.assertIn("workflow_dispatch", text)
        self.assertIn("group: eth-scanner-signal-rerun", text)
        self.assertIn("cancel-in-progress: false", text)


if __name__ == "__main__":
    unittest.main()
