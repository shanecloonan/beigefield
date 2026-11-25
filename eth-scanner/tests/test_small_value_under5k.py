"""Under-$5k queue rules and the batched signal-rerun cut."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.desk import signal_rerun as rerun
from eth_scanner.desk import small_value_under5k as queue
from eth_scanner.store.supabase import MemoryStore


def _row(**kwargs):
    base = {
        "address": "0x" + "11" * 20,
        "contract_name": "Vault",
        "funds_usd": 400.0,
        "signals": ["vault"],
        "unverified": False,
        "family": "",
        "list": "list-2",
        "source": "candidate-pool",
    }
    base.update(kwargs)
    return base


class Rules(unittest.TestCase):
    def test_structural_class_outranks_a_bare_unverified_leftover(self):
        self.assertEqual(queue.assign_reason(["upgradeable", "vault"], unverified=True, family=""), "clone-proxy-takeover")
        self.assertEqual(queue.assign_reason([], unverified=True, family=""), "unverified-leftover")
        self.assertEqual(queue.assign_reason([], unverified=False, family="erc4626"), "clone-erc4626-inflation")
        self.assertEqual(queue.assign_reason([], unverified=False, family="rari"), "lending-underscanned")
        self.assertEqual(queue.assign_reason([], unverified=False, family="univ2"), "amm-fork-thin-pool")
        self.assertEqual(queue.assign_reason([], unverified=False, family=""), "")
        self.assertGreater(
            queue.score_of("clone-proxy-takeover", unverified=True),
            queue.score_of("unverified-leftover", unverified=True),
        )

    def test_funds_outside_the_band_and_blocked_addresses_drop(self):
        rows = [
            _row(address="0x" + "aa" * 20, funds_usd=4999.99, signals=["vault"]),
            _row(address="0x" + "bb" * 20, funds_usd=5000, signals=["upgradeable"]),
            _row(address="0x" + "cc" * 20, funds_usd=99.99, signals=["lending"]),
            _row(address="0x" + "dd" * 20, funds_usd=200, signals=[], unverified=True),
            _row(address="0x" + "ee" * 20, funds_usd=300, signals=[], unverified=False),
        ]
        kept, deferred = queue.rank_candidates(rows, limit=10, blocked={"0x" + "aa" * 20})
        self.assertEqual(deferred, [])
        self.assertEqual([row["address"] for row in kept], ["0x" + "dd" * 20])

    def test_cap_keeps_the_higher_score_and_the_smaller_funds(self):
        rows = [
            _row(address="0x" + "01" * 20, funds_usd=4000, signals=[], unverified=True),
            _row(address="0x" + "02" * 20, funds_usd=150, signals=["vault"]),
            _row(address="0x" + "03" * 20, funds_usd=180, signals=["vault"]),
        ]
        kept, deferred = queue.rank_candidates(rows, limit=2)
        self.assertEqual([row["address"] for row in kept], ["0x" + "02" * 20, "0x" + "03" * 20])
        self.assertEqual(deferred[0]["reason_class"], "unverified-leftover")

    def test_batch_stops_at_the_cu_ceiling_and_skips_finished(self):
        entries = [
            {"address": "0x" + ("%040x" % n), "peak_heat": 4, "reason_class": "clone-erc4626-inflation", "contract_name": "V"}
            for n in range(1, 6)
        ]
        selected, deferred, cap = queue.take_batch(
            entries,
            skip={"0x" + ("%040x" % 1)},
            batch_size=10,
            budget_cu=queue.PER_CONTRACT_CU * 2,
        )
        self.assertEqual([row["address"] for row in selected], ["0x" + ("%040x" % 2), "0x" + ("%040x" % 3)])
        self.assertEqual(len(deferred), 2)
        self.assertLessEqual(cap, queue.SMALL_VALUE_BATCH_CU)
        self.assertLessEqual(cap, queue.PER_CONTRACT_CU * 2)

    def test_a_four_million_budget_still_caps_one_batch(self):
        entries = [
            {"address": "0x" + ("%040x" % n), "peak_heat": 3, "reason_class": "unverified-leftover", "contract_name": "U"}
            for n in range(1, 200)
        ]
        selected, _deferred, cap = queue.take_batch(
            entries,
            skip=set(),
            batch_size=queue.SMALL_VALUE_BATCH,
            budget_cu=4_000_000,
        )
        self.assertEqual(len(selected), queue.SMALL_VALUE_BATCH)
        self.assertLessEqual(cap, queue.SMALL_VALUE_BATCH_CU)
        self.assertLess(cap, 4_000_000)


class CommittedQueue(unittest.TestCase):
    def test_file_matches_the_selector_and_stays_under_five_thousand(self):
        kept, _deferred = queue.rank_candidates(queue.collect_repo_candidates(), limit=queue.QUEUE_LIMIT)
        payload = json.loads(queue.queue_path().read_text(encoding="utf-8"))
        committed = [row["address"] for row in payload["entries"]]
        self.assertEqual(committed, [row["address"] for row in kept])
        self.assertEqual(len(committed), 300)
        self.assertEqual(len(set(committed)), 300)
        old = json.loads((ROOT / "data" / "small_value_queue.json").read_text(encoding="utf-8"))
        old_addrs = {str(row["address"]).lower() for row in old["entries"]}
        for row in payload["entries"]:
            self.assertLess(float(row["funds_usd"]), 5000)
            self.assertGreaterEqual(float(row["funds_usd"]), 100)
            self.assertEqual(row["chain"], "ethereum")
            self.assertNotIn(row["address"], old_addrs)
            self.assertIn(row["reason_class"], queue.REASON_SCORE)


class BatchRun(unittest.TestCase):
    def test_dry_run_takes_one_batch_and_the_next_call_moves_on(self):
        store = MemoryStore()
        called = []

        def boom(address, **kwargs):
            called.append(address)
            raise AssertionError("dry-run scanned")

        class Settings:
            eth_rpc_url = "http://127.0.0.1:1"

        first = rerun.run_signal_rerun(
            store,
            Settings(),
            budget_cu=4_000_000,
            dry_run=True,
            scan_one=boom,
            small_value_batch=True,
            batch_size=75,
        )
        self.assertEqual(called, [])
        self.assertEqual(first["status"], "dry-run")
        self.assertEqual(first["mode"], "small-value-under5k")
        self.assertEqual(first["selected"], 75)
        self.assertLessEqual(first["budget_cu"], queue.SMALL_VALUE_BATCH_CU)
        self.assertLess(first["estimate"]["estimated_cu"], 4_000_000)
        seen = [row["address"] for row in first["selected_rows"]]
        for addr in seen:
            store.save_test_scan_run({
                "dedupe_key": "signal-rerun:%s" % addr,
                "address": addr,
                "discovery_source": "signal_rerun",
                "status": "done",
            })
        second = rerun.run_signal_rerun(
            store,
            Settings(),
            budget_cu=250_000,
            dry_run=True,
            scan_one=boom,
            small_value_batch=True,
            batch_size=75,
        )
        nxt = [row["address"] for row in second["selected_rows"]]
        self.assertEqual(len(nxt), 75)
        self.assertEqual(set(seen) & set(nxt), set())
        self.assertEqual(second["skipped_finished"], 75)


if __name__ == "__main__":
    unittest.main()
