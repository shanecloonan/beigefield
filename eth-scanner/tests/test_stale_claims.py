"""Stale running claims are released back to pending, then skipped after a cap."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import (
    DEFAULT_STALE_CLAIM_HOURS,
    DEFAULT_STALE_CLAIM_MAX_RESETS,
    DEFAULT_STALE_CLAIM_SECONDS,
    load_settings,
    stale_claim_hours,
    stale_claim_max_resets,
    stale_claim_seconds,
)
from eth_scanner.store.supabase import (
    STALE_CLAIM_RESETS_KEY,
    STALE_CLAIM_SKIP_REASON,
    MemoryStore,
    _parse_ts,
    plan_stale_claim_release,
)
from eth_scanner.types import Target


NOW = datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)
ADDR_A = "0x1111111111111111111111111111111111111111"
ADDR_B = "0x2222222222222222222222222222222222222222"
ADDR_C = "0x3333333333333333333333333333333333333333"
ADDR_D = "0x4444444444444444444444444444444444444444"


def _running(
    store: MemoryStore,
    address: str,
    *,
    claimed_at=None,
    updated_at=None,
    claimed_by="eth-scanner",
    resets=0,
) -> dict:
    store.upsert_target(Target(address=address, status="pending", has_code=True))
    row = store.targets[address]
    row["status"] = "running"
    row["claimed_by"] = claimed_by
    row["claimed_at"] = claimed_at
    if updated_at is not None:
        row["updated_at"] = updated_at
    if resets:
        hb = dict(row.get("heat_breakdown") or {})
        hb[STALE_CLAIM_RESETS_KEY] = resets
        row["heat_breakdown"] = hb
    return row


class ParseTimestamp(unittest.TestCase):
    def test_postgres_offset_and_iso(self):
        a = _parse_ts("2026-11-13 04:29:32.112827+00")
        b = _parse_ts("2026-11-13T04:29:32.112827+00:00")
        c = _parse_ts("2026-11-13T04:29:32.112827Z")
        self.assertIsNotNone(a)
        self.assertEqual(a, b)
        self.assertEqual(a, c)


class ConfigKnobs(unittest.TestCase):
    def test_defaults(self):
        env = {}
        with mock.patch.dict("os.environ", env, clear=False):
            # Drop only the knobs under test, leave the rest of the process env.
            for key in (
                "ETH_SCANNER_STALE_CLAIM_HOURS",
                "ETH_SCAN_STALE_CLAIM_HOURS",
                "ETH_SCANNER_STALE_CLAIM_MAX_RESETS",
                "ETH_SCAN_STALE_CLAIM_MAX_RESETS",
            ):
                if key in __import__("os").environ:
                    pass
        with mock.patch.dict(
            "os.environ",
            {
                "ETH_SCANNER_STALE_CLAIM_HOURS": "",
                "ETH_SCAN_STALE_CLAIM_HOURS": "",
            },
            clear=False,
        ):
            # empty string should fall back to default via _env_float
            self.assertEqual(DEFAULT_STALE_CLAIM_HOURS, 3.0)
            self.assertEqual(DEFAULT_STALE_CLAIM_SECONDS, 3 * 3600)
            self.assertEqual(DEFAULT_STALE_CLAIM_MAX_RESETS, 2)

    def test_env_hours_primary(self):
        with mock.patch.dict("os.environ", {"ETH_SCANNER_STALE_CLAIM_HOURS": "6"}, clear=False):
            self.assertEqual(stale_claim_hours(), 6.0)
            self.assertEqual(stale_claim_seconds(), 6 * 3600)
            settings = load_settings()
            self.assertEqual(settings.claim_stale_seconds, 6 * 3600)

    def test_alias_when_primary_absent(self):
        env = {
            key: value
            for key, value in __import__("os").environ.items()
            if key not in {
                "ETH_SCANNER_STALE_CLAIM_HOURS",
                "ETH_SCAN_STALE_CLAIM_HOURS",
            }
        }
        env["ETH_SCAN_STALE_CLAIM_HOURS"] = "1.5"
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(stale_claim_hours(), 1.5)
            self.assertEqual(stale_claim_seconds(), 5400)

    def test_max_resets_env(self):
        with mock.patch.dict("os.environ", {"ETH_SCANNER_STALE_CLAIM_MAX_RESETS": "4"}, clear=False):
            self.assertEqual(stale_claim_max_resets(), 4)
            self.assertEqual(load_settings().stale_claim_max_resets, 4)


class ReleasePlan(unittest.TestCase):
    def test_fresh_running_is_left_alone(self):
        row = {
            "address": ADDR_A,
            "status": "running",
            "claimed_by": "eth-scanner",
            "claimed_at": (NOW - timedelta(minutes=10)).isoformat(),
            "updated_at": NOW.isoformat(),
        }
        self.assertIsNone(plan_stale_claim_release(
            row, now=NOW, stale_seconds=3 * 3600, max_resets=2,
        ))

    def test_recent_updated_at_fallback_is_left_alone(self):
        # Live scan with no claimed_at (the MaplePool shape).
        row = {
            "address": ADDR_A,
            "status": "running",
            "claimed_by": None,
            "claimed_at": None,
            "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        }
        self.assertIsNone(plan_stale_claim_release(
            row, now=NOW, stale_seconds=3 * 3600, max_resets=2,
        ))

    def test_stale_claimed_at_releases_to_pending(self):
        row = {
            "address": ADDR_A,
            "status": "running",
            "claimed_by": "eth-scanner",
            "claimed_at": (NOW - timedelta(hours=4)).isoformat(),
            "updated_at": (NOW - timedelta(hours=4)).isoformat(),
            "heat_breakdown": {},
        }
        plan = plan_stale_claim_release(row, now=NOW, stale_seconds=3 * 3600, max_resets=2)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "released")
        self.assertEqual(plan["resets"], 1)
        self.assertEqual(plan["patch"]["status"], "pending")
        self.assertIsNone(plan["patch"]["claimed_by"])
        self.assertIsNone(plan["patch"]["claimed_at"])
        self.assertEqual(plan["patch"]["heat_breakdown"][STALE_CLAIM_RESETS_KEY], 1)

    def test_null_claimed_at_uses_updated_at(self):
        row = {
            "address": ADDR_A,
            "status": "running",
            "claimed_by": None,
            "claimed_at": None,
            "updated_at": "2026-11-13 06:24:00.20656+00",
            "heat_breakdown": {},
        }
        plan = plan_stale_claim_release(row, now=NOW, stale_seconds=3 * 3600, max_resets=2)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "released")
        self.assertEqual(plan["patch"]["status"], "pending")

    def test_cap_marks_skipped(self):
        row = {
            "address": ADDR_A,
            "status": "running",
            "claimed_by": "eth-scanner",
            "claimed_at": (NOW - timedelta(hours=5)).isoformat(),
            "updated_at": (NOW - timedelta(hours=5)).isoformat(),
            "heat_breakdown": {STALE_CLAIM_RESETS_KEY: 2},
        }
        plan = plan_stale_claim_release(row, now=NOW, stale_seconds=3 * 3600, max_resets=2)
        self.assertEqual(plan["action"], "skipped")
        self.assertEqual(plan["resets"], 3)
        self.assertEqual(plan["patch"]["status"], "skipped")
        self.assertIsNone(plan["patch"]["claimed_by"])
        self.assertIsNone(plan["patch"]["claimed_at"])
        self.assertEqual(plan["patch"]["heat_breakdown"]["skip_reason"], STALE_CLAIM_SKIP_REASON)

    def test_disabled_when_seconds_zero(self):
        row = {
            "address": ADDR_A,
            "status": "running",
            "claimed_at": (NOW - timedelta(days=7)).isoformat(),
        }
        self.assertIsNone(plan_stale_claim_release(
            row, now=NOW, stale_seconds=0, max_resets=2,
        ))


class MemoryStoreSweep(unittest.TestCase):
    def test_sweep_releases_stale_and_spares_fresh(self):
        store = MemoryStore()
        stale_at = (NOW - timedelta(hours=4)).isoformat()
        fresh_at = (NOW - timedelta(minutes=8)).isoformat()
        _running(store, ADDR_A, claimed_at=stale_at, updated_at=stale_at)
        _running(store, ADDR_B, claimed_at=None, updated_at=stale_at, claimed_by=None)
        _running(store, ADDR_C, claimed_at=fresh_at, updated_at=fresh_at)
        _running(store, ADDR_D, claimed_at=None, updated_at=fresh_at, claimed_by=None)

        out = store.release_stale_claims(stale_seconds=3 * 3600, max_resets=2, now=NOW)
        self.assertEqual(sorted(r["address"] for r in out), [ADDR_A, ADDR_B])
        self.assertTrue(all(r["action"] == "released" for r in out))

        self.assertEqual(store.targets[ADDR_A]["status"], "pending")
        self.assertIsNone(store.targets[ADDR_A]["claimed_by"])
        self.assertIsNone(store.targets[ADDR_A]["claimed_at"])
        self.assertEqual(store.targets[ADDR_A]["heat_breakdown"][STALE_CLAIM_RESETS_KEY], 1)

        self.assertEqual(store.targets[ADDR_B]["status"], "pending")
        self.assertEqual(store.targets[ADDR_C]["status"], "running")
        self.assertEqual(store.targets[ADDR_C]["claimed_by"], "eth-scanner")
        self.assertEqual(store.targets[ADDR_D]["status"], "running")

    def test_second_reset_then_skip(self):
        store = MemoryStore()
        stale_at = (NOW - timedelta(hours=5)).isoformat()
        _running(store, ADDR_A, claimed_at=stale_at, updated_at=stale_at)

        first = store.release_stale_claims(stale_seconds=3 * 3600, max_resets=2, now=NOW)
        self.assertEqual(first[0]["action"], "released")
        self.assertEqual(store.targets[ADDR_A]["status"], "pending")

        # It gets stuck again.
        store.targets[ADDR_A]["status"] = "running"
        store.targets[ADDR_A]["claimed_by"] = "eth-scanner"
        store.targets[ADDR_A]["claimed_at"] = stale_at
        second = store.release_stale_claims(stale_seconds=3 * 3600, max_resets=2, now=NOW)
        self.assertEqual(second[0]["action"], "released")
        self.assertEqual(second[0]["resets"], 2)
        self.assertEqual(store.targets[ADDR_A]["status"], "pending")

        store.targets[ADDR_A]["status"] = "running"
        store.targets[ADDR_A]["claimed_by"] = "eth-scanner"
        store.targets[ADDR_A]["claimed_at"] = stale_at
        third = store.release_stale_claims(stale_seconds=3 * 3600, max_resets=2, now=NOW)
        self.assertEqual(third[0]["action"], "skipped")
        self.assertEqual(store.targets[ADDR_A]["status"], "skipped")
        self.assertIsNone(store.targets[ADDR_A]["claimed_by"])
        self.assertIsNone(store.targets[ADDR_A]["claimed_at"])
        self.assertEqual(store.targets[ADDR_A]["heat_breakdown"]["skip_reason"], STALE_CLAIM_SKIP_REASON)

        # A further sweep must not un-skip it.
        fourth = store.release_stale_claims(stale_seconds=3 * 3600, max_resets=2, now=NOW)
        self.assertEqual(fourth, [])
        self.assertEqual(store.targets[ADDR_A]["status"], "skipped")

    def test_claim_pending_releases_stale_then_reclaims(self):
        store = MemoryStore()
        stale_at = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        _running(store, ADDR_A, claimed_at=stale_at, updated_at=stale_at)
        claimed = store.claim_pending(1, "worker-1")
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["address"], ADDR_A)
        self.assertEqual(claimed[0]["status"], "running")
        self.assertEqual(claimed[0]["claimed_by"], "worker-1")
        self.assertEqual(store.targets[ADDR_A]["heat_breakdown"][STALE_CLAIM_RESETS_KEY], 1)


if __name__ == "__main__":
    unittest.main()
