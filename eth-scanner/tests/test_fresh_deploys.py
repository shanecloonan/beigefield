"""Fresh-deploy discovery: creation parsing, triage, cursor, scan-cycle priority."""

from __future__ import annotations

import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import Settings
from eth_scanner.discover.creates import CreateChunkStats
from eth_scanner.discover.fresh import (
    FRESH_SOURCE,
    FRESH_CURSOR_ID,
    contract_address_from_receipt,
    contracts_from_block,
    enqueue_fresh_contracts,
    extract_creation_txs,
    is_creation_tx,
    run_fresh_deploy_discovery,
)
from eth_scanner.discover.recent import DiscoveredContract
from eth_scanner.feed.lists import NamedList, get_list_config
from eth_scanner.feed.master_list import MasterCandidate
from eth_scanner.feed.runner import run_scan_cycle
from eth_scanner.ingest.funds import FundsSnapshot, format_funds_floor_reason
from eth_scanner.store.supabase import MemoryStore
from eth_scanner.types import FunnelResult, Target


ADDR_FUNDED = "0x" + "11" * 20
ADDR_DUST = "0x" + "22" * 20
ADDR_UNKNOWN = "0x" + "33" * 20
ADDR_EXISTING = "0x" + "44" * 20
ADDR_REQUEUE = "0x" + "55" * 20
TX_CREATE = "0x" + "ab" * 32
TX_FAIL = "0x" + "cd" * 32
TX_CALL = "0x" + "ef" * 32


def _block(number=1000, ts=1_700_000_000, txs=None):
    return {
        "number": hex(number),
        "timestamp": hex(ts),
        "transactions": list(txs or []),
    }


def _tx(hash_, to=None, sender="0x" + "aa" * 20, nonce="0x1"):
    return {"hash": hash_, "to": to, "from": sender, "nonce": nonce}


def _receipt(address, status="0x1"):
    return {"contractAddress": address, "status": status}


def _dc(address, block=1000, when="2026-11-17T16:00:00+00:00"):
    return DiscoveredContract(
        address=address,
        deployed_block=block,
        deployed_at=when,
        tx_hash=TX_CREATE,
        source="rpc-create",
    )


def _snap(usd, status="ok"):
    return FundsSnapshot(status=status, total_usd=usd, checked_at="2026-11-17T16:00:00+00:00")


def _probe_map(mapping):
    def probe(addresses):
        out = {}
        for addr in addresses:
            key = addr.lower()
            if key in mapping:
                out[key] = mapping[key]
        return out
    return probe


class CreationTxParsing(unittest.TestCase):
    def test_is_creation_tx_accepts_null_empty_and_0x(self):
        self.assertTrue(is_creation_tx(_tx(TX_CREATE, to=None)))
        self.assertTrue(is_creation_tx(_tx(TX_CREATE, to="")))
        self.assertTrue(is_creation_tx(_tx(TX_CREATE, to="0x")))
        self.assertFalse(is_creation_tx(_tx(TX_CALL, to="0x" + "99" * 20)))
        self.assertFalse(is_creation_tx("not-a-tx"))

    def test_extract_creation_txs_from_full_block(self):
        block = _block(number=123456, ts=1_700_000_012, txs=[
            _tx(TX_CALL, to="0x" + "99" * 20),
            _tx(TX_CREATE, to=None, nonce="0x4"),
            _tx(TX_FAIL, to="0x"),
        ])
        rows = extract_creation_txs(block)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].tx_hash, TX_CREATE)
        self.assertEqual(rows[0].block_number, 123456)
        self.assertEqual(rows[0].nonce, 4)
        self.assertTrue(rows[0].deployed_at.endswith("+00:00") or rows[0].deployed_at.endswith("Z"))
        self.assertEqual(rows[1].tx_hash, TX_FAIL)

    def test_receipt_helpers_and_contracts_from_block(self):
        self.assertEqual(
            contract_address_from_receipt(_receipt(ADDR_FUNDED)),
            ADDR_FUNDED,
        )
        self.assertIsNone(contract_address_from_receipt(_receipt(ADDR_FUNDED, status="0x0")))
        self.assertIsNone(contract_address_from_receipt(_receipt("0x" + "00" * 20)))
        self.assertIsNone(contract_address_from_receipt({}))
        block = _block(number=50, txs=[_tx(TX_CREATE, to=None), _tx(TX_FAIL, to=None)])
        found = contracts_from_block(block, {
            TX_CREATE: _receipt(ADDR_FUNDED),
            TX_FAIL: _receipt(ADDR_DUST, status="0x0"),
        })
        self.assertEqual([r.address for r in found], [ADDR_FUNDED])
        self.assertEqual(found[0].deployed_block, 50)
        self.assertEqual(found[0].tx_hash, TX_CREATE)


class FreshEnqueueAndCursor(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_skips_cleanly_when_rpc_unset(self):
        with mock.patch.dict(os.environ, {"ETH_RPC_URL": ""}, clear=False):
            os.environ.pop("ETH_RPC_URL", None)
            stats = run_fresh_deploy_discovery(store=self.store, rpc_url="")
        self.assertEqual(stats.status, "noop")
        self.assertFalse(stats.rpc_configured)
        self.assertIn("ETH_RPC_URL unset", stats.message)
        self.assertIsNone(self.store.get_backfill(FRESH_CURSOR_ID))
        self.assertEqual(self.store.targets, {})

    def test_below_floor_is_skipped_not_queued(self):
        triage = enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_DUST), _dc(ADDR_FUNDED), _dc(ADDR_UNKNOWN)],
            min_funds_usd=100.0,
            probe_fn=_probe_map({
                ADDR_DUST: _snap(12.0),
                ADDR_FUNDED: _snap(250.0),
                ADDR_UNKNOWN: FundsSnapshot(status="unknown", total_usd=None),
            }),
        )
        self.assertEqual(triage["below_floor"], 1)
        self.assertEqual(triage["enqueued"], 2)
        self.assertEqual(triage["funds_unknown"], 1)
        dust = self.store.get_target(ADDR_DUST)
        funded = self.store.get_target(ADDR_FUNDED)
        unknown = self.store.get_target(ADDR_UNKNOWN)
        self.assertEqual(dust["status"], "skipped")
        self.assertEqual(dust["discovery_source"], FRESH_SOURCE)
        self.assertEqual(dust["deployed_block"], 1000)
        self.assertEqual(funded["status"], "pending")
        self.assertEqual(funded["discovery_source"], FRESH_SOURCE)
        self.assertEqual(funded["funds_usd"], 250.0)
        self.assertEqual(unknown["status"], "pending")
        results = [r for r in self.store.results if r.get("address") == ADDR_DUST]
        self.assertTrue(results)
        self.assertIn("below funds floor", results[-1].get("drop_reason") or "")
        self.assertEqual(results[-1].get("drop_reason"), format_funds_floor_reason(12.0, 100.0))

    def test_upsert_is_idempotent_and_does_not_reset_done(self):
        self.store.upsert_target(Target(
            address=ADDR_EXISTING,
            status="done",
            discovery_source="master_list",
            funds_usd=5000.0,
        ))
        first = enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_FUNDED), _dc(ADDR_EXISTING)],
            min_funds_usd=100.0,
            probe_fn=_probe_map({
                ADDR_FUNDED: _snap(200.0),
                ADDR_EXISTING: _snap(800.0),
            }),
        )
        self.assertEqual(first["enqueued"], 1)
        self.assertEqual(first["already_present"], 1)
        again = enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_FUNDED)],
            min_funds_usd=100.0,
            probe_fn=_probe_map({ADDR_FUNDED: _snap(200.0)}),
        )
        self.assertEqual(again["already_present"], 1)
        self.assertEqual(again["enqueued"], 0)
        existing = self.store.get_target(ADDR_EXISTING)
        self.assertEqual(existing["status"], "done")
        self.assertEqual(existing["discovery_source"], "master_list")

    def test_below_floor_later_funded_is_requeued(self):
        enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_REQUEUE, when="2026-11-17T20:00:00+00:00")],
            min_funds_usd=100.0,
            now=datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc),
            probe_fn=_probe_map({ADDR_REQUEUE: _snap(5.0)}),
        )
        self.assertEqual(self.store.get_target(ADDR_REQUEUE)["status"], "skipped")
        later = enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_REQUEUE, when="2026-11-17T20:00:00+00:00")],
            min_funds_usd=100.0,
            now=datetime(2026, 11, 17, 20, 30, tzinfo=timezone.utc),
            probe_fn=_probe_map({ADDR_REQUEUE: _snap(1500.0)}),
        )
        self.assertEqual(later["requeued"], 1)
        self.assertEqual(self.store.get_target(ADDR_REQUEUE)["status"], "pending")
        self.assertEqual(self.store.get_target(ADDR_REQUEUE)["funds_usd"], 1500.0)

        # Stale skipped-for-floor rows are not revived after the requeue window.
        stale_when = "2026-10-01T00:00:00+00:00"
        enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_DUST, when=stale_when)],
            min_funds_usd=100.0,
            now=datetime(2026, 10, 1, tzinfo=timezone.utc),
            probe_fn=_probe_map({ADDR_DUST: _snap(1.0)}),
        )
        stale = enqueue_fresh_contracts(
            self.store,
            [_dc(ADDR_DUST, when=stale_when)],
            min_funds_usd=100.0,
            now=datetime(2026, 11, 17, tzinfo=timezone.utc),
            probe_fn=_probe_map({ADDR_DUST: _snap(400.0)}),
        )
        self.assertEqual(stale["requeued"], 0)
        self.assertEqual(self.store.get_target(ADDR_DUST)["status"], "skipped")

    def test_cursor_advances_and_next_run_resumes(self):
        def discover(lo, hi):
            self.windows.append((lo, hi))
            return [_dc(ADDR_FUNDED, block=hi)], CreateChunkStats(
                from_block=lo, to_block=hi, source="rpc-receipt-walk", creates=1,
            )

        self.windows = []
        # First run: no cursor, look back 50 from head 10_000, cap 20.
        stats = run_fresh_deploy_discovery(
            store=self.store,
            rpc_url="https://example.invalid",
            lookback=50,
            max_blocks=20,
            min_funds_usd=100.0,
            head_fn=lambda: 10_000,
            discover_fn=discover,
            probe_fn=_probe_map({ADDR_FUNDED: _snap(200.0)}),
        )
        self.assertEqual(stats.status, "done")
        self.assertEqual(stats.from_block, 9950)
        self.assertEqual(stats.to_block, 9969)
        self.assertEqual(stats.cursor_next, 9969)
        self.assertEqual(stats.enqueued, 1)
        self.assertEqual(self.windows, [(9950, 9969)])
        stored = self.store.get_backfill(FRESH_CURSOR_ID)
        self.assertEqual(int(stored["cursor_block"]), 9969)
        self.assertEqual(stored["source"], FRESH_SOURCE)

        # Second run resumes at 9970 and does not insert the same address again.
        stats2 = run_fresh_deploy_discovery(
            store=self.store,
            rpc_url="https://example.invalid",
            lookback=50,
            max_blocks=20,
            min_funds_usd=100.0,
            head_fn=lambda: 10_000,
            discover_fn=discover,
            probe_fn=_probe_map({ADDR_FUNDED: _snap(200.0)}),
        )
        self.assertEqual(stats2.from_block, 9970)
        self.assertEqual(stats2.to_block, 9989)
        self.assertEqual(stats2.already_present, 1)
        self.assertEqual(stats2.enqueued, 0)
        self.assertEqual(int(self.store.get_backfill(FRESH_CURSOR_ID)["cursor_block"]), 9989)

    def test_failed_walk_does_not_advance_cursor(self):
        def boom(lo, hi):
            raise RuntimeError("rpc timeout")

        stats = run_fresh_deploy_discovery(
            store=self.store,
            rpc_url="https://example.invalid",
            lookback=10,
            max_blocks=10,
            head_fn=lambda: 500,
            discover_fn=boom,
        )
        self.assertEqual(stats.status, "error")
        self.assertIn("rpc timeout", stats.message)
        self.assertIsNone(self.store.get_backfill(FRESH_CURSOR_ID))


class FreshScanCyclePriority(unittest.TestCase):
    def test_fresh_deploys_are_scanned_before_lists_and_randoms(self):
        settings = Settings(
            dry_run=True,
            etherscan_api_keys=["test-key"],
            min_funds_usd=2000.0,
            work_dir=Path("/tmp/eth-scanner-fresh-cycle"),
        )
        store = MemoryStore()
        store.upsert_target(Target(
            address=ADDR_FUNDED,
            status="pending",
            discovery_source=FRESH_SOURCE,
            funds_usd=400.0,
            deployed_block=99,
        ))
        lists = {
            "list-1": [MasterCandidate(
                address="0x" + "01" * 20,
                protocol="P1", slug="p1", category="vault",
                est_usd_held=5000, candidate_reason="odd", tier=2, rank=1,
            )],
            "list-2": [MasterCandidate(
                address="0x" + "02" * 20,
                protocol="P2", slug="p2", category="vault",
                est_usd_held=80, candidate_reason="odd", tier=2, rank=2,
            )],
        }

        def named(list_id: str) -> NamedList:
            cfg = get_list_config(list_id)
            return NamedList(config=cfg, candidates=lists[list_id], source="test", total_usd=0)

        events: list[tuple] = []

        def scan(addr: str) -> FunnelResult:
            events.append(("scan", addr, settings.range_min_usd, settings.range_max_usd))
            return FunnelResult(
                bucket="lane-a-cool",
                dropped=False,
                drop_reason=None,
                heat=0,
                src_confidence="high",
                ir_confidence="med",
                funds_usd=400.0,
                funds_status="ok",
                contract_name="Fresh",
            )

        def pick(_skip):
            events.append(("pick",))
            return None

        with mock.patch("eth_scanner.feed.runner.load_named_list", side_effect=named), \
             mock.patch("eth_scanner.feed.runner._blend_note", return_value="blend gauntlet: skipped"):
            progress = run_scan_cycle(
                settings=settings,
                store=store,
                workers=1,
                deadline_monotonic=time.monotonic() + 30,
                scan_one=scan,
                pick_random=pick,
                random_enabled=True,
            )
        scanned = [item[1] for item in events if item[0] == "scan"]
        self.assertEqual(scanned[0], ADDR_FUNDED)
        self.assertEqual(scanned[1], "0x" + "01" * 20)
        self.assertEqual(progress.fresh_scanned, 1)
        self.assertEqual(store.get_target(ADDR_FUNDED)["status"], "done")
        self.assertEqual(store.get_target(ADDR_FUNDED)["discovery_source"], FRESH_SOURCE)
        # Fresh-deploy intake uses the $100 discovery floor, not List 1's band.
        self.assertEqual(events[0][2:], (100.0, None))
        run = next(row for row in store.test_runs if row["address"] == ADDR_FUNDED)
        self.assertEqual(run["discovery_source"], FRESH_SOURCE)


if __name__ == "__main__":
    unittest.main()
