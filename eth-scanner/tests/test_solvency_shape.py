"""Solvency heat is a token shortfall, not a price or custodian shape."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from eth_scanner.engines.rescore import rescore_rows
from eth_scanner.invariants.live import classify_solvency, clean_constant_ratio

FCS_ASSETS = 2457353511816640532228087
FCS_CONVERTED = 7372060535449921596680595
KRWT_ASSETS = 90102080832
KRWT_CONVERTED = 581710522024
VAULT = "0xdb861830d9ae2d1fcf99fa0cfd3973de382b0b5b"
REASON = "solvency shape only; no simulated profit path (erc4626-solvency)"


class Store:
    def __init__(self, rows):
        self.rows = rows

    def _req(self, method, table, body=None, query=None, prefer=None):
        query = query or {}
        if method == "PATCH":
            wanted = str(query.get("id") or "").split("eq.", 1)[-1]
            for row in self.rows:
                if str(row.get("id")) == wanted:
                    row.update(body or {})
            return []
        address = str(query.get("address") or "")
        if address.startswith("ilike."):
            target = address.split(".", 1)[1].lower()
            return [row for row in self.rows if str(row.get("address") or "").lower() == target]
        column = "blend_heat" if str(query.get("blend_heat") or "").startswith("gte") else "heat"
        if str(query.get(column) or "").startswith("gte"):
            return [row for row in self.rows if int(row.get(column) or 0) >= 3]
        return list(self.rows)


class SolvencyShapeTests(unittest.TestCase):
    def test_frankencoin_ratio_is_a_clean_three(self) -> None:
        gap = abs(FCS_CONVERTED - FCS_ASSETS * 3)
        self.assertLess(gap, FCS_ASSETS // 10**12)
        self.assertTrue(clean_constant_ratio(FCS_CONVERTED, FCS_ASSETS))
        self.assertFalse(clean_constant_ratio((FCS_ASSETS * 35) // 10, FCS_ASSETS))
        self.assertEqual(classify_solvency(
            converted=FCS_CONVERTED,
            total_assets=FCS_ASSETS,
            balance=0,
            preview_state="ok",
        ), "unknown")

    def test_custodian_cash_covers_its_own_assets(self) -> None:
        self.assertEqual(classify_solvency(
            converted=KRWT_CONVERTED,
            total_assets=KRWT_ASSETS,
            balance=KRWT_ASSETS,
            preview_state="ok",
        ), "unknown")

    def test_async_redeem_is_unknown(self) -> None:
        self.assertEqual(classify_solvency(
            converted=2559135411508,
            total_assets=4607431255,
            balance=100,
            preview_state="revert",
        ), "unknown")

    def test_a_real_balance_shortfall_still_fails(self) -> None:
        self.assertEqual(classify_solvency(
            converted=1500,
            total_assets=1000,
            balance=100,
            preview_state="ok",
        ), "failed")

    def test_strategy_cash_below_nav_still_holds(self) -> None:
        self.assertEqual(classify_solvency(
            converted=1000,
            total_assets=1000,
            balance=10,
            preview_state="ok",
        ), "held")

    def test_tolerance_is_inclusive(self) -> None:
        assets = 20_000
        tol = max(1, assets // 200)
        self.assertEqual(classify_solvency(
            converted=assets + tol,
            total_assets=assets,
            balance=0,
            preview_state="ok",
        ), "held")
        self.assertEqual(classify_solvency(
            converted=assets + tol + 1,
            total_assets=assets,
            balance=0,
            preview_state="ok",
        ), "failed")

    def test_a_missing_balance_read_does_not_fail(self) -> None:
        self.assertEqual(classify_solvency(
            converted=1500,
            total_assets=1000,
            balance=None,
            preview_state="ok",
        ), "unread")

    def test_rescore_drops_a_shape_that_does_not_stand(self) -> None:
        rows = [{
            "id": "fcs",
            "address": VAULT,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {"invariants_failed": 3, "drain_reason": REASON},
        }]
        store = Store(rows)
        with patch("eth_scanner.invariants.live.solvency_failure_stands", return_value=False):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(rows[0]["heat"], 0)
        self.assertEqual(rows[0]["heat_breakdown"]["invariants_failed"], 0)

    def test_a_failed_reread_drops_the_retired_accounting_stamp(self) -> None:
        rows = [{
            "id": "fcs",
            "address": VAULT,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {"invariants_failed": 3, "drain_reason": REASON},
        }]
        store = Store(rows)
        with patch("eth_scanner.invariants.live.solvency_failure_stands", return_value=None):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(rows[0]["heat"], 0)

    def test_a_failed_reread_keeps_a_recorded_shortfall(self) -> None:
        rows = [{
            "id": "fcs",
            "address": VAULT,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {
                "invariants_failed": 3,
                "drain_reason": "solvency shape only; no simulated profit path (erc4626-asset-shortfall)",
            },
        }]
        store = Store(rows)
        with patch("eth_scanner.invariants.live.solvency_failure_stands", return_value=None):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(rows[0]["heat"], 3)


if __name__ == "__main__":
    unittest.main()
