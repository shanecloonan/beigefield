"""SMTChecker is shortlist-only. Counterexample hex is not stored."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.engines.smt_checker import parse_smt, run_smt, smt_points, standard_input
from eth_scanner.heat import evidence_heat

RAW = json.dumps({
    "errors": [
        {
            "component": "SMTChecker",
            "message": "CHC: Overflow happens here.\nCounterexample:\nassets = 0xabcdef0123456789",
            "secondarySourceLocations": [{"function": "withdraw"}],
        },
        {
            "component": "SMTChecker",
            "message": "CHC: Division by zero happens here.",
            "secondarySourceLocations": [{"function": "quote"}],
        },
        {
            "component": "SMTChecker",
            "message": "CHC: Assertion violation might happen here.",
            "secondarySourceLocations": [{"function": "poke"}],
        },
    ]
})


class SmtParse(unittest.TestCase):
    def test_proved_violations_drop_the_counterexample(self):
        rows = parse_smt(RAW)
        self.assertEqual(
            [(row["kind"], row["function"], row["weight"]) for row in rows],
            [("overflow", "withdraw", 3), ("div-by-zero", "quote", 1)],
        )
        self.assertEqual(smt_points(rows), 3)
        blob = json.dumps(rows)
        self.assertNotIn("0xabcdef", blob)
        self.assertNotIn("Counterexample", blob)
        self.assertEqual(parse_smt("not json"), [])

    def test_the_query_is_time_boxed_and_names_the_targets(self):
        payload = standard_input("contract T {}", engine="bmc", timeout_ms=10000)
        checker = payload["settings"]["modelChecker"]
        self.assertEqual(checker["engine"], "bmc")
        self.assertEqual(checker["timeout"], 10000)
        self.assertEqual(checker["targets"], ["underflow", "overflow", "divByZero", "assert"])
        self.assertFalse(checker["showUnproved"])

    def test_off_shortlist_does_not_run(self):
        calls = []

        def runner(argv, payload, timeout):
            calls.append(argv)
            return 0, RAW

        report = run_smt("contract T {}", on_shortlist=False, runner=runner)
        self.assertEqual(calls, [])
        self.assertFalse(report["ran"])
        self.assertEqual(report["heat_contribution"], 0)

    def test_a_missing_binary_skips(self):
        report = run_smt("contract T {}", on_shortlist=True, which=lambda name: None)
        self.assertEqual(report["status"], "skipped")
        self.assertFalse(report["ran"])

    def test_a_value_moving_violation_weighs_three(self):
        def runner(argv, payload, timeout):
            body = json.loads(payload)
            self.assertEqual(body["settings"]["modelChecker"]["engine"], "chc")
            self.assertEqual(body["settings"]["modelChecker"]["timeout"], 10000)
            self.assertLessEqual(timeout, 25)
            return 0, RAW

        report = run_smt("contract T {}", on_shortlist=True, timeout_s=10, runner=runner)
        self.assertTrue(report["ran"])
        self.assertEqual(report["points"], 3)
        heat, breakdown = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            smt={"ran": True, "points": report["points"]},
        )
        self.assertEqual(heat, 3)
        self.assertEqual(breakdown["smt_evidence"], 3)

    def test_a_non_value_violation_weighs_one(self):
        raw = json.dumps({
            "errors": [{
                "component": "SMTChecker",
                "message": "BMC: Assertion violation happens here.",
                "secondarySourceLocations": [{"function": "poke"}],
            }]
        })
        report = run_smt("contract T {}", on_shortlist=True, engine="bmc", runner=lambda argv, payload, timeout: (0, raw))
        self.assertEqual(report["points"], 1)
        heat, breakdown = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            smt={"ran": True, "points": 1},
        )
        self.assertEqual(heat, 1)
        self.assertEqual(breakdown["smt_evidence"], 1)
