"""Etherscan pacer: just under the per-second cap, stop at the daily cap."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.config import load_settings
from eth_scanner.ingest.etherscan import KeyRotator
from eth_scanner.ingest.quota import (
    DailyBudgetExhausted,
    QuotaLedger,
    interval_for,
    key_id,
    read_limits,
    reset_ledger,
)
from eth_scanner.store.supabase import MemoryStore


class _Clock:
    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


class PaceAndCap(unittest.TestCase):
    def tearDown(self):
        reset_ledger()

    def test_defaults_match_free_tier_and_stay_under_the_cap(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {
                "ETH_SCANNER_ETHERSCAN_PER_SECOND",
                "ETH_SCANNER_ETHERSCAN_PER_DAY",
                "ETH_SCANNER_ETHERSCAN_PACE",
                "ETH_SCANNER_ETHERSCAN_INTERVAL",
                "ETHERSCAN_API_KEYS",
            }
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("eth_scanner.config._load_dotenv"):
                per_second, per_day, pace = read_limits()
                spacing = interval_for(per_second, pace)
                settings = load_settings()
        self.assertEqual(per_second, 5.0)
        self.assertEqual(per_day, 100_000)
        self.assertEqual(pace, 0.95)
        self.assertGreater(spacing, 1.0 / 5.0)
        self.assertLess(1.0 / spacing, 5.0)
        self.assertAlmostEqual(settings.etherscan_min_interval_s, spacing)

    def test_explicit_interval_cannot_outrun_the_cap(self):
        with mock.patch.dict(os.environ, {"ETH_SCANNER_ETHERSCAN_INTERVAL": "0.01"}, clear=False):
            spacing = interval_for(5.0, 0.95)
        self.assertGreater(spacing, 0.2)
        with mock.patch.dict(os.environ, {"ETH_SCANNER_ETHERSCAN_INTERVAL": "0.5"}, clear=False):
            self.assertAlmostEqual(interval_for(5.0, 0.95), 0.5)

    def test_one_key_sleeps_just_under_five_per_second(self):
        clock = _Clock()
        spacing = interval_for(5.0, 0.95)
        rot = KeyRotator(
            keys=["k1"],
            min_interval_s=spacing,
            clock=clock,
            sleeper=clock.sleep,
        )
        stamps = []
        for _ in range(4):
            self.assertEqual(rot.acquire(), "k1")
            stamps.append(clock.t)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertTrue(all(gap + 1e-9 >= spacing for gap in gaps))
        elapsed = stamps[-1] - stamps[0]
        rate = (len(stamps) - 1) / elapsed
        self.assertLess(rate, 5.0)
        self.assertGreater(rate, 4.0)

    def test_keys_share_the_load_and_sum_daily_budgets(self):
        ledger = QuotaLedger(per_day=2, chunk=2)
        rot = KeyRotator(
            keys=["alpha", "beta"],
            min_interval_s=0.0,
            ledger=ledger,
            clock=_Clock(),
            sleeper=lambda _s: None,
        )
        got = [rot.acquire() for _ in range(4)]
        self.assertEqual(got.count("alpha"), 2)
        self.assertEqual(got.count("beta"), 2)
        with self.assertRaises(DailyBudgetExhausted) as raised:
            rot.acquire()
        self.assertIn("resumes", str(raised.exception))
        self.assertEqual(raised.exception.limit, 4)
        self.assertEqual(ledger.snapshot(2)["per_day_total"], 4)
        self.assertEqual(ledger.snapshot(2)["used"], 4)

    def test_reservation_is_spent_on_crash_and_kept_on_clean_close(self):
        secret = "super-secret-key"
        store = MemoryStore()
        ledger = QuotaLedger(per_day=5, chunk=2)
        ledger.store = store
        rot = KeyRotator(
            keys=[secret],
            min_interval_s=0.0,
            ledger=ledger,
            clock=_Clock(),
            sleeper=lambda _s: None,
        )
        rot.acquire()
        raw = json.dumps(store.get_backfill("etherscan-quota"))
        self.assertNotIn(secret, raw)
        crashed = QuotaLedger(per_day=5, chunk=2)
        crashed.store = store
        crashed.load()
        self.assertEqual(crashed.used[key_id(secret)], 2)

        ledger.close()
        clean = QuotaLedger(per_day=5, chunk=2)
        clean.store = store
        clean.load()
        self.assertEqual(clean.used[key_id(secret)], 1)

    def test_utc_day_roll_clears_the_counter(self):
        ledger = QuotaLedger(per_day=1, chunk=1)
        kid = key_id("k")
        ledger.day = "2000-01-01"
        ledger.used[kid] = 1
        ledger.reserved[kid] = 1
        self.assertTrue(ledger.has_budget("k"))
        self.assertEqual(ledger.used.get(kid, 0), 0)


if __name__ == "__main__":
    unittest.main()
