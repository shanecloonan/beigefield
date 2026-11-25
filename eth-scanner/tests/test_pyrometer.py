"""Pyrometer keeps intervals and drops the underlined source."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.deep.runners import EngineRunResult
from eth_scanner.engines.pyrometer_runner import as_static_findings, parse_pyrometer, run_pyrometer
from eth_scanner.heat import evidence_heat
from eth_scanner.logic.static_norm import score_static
from eth_scanner.logic.static_run import run_static_command

REPORT = """
function withdraw(uint256 assets) external {
    uint256 shares = assets / 1e18;
    shares ∈ [ 0, 1000 ]
    uint256 grown = assets * 2;
    grown ∈ [ 0, 115792089237316195423570985008687907853269984665640564039457584007913129639935 ]
}


function quote() external view {
    uint256 price ∈ [ low, high ]
}
"""


class PyrometerParse(unittest.TestCase):
    def test_funds_ranges_score_and_source_is_dropped(self):
        rows = parse_pyrometer(REPORT)
        self.assertEqual([row["kind"] for row in rows], ["precision-loss", "overflow-bound", "rounding-bound"])
        self.assertEqual(rows[0]["weight"], 3)
        self.assertEqual(rows[1]["weight"], 3)
        self.assertEqual(rows[2]["weight"], 0)
        blob = json.dumps(rows)
        self.assertNotIn("assets /", blob)
        self.assertNotIn("function withdraw", blob)
        scored = score_static(as_static_findings({"ranges": rows}))
        self.assertEqual(scored["points"], 6)

    def test_a_missing_binary_skips(self):
        report = run_pyrometer("contract X {}", which=lambda name: None)
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["ranges"], [])
        self.assertEqual(report["heat_contribution"], 0)

    def test_a_crash_keeps_no_ranges(self):
        def boom(source):
            raise RuntimeError("pyrometer broke")

        report = run_pyrometer("contract X {}", runner=boom)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["ranges"], [])

    def test_static_command_scores_a_high_confidence_range(self):
        def engines(_source: str, _timeout: int):
            return [EngineRunResult(
                "pyrometer",
                "ok",
                findings=as_static_findings(run_pyrometer("contract X {}", runner=lambda source: REPORT)),
            )]

        report = run_static_command(source="contract T {}", engines_fn=engines)
        self.assertEqual(report["heat"], 6)
        self.assertTrue(report["heat_breakdown"]["pyrometer"])
        rules = {row["rule"] for row in report["findings"]}
        self.assertIn("precision-loss", rules)
        self.assertNotIn("rounding-bound", rules)

    def test_tag_needs_a_finished_run(self):
        heat, breakdown = evidence_heat(
            funds_usd=None,
            invariant_results=[],
            pyrometer={"ran": True},
        )
        self.assertEqual(heat, 0)
        self.assertTrue(breakdown["pyrometer"])
