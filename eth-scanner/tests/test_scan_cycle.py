"""The scheduler walks every configured list, then random contracts."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import Settings
from eth_scanner.feed.lists import NamedList, get_list_config, load_named_list
from eth_scanner.feed.master_list import MasterCandidate, list_fingerprint
from eth_scanner.feed.runner import list_pass_complete, run_scan_cycle
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import FunnelResult


def _addr(n: int) -> str:
    return "0x%040x" % n


def _cand(n: int, usd: float = 100.0) -> MasterCandidate:
    return MasterCandidate(
        address=_addr(n),
        protocol="P%d" % n,
        slug="p%d" % n,
        category="vault",
        est_usd_held=usd,
        candidate_reason="odd",
        tier=2,
        rank=n,
    )


def _result(funds: float = 4000.0) -> FunnelResult:
    return FunnelResult(
        bucket="lane-a-cool",
        dropped=False,
        drop_reason=None,
        heat=0,
        src_confidence="high",
        ir_confidence="med",
        funds_usd=funds,
        funds_status="ok",
        contract_name="Vault",
    )


class ScanCycle(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            dry_run=True,
            etherscan_api_keys=["test-key"],
            min_funds_usd=2000.0,
            work_dir=Path("/tmp/eth-scanner-cycle"),
        )
        self.store = MemoryStore()
        self.lists = {
            "list-1": [_cand(1, 5000), _cand(2, 4000)],
            "list-2": [_cand(3, 80), _cand(4, 90)],
        }

    def _named(self, list_id: str) -> NamedList:
        cfg = get_list_config(list_id)
        rows = self.lists[list_id]
        return NamedList(config=cfg, candidates=rows, source="test", total_usd=0)

    def test_list_order_then_random_and_new_rows_come_back_first(self):
        events: list[tuple] = []
        picks = {"n": 0}

        def scan(addr: str) -> FunnelResult:
            events.append(("scan", addr, self.settings.range_min_usd, self.settings.range_max_usd))
            return _result()

        def pick(skip: set[str]) -> str | None:
            events.append(("pick",))
            picks["n"] += 1
            if picks["n"] > 1:
                return None
            chosen = _addr(99)
            if chosen in skip:
                chosen = _addr(100)
            self.assertTrue(all(chosen != _addr(i) for i in range(1, 6)))
            return chosen

        with mock.patch("eth_scanner.feed.runner.load_named_list", side_effect=self._named), \
             mock.patch("eth_scanner.feed.runner._blend_note", return_value="blend gauntlet: medusa=skipped"):
            first = run_scan_cycle(
                settings=self.settings,
                store=self.store,
                workers=1,
                deadline_monotonic=time.monotonic() + 30,
                scan_one=scan,
                pick_random=pick,
                random_enabled=True,
            )
        self.assertEqual([row["list_id"] for row in first.lists], ["list-1", "list-2"])
        self.assertEqual(first.random_scanned, 1)
        scanned = [item[1] for item in events if item[0] == "scan"]
        self.assertEqual(scanned[:2], [_addr(1), _addr(2)])
        self.assertEqual(scanned[2:4], [_addr(3), _addr(4)])
        self.assertEqual(scanned[4], _addr(99))
        self.assertEqual(events[4][0], "pick")
        # List 2 keeps its own band. Random uses the discovery floor ($100), no ceiling.
        self.assertEqual(events[2][2:], (50.0, 1900.0))
        self.assertEqual(events[4][0], "pick")
        random_scan = next(item for item in events if item[0] == "scan" and item[1] == _addr(99))
        self.assertEqual(random_scan[2:], (100.0, None))
        random_row = next(row for row in self.store.test_runs if row["address"] == _addr(99))
        self.assertEqual(random_row["discovery_source"], "random_scan")
        self.assertIsNone(random_row["list_id"])
        self.assertTrue(str(random_row["dedupe_key"]).startswith("random:"))
        self.assertEqual(random_row["heat"], 0)
        self.assertIn("blend gauntlet", " ".join(random_row["notes"]))
        list2_rows = [row for row in self.store.test_runs if row.get("list_id") == "list-2"]
        self.assertEqual(len(list2_rows), 2)
        self.assertTrue(all(str(row["dedupe_key"]).startswith("master-list:list-2:") for row in list2_rows))

        # Finished lists are not walked again.
        events.clear()
        with mock.patch("eth_scanner.feed.runner.load_named_list", side_effect=self._named):
            again = run_scan_cycle(
                settings=self.settings,
                store=self.store,
                workers=1,
                deadline_monotonic=time.monotonic() + 30,
                scan_one=scan,
                pick_random=lambda _skip: None,
                random_enabled=False,
            )
        self.assertEqual(again.status, "done")
        self.assertEqual(again.lists, [])
        self.assertEqual(events, [])

        # A new list row changes the fingerprint and is scanned before randoms.
        self.lists["list-1"] = [_cand(1, 5000), _cand(2, 4000), _cand(5, 3000)]
        events.clear()
        picks["n"] = 0
        with mock.patch("eth_scanner.feed.runner.load_named_list", side_effect=self._named), \
             mock.patch("eth_scanner.feed.runner._blend_note", return_value="blend gauntlet: skipped"):
            third = run_scan_cycle(
                settings=self.settings,
                store=self.store,
                workers=1,
                deadline_monotonic=time.monotonic() + 30,
                scan_one=scan,
                pick_random=pick,
                random_enabled=True,
            )
        self.assertEqual([row["list_id"] for row in third.lists], ["list-1"])
        self.assertEqual(events[0][0], "scan")
        self.assertLess(
            events.index(("scan", _addr(5), 2000.0, 9_000_000.0)),
            next(i for i, item in enumerate(events) if item[0] == "pick"),
        )

    def test_real_list_2_is_scanned_once_list_1_is_done(self):
        listed = load_named_list("list-1")
        sha = list_fingerprint(listed.candidates)
        self.store.upsert_backfill({
            "id": "master-list",
            "start_block": 0,
            "end_block": len(listed.candidates),
            "cursor_block": 0,
            "status": "done",
            "source": "master_list",
            "stats": {
                "list_sha": sha,
                "passes_completed": 1,
                "list_size": len(listed.candidates),
            },
        })
        self.assertTrue(list_pass_complete(
            self.store.get_backfill("master-list"),
            len(listed.candidates),
            sha,
        ))
        seen: list[str] = []

        def scan(addr: str) -> FunnelResult:
            seen.append(addr)
            return _result(funds=100.0)

        progress = run_scan_cycle(
            settings=self.settings,
            store=self.store,
            workers=1,
            deadline_monotonic=time.monotonic() + 60,
            scan_one=scan,
            random_enabled=False,
        )
        list2 = load_named_list("list-2")
        self.assertEqual(list2.source, "list2_candidates")
        self.assertEqual(len(list2.candidates), 929)
        self.assertEqual(len(progress.lists), 1)
        self.assertEqual(progress.lists[0]["list_id"], "list-2")
        self.assertEqual(progress.lists[0]["status"], "done")
        self.assertEqual(progress.lists[0]["processed"], 929)
        self.assertEqual(len(seen), 929)
        rows = [row for row in self.store.test_runs if row.get("list_id") == "list-2"]
        self.assertEqual(len(rows), 929)
        self.assertTrue(all(str(row["dedupe_key"]).startswith("master-list:list-2:") for row in rows))
        self.assertEqual(progress.status, "done")

        second = run_scan_cycle(
            settings=self.settings,
            store=self.store,
            workers=1,
            deadline_monotonic=time.monotonic() + 30,
            scan_one=scan,
            random_enabled=False,
        )
        self.assertEqual(second.status, "done")
        self.assertEqual(second.lists, [])
        self.assertEqual(len(seen), 929)


if __name__ == "__main__":
    unittest.main()
