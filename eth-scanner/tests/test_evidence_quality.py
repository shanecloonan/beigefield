"""Evidence heat counts a fact once, and a failed code read is not an EOA."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.admin_checks import _classify_controller, _looks_custom_proxy, _wallet_kind
from eth_scanner.engines.corroborate import confirm_privileged_call, read_code, selector_in_bytecode
from eth_scanner.engines.rescore import adjust_heat
from eth_scanner.heat import evidence_heat
from eth_scanner.research.keccak import selector4

ADDR = "0x" + "11" * 20
OWNER = "0x" + "22" * 20
UPGRADE = selector4("upgradeTo(address)")[2:]


def _push4(selector: str) -> str:
    return "63" + selector.lower().removeprefix("0x")


class CodeRead(unittest.TestCase):
    def test_an_rpc_error_is_unknown_not_an_eoa(self):
        with mock.patch(
            "eth_scanner.engines.corroborate._rpc",
            side_effect=RuntimeError("429 rate limited"),
        ):
            read = read_code("http://127.0.0.1:8545", OWNER)
            kind, details = _classify_controller("http://127.0.0.1:8545", OWNER, deadline=10**12)
        self.assertEqual(read["status"], "unknown")
        self.assertIsNone(read["size"])
        self.assertEqual(kind, "unknown")
        self.assertNotEqual(kind, "eoa")
        self.assertEqual(details["code_status"], "unknown")

    def test_empty_code_is_an_eoa_only_after_success(self):
        with mock.patch("eth_scanner.engines.corroborate._rpc", return_value="0x"):
            kind, details = _classify_controller("http://127.0.0.1:8545", OWNER, deadline=10**12)
        self.assertEqual(kind, "eoa")
        self.assertEqual(details["code_status"], "ok")


class PrivilegedProbe(unittest.TestCase):
    def test_a_fallback_that_accepts_garbage_is_ignored(self):
        def rpc(_url, method, params, timeout_s=10):
            if method == "debug_traceCall":
                raise RuntimeError("method not found")
            return "0x"

        code = "0x60806040"
        self.assertFalse(selector_in_bytecode(code, UPGRADE))
        with mock.patch("eth_scanner.engines.corroborate._rpc", side_effect=rpc):
            missing = confirm_privileged_call(
                "http://127.0.0.1:8545", ADDR, UPGRADE, code_hex=code, signature="upgradeTo(address)",
            )
            present = confirm_privileged_call(
                "http://127.0.0.1:8545", ADDR, UPGRADE,
                code_hex="0x" + _push4(UPGRADE),
                signature="upgradeTo(address)",
            )
        self.assertFalse(missing["confirmed"])
        self.assertEqual(missing["reason"], "selector not in dispatch")
        self.assertFalse(present["confirmed"])
        self.assertEqual(present["reason"], "fallback swallows calls")

    def test_a_dispatched_selector_with_a_reverting_control_can_confirm(self):
        def rpc(_url, method, params, timeout_s=10):
            if method == "debug_traceCall":
                return {"pre": {}, "post": {ADDR: {"storage": {"0x1": "0x2"}}}}
            data = params[0]["data"]
            if data.startswith("0x" + UPGRADE):
                return "0x"
            raise RuntimeError("execution reverted")

        with mock.patch("eth_scanner.engines.corroborate._rpc", side_effect=rpc):
            verdict = confirm_privileged_call(
                "http://127.0.0.1:8545", ADDR, UPGRADE,
                code_hex="0x" + _push4(UPGRADE),
                signature="upgradeTo(address)",
                data_suffix="00" * 32,
            )
        self.assertTrue(verdict["confirmed"])
        self.assertTrue(verdict["state_effect"])


class Owners(unittest.TestCase):
    def test_required_getowners_and_isconfirmed_are_a_multisig(self):
        code = "0x" + _push4(selector4("getOwners()")) + _push4(selector4("required()")) + _push4(selector4("isConfirmed(uint256)"))
        self.assertEqual(_wallet_kind(code), "multisig")

    def test_a_custom_proxy_pattern_is_named(self):
        code = "0x363d3d373d3d3d363d73" + "11" * 20
        self.assertTrue(_looks_custom_proxy(code))


class HeatOnce(unittest.TestCase):
    def test_eoa_and_privileged_are_not_counted_again_as_confirmed(self):
        heat, bd = evidence_heat(
            funds_usd=200_000,
            invariant_results=[],
            privileged_callable=True,
            eoa_admin=True,
            corroborated=[
                {"lead_id": "admin-eoa-confirmed", "confirmed": True, "method": "storage", "fact": "eoa-admin"},
                {"lead_id": "admin-privileged-open", "confirmed": True, "method": "eth_call", "fact": "privileged-callable"},
            ],
        )
        self.assertEqual(bd["eoa_admin"], 3)
        self.assertEqual(bd["privileged_callable"], 4)
        self.assertEqual(bd["corroborated_leads"], 0)
        self.assertEqual(heat, 7)

    def test_a_passing_halmos_access_check_removes_the_weaker_probe(self):
        heat, bd = evidence_heat(
            funds_usd=200_000,
            invariant_results=[{
                "id": "symbolic-access_control_non_owner",
                "name": "access_control_non_owner",
                "status": "held",
                "source": "symbolic",
            }],
            privileged_callable=True,
            corroborated=[
                {"lead_id": "admin-privileged-open", "confirmed": True, "method": "eth_call", "fact": "privileged-callable"},
            ],
        )
        self.assertEqual(bd["privileged_callable"], 0)
        self.assertEqual(bd["privileged_confidence"], 0)
        self.assertIn("privileged-callable", bd["contradictions"])
        self.assertEqual(heat, 0)

    def test_a_real_live_failure_still_adds_heat(self):
        heat, bd = evidence_heat(
            funds_usd=50_000,
            invariant_results=[{"id": "solvency", "status": "failed", "evidence": "assets < claim"}],
        )
        self.assertEqual(bd["invariants_failed"], 3)
        self.assertEqual(heat, 3)

    def test_rescore_drops_contradicted_points_and_never_raises(self):
        adjusted = adjust_heat(
            heat=12,
            breakdown={
                "invariants_failed": 0,
                "privileged_callable": 4,
                "eoa_admin": 3,
                "corroborated_leads": 6,
                "admin": {"confirmed": [
                    {"id": "admin-eoa-confirmed", "method": "storage"},
                    {"id": "admin-privileged-open", "method": "eth_call"},
                ]},
            },
            eoa_stands=False,
            privileged_stands=False,
        )
        self.assertEqual(adjusted["heat"], 0)
        self.assertTrue(adjusted["changed"])
        kept = adjust_heat(heat=3, breakdown={"invariants_failed": 3}, eoa_stands=None, privileged_stands=None)
        self.assertEqual(kept["heat"], 3)


if __name__ == "__main__":
    unittest.main()
