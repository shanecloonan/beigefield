"""Stage fusion keeps confirmed evidence when another stage is empty or pending."""

from __future__ import annotations

import unittest

from eth_scanner.heat import evidence_heat
from eth_scanner.receipt import ReceiptContext, render_markdown
from eth_scanner.stages.fusion import annotate_stages, complete_stage, fuse


class StageFusionTests(unittest.TestCase):
    def test_empty_and_pending_stages_do_not_dilute(self) -> None:
        stages = [
            {
                "id": "quick",
                "status": "done",
                "confidence": 1.0,
                "facts": [{"fact": "privileged-callable", "heat": 4, "confidence": 0.45}],
            },
            {"id": "similarity", "status": "done", "confidence": 0.4, "facts": []},
            {
                "id": "halmos",
                "status": "pending",
                "confidence": 0.95,
                "facts": [{"fact": "privileged-callable", "heat": 0, "direction": "hold"}],
            },
        ]
        report = fuse(stages)
        self.assertEqual(report["heat"], 4)
        self.assertEqual(report["score_state"], "provisional")
        self.assertIn("halmos", report["pending_stages"])

    def test_stronger_hold_removes_only_the_weaker_fact(self) -> None:
        stages = [
            {
                "id": "quick",
                "status": "done",
                "confidence": 1.0,
                "facts": [
                    {"fact": "privileged-callable", "heat": 4, "confidence": 0.45},
                    {"fact": "invariant-failed", "heat": 3, "confidence": 1.0},
                ],
            },
            {
                "id": "halmos",
                "status": "done",
                "confidence": 0.95,
                "facts": [{"fact": "privileged-callable", "direction": "hold", "confidence": 0.95}],
            },
        ]
        report = fuse(stages)
        self.assertEqual(report["facts"]["privileged-callable"], 0)
        self.assertEqual(report["facts"]["invariant-failed"], 3)
        self.assertEqual(report["heat"], 3)
        self.assertEqual(report["score_state"], "final")

    def test_the_same_fact_is_counted_once(self) -> None:
        report = fuse([{
            "id": "quick",
            "status": "done",
            "confidence": 1.0,
            "facts": [
                {"fact": "eoa-admin", "heat": 3, "confidence": 0.8},
                {"fact": "eoa-admin", "heat": 3, "confidence": 0.5},
            ],
        }])
        self.assertEqual(report["heat"], 3)

    def test_a_finished_empty_stage_leaves_the_provisional_heat(self) -> None:
        start = annotate_stages({"privileged_callable": 4, "total": 4}, heat=4)
        self.assertEqual(start["fused_heat"], 4)
        self.assertEqual(start["evidence_heat"], 4)
        self.assertEqual(start["score_state"], "provisional")
        done = complete_stage(start, "similarity", facts=[], confidence=0.4)
        self.assertEqual(done["fused_heat"], 4)
        self.assertNotIn("similarity", done["pending_stages"])

    def test_annotation_matches_evidence_heat_and_the_receipt_names_it(self) -> None:
        total, breakdown = evidence_heat(
            funds_usd=1_000_000,
            invariant_results=[{"id": "solvency", "status": "failed", "source": "live"}],
            privileged_callable=True,
        )
        annotated = annotate_stages(breakdown, heat=total)
        self.assertEqual(annotated["fused_heat"], total)
        self.assertEqual(annotated["evidence_heat"], total)
        text = render_markdown(ReceiptContext(
            address="0x" + "11" * 20,
            lane="A",
            result={"heat": total, "heat_breakdown": annotated, "bucket": "lane-b-queue"},
        ))
        self.assertIn("provisional", text)
        self.assertIn("similarity", text)


if __name__ == "__main__":
    unittest.main()
