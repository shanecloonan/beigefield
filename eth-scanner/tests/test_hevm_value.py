"""hevm stays an external CLI. A symbolic path adds no heat until a local call measures value."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.heat import evidence_heat
from eth_scanner.logic import hevm_value
from eth_scanner.logic.hevm_value import parse_hevm_reachable, run_hevm_value, trace_deltas
from eth_scanner.research.symbolic import hevm_value_argv

ADDR = "0x1111111111111111111111111111111111111111"
LOCAL = "http://127.0.0.1:8545/secret-token"
CALLER = "0x000000000000000000000000000000000000beef"
TARGET = "0x1111111111111111111111111111111111111111"


class HevmPin(unittest.TestCase):
    def test_pin_is_unlinked_agpl(self):
        self.assertEqual(hevm_value.PIN["license"], "AGPL-3.0")
        self.assertFalse(hevm_value.PIN["link"])
        source = Path(hevm_value.__file__).read_text(encoding="utf-8")
        imports = [
            line.strip() for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        self.assertFalse(any(line.startswith("import hevm") or line.startswith("from hevm") for line in imports))

    def test_public_rpc_is_refused_before_a_command(self):
        with self.assertRaises(ValueError):
            hevm_value_argv(
                "hevm",
                rpc="https://eth.example/v2/SECRET",
                address=ADDR,
                caller=CALLER,
                signature="withdraw()",
                timeout_s=10,
            )
        argv = hevm_value_argv(
            "hevm",
            rpc="http://127.0.0.1:8545",
            address=ADDR,
            caller=CALLER,
            signature="withdraw()",
            timeout_s=10,
        )
        self.assertNotIn("--calldata", argv)
        self.assertNotIn("--get-models", argv)
        self.assertIn("--smt-timeout", argv)


class HevmShortlist(unittest.TestCase):
    def test_off_shortlist_and_public_rpc_do_not_run(self):
        calls = []

        def runner(argv, timeout):
            calls.append(argv)
            return 0, ""

        off = run_hevm_value(address=ADDR, on_shortlist=False, fork_url=LOCAL, runner=runner)
        public = run_hevm_value(
            address=ADDR,
            on_shortlist=True,
            fork_url="https://eth.example/v2/SECRET",
            runner=runner,
        )
        with patch("eth_scanner.deep.runners.hevm_bin", return_value=None):
            missing = run_hevm_value(address=ADDR, on_shortlist=True, fork_url=LOCAL)
        self.assertEqual(calls, [])
        self.assertEqual(off["heat"], 0)
        self.assertFalse(off["ran"])
        self.assertEqual(public["heat"], 0)
        self.assertNotIn("SECRET", json.dumps(public))
        self.assertEqual(missing["status"], "skipped")
        self.assertIn("not installed", missing["note"])

    def test_a_symbolic_hit_without_a_measured_move_adds_no_heat(self):
        def confirmer(url, target, selector, caller):
            return 1, 1

        report = run_hevm_value(
            address=ADDR,
            on_shortlist=True,
            fork_url=LOCAL,
            output="Assertion violation [validated] calldata 0xdeadbeefdeadbeef",
            confirmer=confirmer,
        )
        self.assertEqual(report["status"], "lead")
        self.assertEqual(report["heat"], 0)
        self.assertTrue(report["heat_breakdown"]["hevm"])
        self.assertNotIn("deadbeef", json.dumps(report))
        self.assertNotIn("secret-token", json.dumps(report))

    def test_a_measured_local_move_is_invariant_heat(self):
        def confirmer(url, target, selector, caller):
            self.assertEqual(selector, "3ccfd60b")
            return 10**18, 10**18

        report = run_hevm_value(
            address=ADDR,
            on_shortlist=True,
            fork_url=LOCAL,
            output="Assertion violation [validated]",
            confirmer=confirmer,
        )
        self.assertEqual(report["status"], "confirmed")
        self.assertEqual(report["heat"], 3)
        self.assertEqual(report["selector"], "withdraw()")
        self.assertNotIn("0x", report["note"])

    def test_a_hold_does_not_confirm(self):
        def confirmer(url, target, selector, caller):
            raise AssertionError("confirmer")

        report = run_hevm_value(
            address=ADDR,
            on_shortlist=True,
            fork_url=LOCAL,
            output="QED: no assertion violations",
            confirmer=confirmer,
        )
        self.assertEqual(report["status"], "held")
        self.assertEqual(report["heat"], 0)
        self.assertFalse(parse_hevm_reachable("timed out"))


class HevmTrace(unittest.TestCase):
    def test_value_leaving_the_target_is_measured(self):
        up, down = trace_deltas(
            {
                "from": CALLER,
                "to": TARGET,
                "input": "0x3ccfd60b",
                "calls": [{
                    "from": TARGET,
                    "to": CALLER,
                    "value": hex(10**18),
                }],
            },
            TARGET,
            CALLER,
        )
        self.assertEqual((up, down), (10**18, 10**18))

    def test_a_dust_transfer_stays_under_the_bar(self):
        up, down = trace_deltas(
            {"from": TARGET, "to": CALLER, "value": "0x1"},
            TARGET,
            CALLER,
        )
        self.assertLessEqual(up, hevm_value.DUST)
        self.assertLessEqual(down, hevm_value.DUST)

    def test_symbolic_source_does_not_count_and_a_fork_call_does(self):
        symbolic, _ = evidence_heat(
            funds_usd=None,
            invariant_results=[{
                "id": "non-owner-value",
                "status": "failed",
                "source": "symbolic",
            }],
        )
        live, _ = evidence_heat(
            funds_usd=None,
            invariant_results=[{
                "id": "non-owner-value",
                "status": "failed",
                "source": "fork-simulation",
            }],
        )
        self.assertEqual(symbolic, 0)
        self.assertEqual(live, 3)
