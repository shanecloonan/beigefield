"""Protocol specs are cached properties. No key still writes a template. Heat stays 0."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from eth_scanner.specs.protocol import code_hash, generate_specs, llm_key

ADDR = "0x1111111111111111111111111111111111111111"
SOURCE = """\
/// Reports assets held for shares.
function totalAssets() external view returns (uint256) { return 1; }
function totalSupply() external view returns (uint256) { return 1; }
"""


class ProtocolSpecTests(unittest.TestCase):
    def test_shortlist_and_verified_source_are_required(self):
        off = generate_specs(address=ADDR, source=SOURCE, on_shortlist=False, verified=True)
        self.assertEqual(off["status"], "skipped")
        self.assertEqual(off["heat_contribution"], 0)
        self.assertFalse(off["specs"])
        unverified = generate_specs(address=ADDR, source=SOURCE, on_shortlist=True, verified=False)
        self.assertIn("verified", unverified["note"])

    def test_template_writes_engine_files_and_caches_the_hash(self):
        old = os.environ.pop("ETH_SCANNER_LLM_API_KEY", None)
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        try:
            self.assertFalse(llm_key())
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                report = generate_specs(
                    address=ADDR,
                    source=SOURCE,
                    on_shortlist=True,
                    verified=True,
                    cache_dir=root / "cache",
                    dest=root / "out",
                )
                self.assertEqual(report["generator"], "template")
                self.assertEqual(report["cache"], "miss")
                self.assertIn("assetsReportedWhenSupply", report["properties"])
                self.assertEqual(report["heat_contribution"], 0)
                text = (root / "out" / "test" / "ProtocolProperties.t.sol").read_text(encoding="utf-8")
                self.assertIn("function test_assetsReportedWhenSupply", text)
                self.assertIn("function property_assetsReportedWhenSupply", text)
                self.assertIn("function echidna_assetsReportedWhenSupply", text)
                spec = (root / "out" / "Protocol.spec").read_text(encoding="utf-8")
                self.assertIn("assetsReportedWhenSupply", spec)
                self.assertNotIn("calldataarg", spec)
                self.assertTrue((root / "out" / "echidna.yaml").is_file())
                self.assertTrue((root / "out" / "medusa.json").is_file())
                names = (root / "out" / "hevm-properties.txt").read_text(encoding="utf-8")
                self.assertIn("assetsReportedWhenSupply", names)
                again = generate_specs(
                    address=ADDR,
                    source=SOURCE,
                    on_shortlist=True,
                    verified=True,
                    cache_dir=root / "cache",
                )
                self.assertEqual(again["cache"], "hit")
                self.assertEqual(again["generator"], "cache")
                self.assertEqual(again["code_hash"], code_hash(SOURCE))
                cached = json.loads((root / "cache" / ("%s.json" % report["code_hash"])).read_text(encoding="utf-8"))
                self.assertNotIn("sk-", json.dumps(cached))
        finally:
            if old is not None:
                os.environ["ETH_SCANNER_LLM_API_KEY"] = old
            if old_openai is not None:
                os.environ["OPENAI_API_KEY"] = old_openai

    def test_a_key_uses_the_model_and_drops_a_recipe(self):
        os.environ["ETH_SCANNER_LLM_API_KEY"] = "sk-test-secret-value"
        try:
            def fetch(_body: str) -> dict:
                return {
                    "invariants": [
                        {"id": "oracleAnswerFresh", "statement": "The answer is positive."},
                        {"id": "stealFunds", "statement": "exploit calldata 0xdeadbeefcafebabe"},
                    ]
                }

            with tempfile.TemporaryDirectory() as tmp:
                report = generate_specs(
                    address=ADDR,
                    source=SOURCE,
                    on_shortlist=True,
                    verified=True,
                    dest=Path(tmp),
                    fetch=fetch,
                )
            self.assertEqual(report["generator"], "llm")
            self.assertEqual(report["properties"], ["oracleAnswerFresh"])
            blob = json.dumps(report)
            self.assertNotIn("sk-test-secret-value", blob)
            self.assertNotIn("deadbeef", blob)
            self.assertEqual(report["heat_contribution"], 0)
        finally:
            os.environ.pop("ETH_SCANNER_LLM_API_KEY", None)

    def test_run_records_a_local_engine_and_adds_no_heat(self):
        from eth_scanner.specs import protocol as specs

        calls: list[list[str]] = []

        def runner(argv: list[str], _cwd: Path) -> tuple[int, str]:
            calls.append(argv)
            return 0, "held"

        original = specs._which
        specs._which = lambda name, _env: "/usr/bin/forge" if name == "forge" else None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report = generate_specs(
                    address=ADDR,
                    source=SOURCE,
                    on_shortlist=True,
                    verified=True,
                    dest=Path(tmp),
                    run=True,
                    runner=runner,
                )
        finally:
            specs._which = original
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(calls[0][0], "forge")
        self.assertNotIn("http", " ".join(calls[0]))
        self.assertIn("echidna", report["engines"]["skipped"])


if __name__ == "__main__":
    unittest.main()
