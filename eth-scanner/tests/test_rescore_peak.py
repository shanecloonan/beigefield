"""A contradicted false peak is rewritten on every stored scan. Real invariant heat stays."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from eth_scanner.engines.rescore import rescore_rows

HYDRO = "0x241e82c79452f51fbfc89fac6d912e021db1a3b7"
FALSE = {
    "privileged_callable": 4,
    "eoa_admin": 3,
    "corroborated_leads": 6,
    "invariants_failed": 0,
    "admin": {"confirmed": [
        {"id": "admin-eoa-confirmed"},
        {"id": "admin-privileged-open"},
    ]},
}


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


class RescorePeakTests(unittest.TestCase):
    def test_blend_heat_and_old_scans_lose_a_false_peak(self) -> None:
        rows = [
            {"id": "new", "address": HYDRO, "chain": "ethereum", "heat": 0, "blend_heat": 12, "heat_breakdown": dict(FALSE)},
            {"id": "old", "address": HYDRO.upper(), "chain": "ethereum", "heat": 12, "blend_heat": 12, "heat_breakdown": dict(FALSE)},
            {"id": "real", "address": "0x" + "ab" * 20, "chain": "ethereum", "heat": 9, "blend_heat": 9, "heat_breakdown": {"invariants_failed": 9}},
        ]
        store = Store(rows)
        with patch("eth_scanner.engines.rescore.live_flags", return_value=(False, False)):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(rows[0]["heat"], 0)
        self.assertEqual(rows[0]["blend_heat"], 0)
        self.assertEqual(rows[0]["heat_breakdown"]["original_peak"], 12)
        self.assertEqual(rows[0]["heat_breakdown"]["peak_heat"], 0)
        self.assertEqual(rows[1]["heat"], 0)
        self.assertEqual(rows[2]["heat"], 9)
        self.assertNotIn("rescore", rows[2]["heat_breakdown"])

    def test_receipt_evidence_lowers_a_column_the_board_still_ranks(self) -> None:
        receipt = {"heat_breakdown": dict(FALSE)}
        rows = [
            {
                "id": "latest",
                "address": HYDRO,
                "chain": "ethereum",
                "heat": 0,
                "blend_heat": 0,
                "heat_breakdown": {"rescore": "evidence-read", "eoa_admin": 0, "privileged_callable": 0},
                "blend_receipt": receipt,
            },
            {
                "id": "ghost",
                "address": HYDRO,
                "chain": "eth",
                "heat": 12,
                "blend_heat": 12,
                "heat_breakdown": {},
                "blend_receipt": receipt,
            },
        ]
        store = Store(rows)
        with patch("eth_scanner.engines.rescore.live_flags", return_value=(False, False)):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertGreater(report["updated"], 0)
        self.assertEqual(rows[1]["heat"], 0)
        self.assertEqual(rows[1]["blend_heat"], 0)
        self.assertEqual(rows[1]["heat_breakdown"]["original_peak"], 12)
        self.assertEqual(rows[1]["heat_breakdown"]["peak_heat"], 0)
        self.assertEqual(rows[0]["heat_breakdown"]["peak_heat"], 0)

    def test_unexplained_heat_is_not_wiped(self) -> None:
        rows = [{"id": "bare", "address": HYDRO, "chain": "ethereum", "heat": 12, "blend_heat": 12, "heat_breakdown": {}}]
        store = Store(rows)
        with patch("eth_scanner.engines.rescore.live_flags", return_value=(False, False)):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(rows[0]["heat"], 12)
        self.assertEqual(report["skipped"][0]["reason"], "no-probe-points")

    def test_retired_probe_drops_without_a_live_read(self) -> None:
        retired = dict(FALSE)
        retired["admin"] = {"confirmed": [
            {"id": "admin-eoa-confirmed", "evidence": "controller=0xabc funds_usd=241805"},
            {"id": "admin-privileged-open", "evidence": "upgradeTo(address) on 0xabc — eth_call succeeded (no revert) selector=0x3659cfe6"},
        ]}
        rows = [{"id": "hydro", "address": HYDRO, "chain": "ethereum", "heat": 12, "blend_heat": 12, "heat_breakdown": retired}]
        store = Store(rows)
        with patch("eth_scanner.engines.rescore.live_flags", return_value=(None, None)):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 1)
        self.assertEqual(rows[0]["heat"], 6)
        self.assertEqual(rows[0]["heat_breakdown"]["privileged_callable"], 0)
        self.assertEqual(rows[0]["heat_breakdown"]["eoa_admin"], 3)
        self.assertEqual(rows[0]["heat_breakdown"]["original_peak"], 12)
        self.assertEqual(rows[0]["heat_breakdown"]["peak_heat"], 6)

    def test_current_control_confirmation_survives_a_failed_read(self) -> None:
        current = dict(FALSE)
        current["admin"] = {"confirmed": [
            {"id": "admin-privileged-open", "evidence": "selector dispatched and the control selector reverted"},
        ]}
        rows = [{"id": "kept", "address": HYDRO, "chain": "ethereum", "heat": 4, "blend_heat": 4, "heat_breakdown": current}]
        store = Store(rows)
        with patch("eth_scanner.engines.rescore.live_flags", return_value=(None, None)):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(rows[0]["heat"], 4)

    def test_an_undecided_read_does_not_touch_heat(self) -> None:
        rows = [{"id": "only", "address": HYDRO, "chain": "ethereum", "heat": 12, "blend_heat": 12, "heat_breakdown": dict(FALSE)}]
        store = Store(rows)
        with patch("eth_scanner.engines.rescore.live_flags", return_value=(None, None)):
            report = rescore_rows(store, "http://rpc.example", limit=10)
        self.assertEqual(report["updated"], 0)
        self.assertEqual(rows[0]["heat"], 12)


if __name__ == "__main__":
    unittest.main()
