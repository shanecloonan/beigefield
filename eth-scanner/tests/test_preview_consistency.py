"""previewRedeem fails only when it pays more than the shares are worth."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from eth_scanner.engines.rescore import rescore_rows
from eth_scanner.invariants.live import preview_overpays, preview_probe_shares

VAULT = "0xd9a442856c234a39a81a089c06451ebaa4306a72"
REASON = "solvency shape only; no simulated profit path (erc4626-preview-consistency)"


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


class PreviewRuleTests(unittest.TestCase):
    def test_a_lower_preview_is_a_fee(self) -> None:
        converted = 5_687_973_300
        tol = max(1, converted // 200)
        # One wei past the old two-sided tolerance. A fee, not an overpay.
        self.assertFalse(preview_overpays(converted - tol - 1, converted))
        self.assertFalse(preview_overpays(converted, converted))

    def test_tolerance_is_inclusive(self) -> None:
        converted = 20_000
        tol = max(1, converted // 200)
        self.assertFalse(preview_overpays(converted + tol, converted))
        self.assertTrue(preview_overpays(converted + tol + 1, converted))

    def test_probe_is_about_one_percent_of_supply(self) -> None:
        self.assertEqual(preview_probe_shares(10**24), 10**22)
        self.assertEqual(preview_probe_shares(50), 1)
        self.assertEqual(preview_probe_shares(0), 0)

    def test_rescore_drops_a_preview_that_does_not_overpay(self) -> None:
        rows = [{
            "id": "vault",
            "address": VAULT,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {"invariants_failed": 3, "drain_reason": REASON},
        }, {
            "id": "real",
            "address": "0x" + "ab" * 20,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {"invariants_failed": 3, "drain_reason": "erc4626-share-price"},
        }]
        store = Store(rows)
        with patch("eth_scanner.invariants.live.preview_failure_stands", return_value=False):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(rows[0]["heat"], 0)
        self.assertEqual(rows[0]["heat_breakdown"]["invariants_failed"], 0)
        self.assertEqual(rows[0]["heat_breakdown"]["original_peak"], 3)
        self.assertEqual(rows[1]["heat"], 3)

    def test_a_failed_reread_keeps_the_preview_heat(self) -> None:
        rows = [{
            "id": "vault",
            "address": VAULT,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {"invariants_failed": 3, "drain_reason": REASON},
        }]
        store = Store(rows)
        with patch("eth_scanner.invariants.live.preview_failure_stands", return_value=None):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(rows[0]["heat"], 3)

    def test_a_real_overpay_keeps_its_heat(self) -> None:
        rows = [{
            "id": "vault",
            "address": VAULT,
            "chain": "ethereum",
            "heat": 3,
            "blend_heat": 3,
            "heat_breakdown": {"invariants_failed": 3, "drain_reason": REASON},
        }]
        store = Store(rows)
        with patch("eth_scanner.invariants.live.preview_failure_stands", return_value=True):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(rows[0]["heat"], 3)


if __name__ == "__main__":
    unittest.main()
