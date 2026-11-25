"""Fuzz corpora are cache keys. Heat stays 0 and seeds stay out of the report."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eth_scanner.fuzz.corpus import (
    ENGINES,
    cache_key,
    code_hash,
    github_output,
    plan_corpus,
    public_report,
    restore_prefix,
    seed_names,
    write_seed,
)
from eth_scanner.specs.protocol import code_hash as spec_hash

SOURCE = """
contract Vault {
    function poke() external pure returns (uint256) {
        return 1; // notStoredBody
    }
}
"""

_REQUIRED = (
    "tests.test_benchmark",
    "tests.test_conservation",
    "tests.test_gated_leads",
    "tests.test_signal_rerun",
    "tests.test_small_value_under5k",
    "tests.test_static_evidence",
    "tests.test_sequences",
    "tests.test_perturb",
    "tests.test_corpus",
    "tests.test_clones",
    "tests.test_priority",
    "tests.test_bytecode_surface",
    "tests.test_external_suites",
    "tests.test_weird_tokens",
    "tests.test_heimdall_funded",
    "tests.test_fork_verify",
    "tests.test_certora_prover",
    "tests.test_hevm_value",
    "tests.test_wake_runner",
    "tests.test_storage_fidelity",
    "tests.test_upgrade_layout",
    "tests.test_corpus_recall",
    "tests.test_pyrometer",
    "tests.test_smt_checker",
    "tests.test_engine_fuzz",
    "tests.test_protocol_specs",
    "tests.test_exploit_replay",
    "tests.test_shaped_watch",
    "tests.test_fund_flow",
    "tests.test_system_fork",
    "tests.test_fuzz_corpus",
)


class FuzzCorpusTests(unittest.TestCase):
    def test_keys_share_a_prefix_and_the_body_is_dropped(self):
        first = plan_corpus(SOURCE, run_id="101")
        second = plan_corpus("  %s  " % SOURCE.strip(), run_id="202")
        self.assertEqual(first["status"], "ok")
        self.assertTrue(first["fuzz_corpus"])
        self.assertEqual(first["heat_contribution"], 0)
        self.assertEqual(first["code_hash"], second["code_hash"])
        self.assertEqual(first["code_hash"], spec_hash(SOURCE))
        for engine in ENGINES:
            key = first["engines"][engine]["key"]
            prefix = first["engines"][engine]["restore"]
            self.assertEqual(key, cache_key(engine, first["code_hash"], "101"))
            self.assertEqual(prefix, restore_prefix(engine, first["code_hash"]))
            self.assertTrue(key.startswith(prefix))
            self.assertTrue(second["engines"][engine]["key"].startswith(prefix))
            self.assertNotEqual(key, second["engines"][engine]["key"])
        dumped = json.dumps(public_report(first))
        self.assertNotIn("notStoredBody", dumped)
        self.assertNotIn("http", dumped)
        self.assertEqual(public_report(first)["heat_breakdown"], {"fuzz_corpus": True})

    def test_a_bad_run_id_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fuzz-corpus"
            report = plan_corpus(SOURCE, run_id="../secret", dest=dest)
            self.assertEqual(report["status"], "refused")
            self.assertFalse(report["fuzz_corpus"])
            self.assertFalse(dest.exists())
            self.assertNotIn("secret", json.dumps(public_report(report)))

    def test_seeds_stay_in_the_hash_directory(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp)
            report = plan_corpus(SOURCE, run_id="7", dest=dest)
            digest = report["code_hash"]
            write_seed(dest, "medusa", digest, "seed-1", b"coverage")
            with self.assertRaises(ValueError):
                write_seed(dest, "medusa", digest, "../escape", b"nope")
            again = plan_corpus(SOURCE, run_id="8", dest=dest)
            self.assertEqual(seed_names(dest, "medusa", digest), ["seed-1"])
            self.assertEqual(again["engines"]["medusa"]["restore"], report["engines"]["medusa"]["restore"])
            plan = json.loads((dest / "plan.json").read_text(encoding="utf-8"))
            self.assertNotIn("notStoredBody", json.dumps(plan))
            self.assertNotIn("coverage", json.dumps(plan))
            output = github_output(report)
            self.assertIn("medusa_key=%s" % cache_key("medusa", digest, "7"), output)
            self.assertIn("medusa_restore=%s" % restore_prefix("medusa", digest), output)
            self.assertNotIn("\n\n", output.strip() + "x")

    def test_the_workflow_caches_each_engine_and_does_not_start_one(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github" / "workflows" / "eth-scanner-fuzz-corpus.yml").read_text(encoding="utf-8")
        benchmark = (root / ".github" / "workflows" / "eth-scanner-benchmark.yml").read_text(encoding="utf-8")
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("actions/cache/restore@v4", workflow)
        self.assertIn("actions/cache/save@v4", workflow)
        self.assertIn("workflow_dispatch", workflow)
        self.assertNotIn("schedule:", workflow)
        for engine in ENGINES:
            self.assertIn("%s_key" % engine, workflow)
            self.assertIn("%s_restore" % engine, workflow)
        self.assertNotIn("eth_send", workflow)
        self.assertNotRegex(workflow, r"(?m)^\s*(echidna|medusa|ityfuzz)\b")
        self.assertIn("/fuzz-corpus/", ignore)
        for name in _REQUIRED:
            self.assertIn(name, benchmark)

    def test_empty_source_is_not_a_corpus(self):
        report = plan_corpus("   ", run_id="1")
        self.assertEqual(report["status"], "skipped")
        self.assertFalse(report["fuzz_corpus"])
        self.assertEqual(code_hash(SOURCE), spec_hash(SOURCE))


if __name__ == "__main__":
    unittest.main()
