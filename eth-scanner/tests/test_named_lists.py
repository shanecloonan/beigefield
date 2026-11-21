"""Named master lists: List 1 stays the curated feed. List 2 is the junk drawer.

No live RPC. No heat-rule changes.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from eth_scanner.config import Settings
from eth_scanner.feed.lists import (
    append_manual_address,
    clear_list_cache,
    get_list_config,
    is_big_or_canonical_name,
    load_named_list,
    select_list2,
)
from eth_scanner.feed.master_list import MasterCandidate, load_master_candidates
from eth_scanner.feed.runner import run_master_list
from eth_scanner.ingest.funds import FundsSnapshot, funds_range_reason
from eth_scanner.lane_a.worker import run_one
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import FunnelResult


def _row(addr: str, protocol: str, usd: float, reason: str, slug: str = "") -> MasterCandidate:
    return MasterCandidate(
        address=addr,
        protocol=protocol,
        slug=slug or protocol.lower(),
        category="vault",
        est_usd_held=usd,
        candidate_reason=reason,
        tier=3,
        rank=1,
        source="test",
    )


class ListConfigTests(unittest.TestCase):
    def test_bounds_live_on_the_list_config(self) -> None:
        one = get_list_config("list-1")
        two = get_list_config("list-2")
        self.assertEqual(one.name, "List 1")
        self.assertEqual((one.min_funds_usd, one.max_funds_usd), (2000.0, 9_000_000.0))
        self.assertEqual(two.name, "List 2")
        self.assertEqual((two.min_funds_usd, two.max_funds_usd), (50.0, 1900.0))
        self.assertIn("junk-drawer", two.summary.lower())
        self.assertIn("funded", one.summary.lower())

    def test_list1_contents_match_the_curated_feed(self) -> None:
        clear_list_cache()
        named = load_named_list("list-1")
        curated = load_master_candidates()
        # Manual addresses are prepended and not re-ranked; the rest is the curated feed.
        non_manual = [row for row in named.candidates if row.source != "manual"]
        self.assertEqual([row.address for row in non_manual], [row.address for row in curated])
        self.assertEqual(named.source, "master_candidates")
        self.assertGreaterEqual(len(named.candidates), len(curated))


class List2SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = get_list_config("list-2")

    def test_sketchy_filter_drops_big_names_and_ranks_odd_patterns_first(self) -> None:
        sushi = "0x" + "11" * 20
        unknown = "0x" + "22" * 20
        hacked = "0x" + "33" * 20
        plain = "0x" + "44" * 20
        rich = "0x" + "55" * 20
        rows = [
            _row(sushi, "SushiSwap", 400, "below-2000-usd-priced", "sushiswap"),
            _row(plain, "Varen", 1800, "below-2000-usd-priced", "varen"),
            _row(unknown, "univ2-fork-unknown", 80, "below-2000-usd-priced", "univ2-fork-unknown"),
            _row(hacked, "Percent Finance", 600, "below-2000-usd-priced;past-hack;no-audit", "percent-finance"),
            _row(rich, "ChickenSwap", 50_000, "below-2000-usd-priced", "chickenswap"),
        ]
        kept = select_list2(rows, self.cfg, from_excluded=True)
        addrs = [row.address for row in kept]
        self.assertNotIn(sushi, addrs)
        self.assertNotIn(rich, addrs)
        self.assertEqual(addrs[0], hacked)
        self.assertLess(addrs.index(unknown), addrs.index(plain))
        self.assertTrue(is_big_or_canonical_name("PancakeSwap AMM", "pancake"))
        self.assertFalse(is_big_or_canonical_name("univ2-fork-unknown", "univ2-fork-unknown"))

    def test_real_excluded_seed_is_the_sketchy_band(self) -> None:
        os.environ.pop("ETH_SCANNER_LIST2", None)
        clear_list_cache()
        named = load_named_list("list-2")
        self.assertEqual(named.source, "list2_candidates")
        self.assertTrue(str(named.source_path).endswith("list2_candidates.json"))
        self.assertEqual(len(named.candidates), 313)
        self.assertAlmostEqual(named.total_usd, 211226.03, places=2)
        self.assertEqual(named.config.min_funds_usd, 50.0)
        self.assertEqual(named.config.max_funds_usd, 1900.0)
        for row in named.candidates:
            if row.source == "manual":
                continue
            if named.source == "excluded_fallback":
                self.assertGreaterEqual(row.est_usd_held, 50)
                self.assertLessEqual(row.est_usd_held, 1900)
                self.assertIn("below-2000", row.candidate_reason)
            self.assertFalse(is_big_or_canonical_name(row.protocol, row.slug))
        if named.source == "excluded_fallback":
            self.assertGreater(named.total_usd, 0)

    def test_list2_file_wins_over_excluded(self) -> None:
        folder = Path("/tmp/list2-file-wins")
        folder.mkdir(exist_ok=True)
        path = folder / "list2_candidates.json"
        addr = "0x" + "ab" * 20
        path.write_text(json.dumps([
            {
                "address": addr,
                "protocol": "Odd Drawer",
                "slug": "odd-drawer",
                "funds_usd": 120,
                "candidate_reason": "abandoned;no-audit;odd-pattern",
                "drain_probability": 10,
            },
            {
                "address": "0x" + "cd" * 20,
                "protocol": "SushiSwap",
                "slug": "sushiswap",
                "funds_usd": 400,
                "candidate_reason": "below-2000-usd-priced",
            },
        ]), encoding="utf-8")
        os.environ["ETH_SCANNER_LIST2"] = str(path)
        clear_list_cache()
        try:
            named = load_named_list("list-2")
        finally:
            os.environ.pop("ETH_SCANNER_LIST2", None)
            clear_list_cache()
        self.assertEqual(named.source, "list2_candidates")
        # Manual addresses stay prepended; the file itself should win over excluded.csv.
        non_manual = [row for row in named.candidates if row.source != "manual"]
        self.assertEqual([row.address for row in non_manual], [addr])
        self.assertTrue(any(row.address == addr for row in named.candidates))
        self.assertFalse(any(row.protocol == "SushiSwap" for row in named.candidates))
        self.assertAlmostEqual(named.total_usd, 120.0)


class ListRangeAndManualTests(unittest.TestCase):
    def test_range_reason_uses_the_passed_bounds(self) -> None:
        self.assertIn("below funds floor", funds_range_reason(12, 50, 1900) or "")
        self.assertIn("above funds ceiling", funds_range_reason(12_000_000, 2000, 9_000_000) or "")
        self.assertIsNone(funds_range_reason(800, 50, 1900))

    def test_worker_drops_above_list_ceiling_without_fetching_source(self) -> None:
        settings = Settings(
            dry_run=True,
            work_dir=Path("/tmp/eth-scanner-test-range"),
            min_funds_usd=2000.0,
            range_min_usd=2000.0,
            range_max_usd=9_000_000.0,
        )
        store = MemoryStore()
        snap = FundsSnapshot(status="ok", total_usd=12_000_000.0, breakdown=[], checked_at="2026-01-01T00:00:00+00:00")
        with mock.patch("eth_scanner.lane_a.worker.probe_contract_funds", return_value=snap):
            with mock.patch("eth_scanner.lane_a.worker._ingest") as ingest:
                result = run_one("0x" + "ef" * 20, settings=settings, store=store)
                ingest.assert_not_called()
        self.assertTrue(result.dropped)
        self.assertIn("above funds ceiling", result.drop_reason or "")
        self.assertEqual(result.heat, 0)

    def test_list2_bounds_drive_the_runner(self) -> None:
        path = Path("/tmp/list2-runner.json")
        addr = "0x" + "10" * 20
        path.write_text(json.dumps([{
            "address": addr,
            "protocol": "Odd",
            "est_usd_held": 100,
            "candidate_reason": "odd",
            "tier": 3,
            "rank": 1,
        }]), encoding="utf-8")
        settings = Settings(dry_run=True, work_dir=Path("/tmp/eth-scanner-test-list2-run"), min_funds_usd=2000.0)
        store = MemoryStore()

        def scan(_addr: str) -> FunnelResult:
            return FunnelResult(
                bucket="lane-a-cool",
                heat=0,
                src_confidence="high",
                ir_confidence="med",
                funds_usd=100.0,
                funds_status="ok",
            )

        progress = run_master_list(
            settings=settings,
            store=store,
            path=path,
            list_id="list-2",
            workers=1,
            deadline_monotonic=10**12,
            scan_one=scan,
        )
        self.assertEqual(settings.range_min_usd, 50.0)
        self.assertEqual(settings.range_max_usd, 1900.0)
        self.assertEqual(settings.min_funds_usd, 2000.0)
        self.assertEqual(progress.list_id, "list-2")
        self.assertEqual(store.test_runs[0]["list_id"], "list-2")
        self.assertTrue(store.test_runs[0]["dedupe_key"].startswith("master-list:list-2:"))

    def test_manual_append_validates_and_dedupes(self) -> None:
        path = Path("/tmp/list-manual.json")
        if path.exists():
            path.unlink()
        os.environ["ETH_SCANNER_LIST_MANUAL"] = str(path)
        clear_list_cache()
        try:
            ok, msg = append_manual_address("list-2", "not-an-address")
            self.assertFalse(ok)
            ok, addr = append_manual_address("list-2", "0xABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD")
            self.assertTrue(ok)
            self.assertEqual(addr, "0x" + "abcdefabcdefabcdefabcdefabcdefabcdefabcd"[:40])
            again, _ = append_manual_address("list-2", addr)
            self.assertFalse(again)
            named = load_named_list("list-2")
            self.assertEqual(named.candidates[0].address, addr)
            self.assertEqual(named.candidates[0].source, "manual")
        finally:
            os.environ.pop("ETH_SCANNER_LIST_MANUAL", None)
            clear_list_cache()


if __name__ == "__main__":
    unittest.main()
