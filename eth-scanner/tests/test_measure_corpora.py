"""Tests for the corpus-recall measurement helper (no Slither run)."""
from __future__ import annotations

import argparse
import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def _load_measure():
    path = Path(__file__).resolve().parents[1] / "tools" / "measure_corpora.py"
    spec = importlib.util.spec_from_file_location("measure_corpora", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load measure_corpora.py")
    mod = importlib.util.module_from_spec(spec)
    # Importing the tool is heavy (scanner + optional solc-select). The
    # threshold helpers do not need the rest, but they live in that module.
    spec.loader.exec_module(mod)
    return mod


# Load once for the process; skip the module if the scanner import fails.
try:
    MEASURE = _load_measure()
    LOAD_ERROR = None
except Exception as exc:  # pragma: no cover - environment-specific
    MEASURE = None
    LOAD_ERROR = exc


@unittest.skipIf(MEASURE is None, f"measure_corpora import failed: {LOAD_ERROR}")
class CorpusThresholdTests(unittest.TestCase):
    def _args(self, floor: int) -> argparse.Namespace:
        return argparse.Namespace(min_smartbugs=floor)

    def _summary(self, caught: int, n: int = 143) -> dict:
        return {
            "corpora": {
                "smartbugs-curated": {
                    "n": n,
                    "ungated_caught": caught,
                    "ungated_recall": (caught / n) if n else None,
                    "compile_failed": 0,
                    "engines_would_run_if_funded": 139,
                }
            }
        }

    def test_disabled_floor_always_passes(self):
        code = MEASURE._threshold_exit(self._summary(0), self._args(0))
        self.assertEqual(code, 0)

    def test_missing_smartbugs_is_ok(self):
        code = MEASURE._threshold_exit({"corpora": {}}, self._args(90))
        self.assertEqual(code, 0)

    def test_pass_at_or_above_floor(self):
        self.assertEqual(MEASURE._threshold_exit(self._summary(90), self._args(90)), 0)
        self.assertEqual(MEASURE._threshold_exit(self._summary(102), self._args(90)), 0)

    def test_fail_below_floor(self):
        self.assertEqual(MEASURE._threshold_exit(self._summary(89), self._args(90)), 1)

    def test_new_shape_detectors_map_to_dasp_categories(self):
        pairs = {
            "custom:pre08-arithmetic": "arithmetic",
            "weak-entropy": "bad_randomness",
            "slither:unchecked-low-level": "unchecked_low_level_calls",
            "unchecked-delegatecall": "access_control",
            "custom:hash-preimage-payout": "front_running",
            "unbounded-storage-loop": "denial_of_service",
            "arbitrary-send-erc20-permit": "access_control",
        }
        for detector, category in pairs.items():
            self.assertEqual(MEASURE.dasp_of_finding(detector=detector), category, detector)

    def test_recall_floor_stays_at_least_90(self):
        self.assertGreaterEqual(MEASURE.DEFAULT_MIN_SMARTBUGS, 90)

    def test_print_table_includes_counts(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            MEASURE._print_table(self._summary(102))
        text = buf.getvalue()
        self.assertIn("smartbugs-curated", text)
        self.assertIn("102", text)
        self.assertIn("143", text)
        self.assertIn("71.3%", text)


if __name__ == "__main__":
    unittest.main()
