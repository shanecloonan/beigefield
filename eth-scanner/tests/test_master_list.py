"""Curated master-list feed: order, resume cursor, and test_scan_runs metadata.

No live RPC. Lane A is stubbed. Heat rules are not exercised here.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import Settings
from eth_scanner.feed.master_list import (
    HAND_RANKED_FILENAME,
    default_master_list_path,
    list_fingerprint,
    load_master_candidates,
)
from eth_scanner.feed.runner import CURSOR_ID, DISCOVERY_SOURCE, run_master_list
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import FunnelResult


def _cand(
    addr: str,
    tier: int,
    usd: float,
    reason: str,
    rank: int,
    drain: float = 0.0,
    tvl: float = 0.0,
) -> dict:
    return {
        "protocol": "P%s" % rank,
        "slug": "p%s" % rank,
        "category": "Lending",
        "address": addr,
        "est_usd_held": usd,
        "defillama_eth_tvl": tvl,
        "candidate_reason": reason,
        "tier": tier,
        "rank": rank,
        "drain_probability": drain,
        "verified_contract": True,
    }


def _result(heat: int = 0, bucket: str = "lane-a-cool", funds: float = 5000.0, dropped: bool = False) -> FunnelResult:
    return FunnelResult(
        bucket=bucket,  # type: ignore[arg-type]
        dropped=dropped,
        drop_reason="below funds floor ($10 < $2,000)" if dropped else None,
        heat=heat,
        src_confidence="high",
        ir_confidence="med",
        funds_usd=10.0 if dropped else funds,
        funds_status="ok",
        contract_class="vault",
        scope="in-scope",
        contract_name="Vault",
    )


class MasterListOrder(unittest.TestCase):
    def test_committed_feed_shape_and_order(self):
        path = default_master_list_path()
        self.assertTrue(path.is_file(), path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        hand = json.loads((path.parent / HAND_RANKED_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(len(raw), 1322)
        self.assertEqual(len(hand), 197)

        def _valid(addr: object) -> str:
            text = str(addr or "").strip().lower()
            if text.startswith("0x") and len(text) == 42 and all(c in "0123456789abcdef" for c in text[2:]):
                return text
            return ""

        expected = {
            addr for addr in (_valid(r.get("address")) for r in list(raw) + list(hand)) if addr
        }
        rows = load_master_candidates(path)
        self.assertEqual(len(rows), len(expected))
        self.assertEqual({r.address for r in rows}, expected)
        for i in range(1, len(rows)):
            prev, cur = rows[i - 1], rows[i]
            self.assertGreaterEqual(prev.drain_probability, cur.drain_probability)
            if prev.drain_probability == cur.drain_probability:
                self.assertLessEqual(prev.tier, cur.tier)
                if prev.tier == cur.tier:
                    self.assertGreaterEqual(prev.est_usd_held, cur.est_usd_held)
                    if prev.est_usd_held == cur.est_usd_held:
                        self.assertGreaterEqual(
                            float(prev.defillama_eth_tvl or 0.0),
                            float(cur.defillama_eth_tvl or 0.0),
                        )
        self.assertEqual(rows[0].address, "0x3fda67f7583380e67ef93072294a7fac882fd7e7")
        self.assertAlmostEqual(rows[0].drain_probability, 0.85)
        self.assertIn("MoneyMarket", rows[0].evidence_note)
        gold = next(r for r in rows if r.address == "0x8481a6ebaf5c7dabc3f7e09e44a89531fd31f822")
        self.assertAlmostEqual(gold.drain_probability, 0.79)
        self.assertIn("Goldfinch", gold.evidence_note)
        self.assertEqual(gold.tier, 1)
        self.assertGreaterEqual(rows[0].drain_probability, 0.60)
        self.assertTrue(all(r.candidate_reason for r in rows[:10]))
        self.assertTrue(all(r.contract_class for r in rows[:10]))

    def test_drain_probability_outranks_tier_and_usd(self):
        path = Path("/tmp/master-list-drain-order.json")
        low = "0x1111111111111111111111111111111111111111"
        high = "0x2222222222222222222222222222222222222222"
        path.write_text(json.dumps([
            _cand(low, 1, 9_000_000, "rich-cold", 1, drain=0.10, tvl=9_000_000),
            _cand(high, 3, 3_000, "lean-hot", 9, drain=0.80, tvl=1),
        ]), encoding="utf-8")
        rows = load_master_candidates(path)
        self.assertEqual([r.address for r in rows], [high, low])

    def test_hand_ranked_overlay_appends_and_replaces(self):
        folder = Path("/tmp/master-list-overlay")
        folder.mkdir(exist_ok=True)
        base = folder / "master_candidates.json"
        kept = "0x1111111111111111111111111111111111111111"
        replaced = "0x2222222222222222222222222222222222222222"
        added = "0x3333333333333333333333333333333333333333"
        base.write_text(json.dumps([
            _cand(kept, 1, 50_000, "base-kept", 1, drain=0.70),
            _cand(replaced, 1, 80_000, "base-old", 2, drain=0.40),
        ]), encoding="utf-8")
        (folder / HAND_RANKED_FILENAME).write_text(json.dumps([
            {
                "address": replaced,
                "protocol": "Handed",
                "funds_usd": 4000,
                "drain_probability": 91,
                "candidate_reason": "hand-replaced",
                "evidence_note": "manual review replaced the base prior",
                "source": "hand:test",
            },
            _cand(added, 2, 5_000, "hand-added", 2, drain=0.55),
        ]), encoding="utf-8")
        rows = load_master_candidates(base)
        self.assertEqual([r.address for r in rows], [replaced, kept, added])
        self.assertEqual(rows[0].candidate_reason, "hand-replaced")
        self.assertAlmostEqual(rows[0].drain_probability, 0.91)
        self.assertEqual(rows[0].tier, 1)
        self.assertEqual(rows[0].evidence_note, "manual review replaced the base prior")
        self.assertEqual(rows[0].est_usd_held, 4000)
        self.assertEqual(rows[2].candidate_reason, "hand-added")

    def test_dedupe_keeps_higher_priority_row(self):
        path = Path("/tmp/master-list-dedupe.json")
        addr = "0x1111111111111111111111111111111111111111"
        path.write_text(json.dumps([
            _cand(addr, 2, 9_000, "later", 2),
            _cand(addr, 1, 1_000, "better-tier", 9),
            _cand("0x2222222222222222222222222222222222222222", 1, 50_000, "richer", 3),
            _cand("0x2222222222222222222222222222222222222222", 1, 10, "poorer", 1),
        ]), encoding="utf-8")
        rows = load_master_candidates(path)
        self.assertEqual([r.address for r in rows], [
            "0x2222222222222222222222222222222222222222",
            addr,
        ])
        self.assertEqual(rows[0].candidate_reason, "richer")
        self.assertEqual(rows[1].candidate_reason, "better-tier")
        self.assertEqual(rows[1].tier, 1)


class MasterListRunner(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp/master-list-runner.json")
        self.rows = [
            _cand("0x%040x" % (i + 1), 1 if i < 3 else 2, 100_000 - i * 1000, "reason-%d" % i, i + 1)
            for i in range(6)
        ]
        self.path.write_text(json.dumps(self.rows), encoding="utf-8")
        self.store = MemoryStore()
        self.settings = Settings(dry_run=True, etherscan_api_keys=[], eth_rpc_url="", worker_id="master-test")

    def test_resume_cursor_and_metadata(self):
        seen: list[str] = []

        def scan(addr: str) -> FunnelResult:
            seen.append(addr)
            if addr.endswith("1"):
                return _result(heat=4, bucket="lane-b-queue", funds=80_000)
            if addr.endswith("2"):
                return _result(dropped=True)
            return _result()

        first = run_master_list(
            settings=self.settings,
            store=self.store,
            path=self.path,
            workers=2,
            deadline_monotonic=time.monotonic() - 1,
            scan_one=scan,
        )
        self.assertEqual(first.status, "running")
        self.assertEqual(first.processed, 2)
        self.assertEqual(first.cursor_start, 0)
        self.assertEqual(first.cursor_next, 2)
        self.assertEqual(first.persisted, 2)
        self.assertEqual(first.heat_gt0, 1)
        self.assertEqual(first.lane_b, 1)
        self.assertEqual(first.below_floor, 1)
        self.assertEqual(len(seen), 2)

        runs = [row for row in self.store.test_runs if str(row.get("dedupe_key") or "").startswith("master-list:")]
        self.assertEqual(len(runs), 2)
        dropped = [row for row in self.store.test_runs if row.get("kind") == "blend"]
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["status"], "dropped")
        self.assertTrue(any(row.get("stage") == "intake" for row in self.store.blend_stages))
        for row in runs:
            self.assertEqual(row["discovery_source"], DISCOVERY_SOURCE)
            self.assertIn("candidate_reason", row)
            self.assertEqual(row["tier"], 1)
            self.assertTrue(str(row["dedupe_key"]).startswith("master-list:"))
        hot = next(r for r in runs if r["address"].endswith("1"))
        self.assertEqual(hot["bucket"], "lane-b-queue")
        self.assertEqual(hot["heat"], 4)
        self.assertEqual(hot["candidate_reason"], "reason-0")

        cursor = self.store.get_backfill(CURSOR_ID)
        self.assertIsNotNone(cursor)
        assert cursor is not None
        self.assertEqual(int(cursor["cursor_block"]), 2)
        self.assertEqual(cursor["source"], DISCOVERY_SOURCE)
        # Lease is released when the job returns so the next run can continue.
        self.assertFalse((cursor.get("stats") or {}).get("lease_owner"))

        second = run_master_list(
            settings=self.settings,
            store=self.store,
            path=self.path,
            workers=1,
            max_scans=2,
            deadline_monotonic=time.monotonic() + 30,
            scan_one=scan,
        )
        self.assertTrue(second.resumed)
        self.assertEqual(second.cursor_start, 2)
        self.assertEqual(second.processed, 2)
        self.assertEqual(second.cursor_next, 4)
        self.assertEqual(seen[2], "0x%040x" % 3)

    def test_full_pass_resets_cursor(self):
        def scan(_addr: str) -> FunnelResult:
            return _result()

        done = run_master_list(
            settings=self.settings,
            store=self.store,
            path=self.path,
            workers=3,
            deadline_monotonic=time.monotonic() + 30,
            scan_one=scan,
        )
        self.assertEqual(done.status, "done")
        self.assertEqual(done.processed, 6)
        self.assertEqual(done.cursor_next, 0)
        self.assertEqual(done.passes_completed, 1)
        cursor = self.store.get_backfill(CURSOR_ID)
        assert cursor is not None
        self.assertEqual(int(cursor["cursor_block"]), 0)

    def test_stale_list_hash_resets_cursor(self):
        def scan(_addr: str) -> FunnelResult:
            return _result()

        run_master_list(
            settings=self.settings,
            store=self.store,
            path=self.path,
            workers=1,
            max_scans=2,
            deadline_monotonic=time.monotonic() + 5,
            scan_one=scan,
        )
        row = self.store.get_backfill(CURSOR_ID)
        assert row is not None
        self.assertEqual(int(row["cursor_block"]), 2)
        stats = dict(row.get("stats") or {})
        stats["list_sha"] = "stale-ranking"
        row["stats"] = stats
        self.store.upsert_backfill(row)

        again = run_master_list(
            settings=self.settings,
            store=self.store,
            path=self.path,
            workers=1,
            max_scans=1,
            deadline_monotonic=time.monotonic() + 5,
            scan_one=scan,
        )
        self.assertEqual(again.cursor_start, 0)
        self.assertFalse(again.resumed)
        fresh = self.store.get_backfill(CURSOR_ID)
        assert fresh is not None
        self.assertEqual((fresh.get("stats") or {}).get("list_sha"), list_fingerprint(
            load_master_candidates(self.path)
        ))

    def test_lease_blocks_a_second_owner(self):
        def scan(_addr: str) -> FunnelResult:
            return _result()

        with mock.patch("eth_scanner.feed.runner._lease_owner", return_value="owner-a"):
            run_master_list(
                settings=self.settings,
                store=self.store,
                path=self.path,
                workers=1,
                max_scans=1,
                deadline_monotonic=time.monotonic() + 5,
                scan_one=scan,
            )
        # Re-acquire as if the job were still holding the lease.
        row = self.store.get_backfill(CURSOR_ID)
        assert row is not None
        stats = dict(row.get("stats") or {})
        stats["lease_owner"] = "owner-a"
        stats["lease_until"] = "2999-01-01T00:00:00+00:00"
        row["stats"] = stats
        self.store.upsert_backfill(row)

        with mock.patch("eth_scanner.feed.runner._lease_owner", return_value="owner-b"):
            blocked = run_master_list(
                settings=self.settings,
                store=self.store,
                path=self.path,
                workers=1,
                deadline_monotonic=time.monotonic() + 5,
                scan_one=scan,
            )
        self.assertEqual(blocked.status, "noop")
        self.assertEqual(blocked.processed, 0)

    def test_default_cli_is_master_list_not_discovery(self):
        from eth_scanner.cli import main

        def scan(_addr: str) -> FunnelResult:
            return _result()

        with mock.patch("eth_scanner.feed.runner._default_scan", side_effect=lambda addr, settings: scan(addr)), \
             mock.patch("eth_scanner.cli.open_store", return_value=self.store), \
             mock.patch("eth_scanner.cli.load_settings", return_value=self.settings):
            code = main([
                "monitor",
                "--list-id", "list-1",
                "--list", str(self.path),
                "--workers", "1",
                "--deadline-minutes", "1",
                "--json",
            ])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(self.store.test_runs), 1)
        self.assertTrue(all(r["discovery_source"] == "master_list" for r in self.store.test_runs))


if __name__ == "__main__":
    unittest.main()
