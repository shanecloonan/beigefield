"""Wake leads keep detector names and drop source snippets."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.runners import EngineRunResult
from eth_scanner.engines.wake_runner import parse_wake, run_wake, run_wake_fuzz, wake_rule
from eth_scanner.logic.static_norm import score_static
from eth_scanner.logic.static_run import run_static_command

RAW = json.dumps({
    "detections": [{
        "detector": "unused-import",
        "impact": "warning",
        "confidence": "high",
        "message": "function steal() public { selfdestruct(payable(msg.sender)); }",
        "source": "contract X { function steal() public {} }",
    }]
})


class WakeRunner(unittest.TestCase):
    def test_json_keeps_the_name_and_drops_the_snippet(self):
        rows = parse_wake(RAW)
        self.assertEqual(rows, [{
            "detector": "unused-import",
            "impact": "warning",
            "confidence": "high",
            "heat_contribution": 0,
        }])
        blob = json.dumps(rows)
        self.assertNotIn("steal", blob)
        self.assertNotIn("selfdestruct", blob)
        self.assertEqual(parse_wake("not json and function steal() {}"), [])

    def test_a_missing_binary_skips(self):
        report = run_wake("contract X {}", which=lambda name: None)
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["detections"], [])
        self.assertEqual(report["heat_contribution"], 0)

    def test_a_crash_keeps_no_detections(self):
        def boom(source):
            raise RuntimeError("wake broke")

        report = run_wake("contract X {}", runner=boom)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["detections"], [])
        self.assertEqual(report["heat_contribution"], 0)

    def test_injected_json_is_evidence_only(self):
        report = run_wake("contract X {}", runner=lambda source: RAW)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["detections"][0]["detector"], "unused-import")
        self.assertTrue(report["evidence_only"])
        self.assertEqual(report["heat_contribution"], 0)


class WakeStatic(unittest.TestCase):
    def test_high_impact_names_join_the_allowlist(self):
        self.assertEqual(wake_rule("reentrancy", "high"), "reentrancy-eth")
        self.assertEqual(wake_rule("reentrancy", "warning"), "reentrancy-no-eth")
        self.assertEqual(wake_rule("unsafe-delegatecall", "high"), "controlled-delegatecall")
        self.assertEqual(wake_rule("unchecked-return-value", "medium"), "unchecked-transfer")
        self.assertEqual(wake_rule("unused-import", "warning"), "unused-import")
        scored = score_static([
            {"engine": "wake", "rule": "reentrancy-eth", "generic": True, "evidence": "impact=high"},
            {"engine": "wake", "rule": "unused-import", "generic": True, "evidence": "style"},
        ])
        self.assertEqual(scored["points"], 3)

    def test_static_command_scores_a_mapped_wake_hit(self):
        def engines(_source: str, _timeout: int):
            return [EngineRunResult(
                "wake",
                "ok",
                findings=[{
                    "engine": "wake",
                    "rule": "unsafe-delegatecall",
                    "generic": True,
                    "evidence": "delegatecall target",
                }],
            )]

        report = run_static_command(source="contract T {}", engines_fn=engines)
        self.assertEqual(report["heat"], 3)
        self.assertTrue(report["heat_breakdown"]["wake"])
        self.assertEqual(report["findings"][0]["rule"], "controlled-delegatecall")


class WakeFuzz(unittest.TestCase):
    def test_off_shortlist_does_not_run(self):
        calls = []

        def runner(argv, timeout):
            calls.append(argv)
            return 0, ""

        report = run_wake_fuzz("/tmp", on_shortlist=False, runner=runner)
        self.assertEqual(calls, [])
        self.assertEqual(report["heat"], 0)
        self.assertFalse(report["ran"])

    def test_a_failure_keeps_no_sequence(self):
        import tempfile
        def runner(argv, timeout):
            return 1, "failed 0x" + "ab" * 8

        with tempfile.TemporaryDirectory() as tmp:
            tests = Path(tmp) / "tests"
            tests.mkdir()
            (tests / "test_hold.py").write_text("def test_hold():\n    assert True\n", encoding="utf-8")
            report = run_wake_fuzz(tmp, on_shortlist=True, runner=runner)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["heat"], 0)
        self.assertNotIn("abab", json.dumps(report))
        self.assertIn("not stored", report["note"])


if __name__ == "__main__":
    unittest.main()
