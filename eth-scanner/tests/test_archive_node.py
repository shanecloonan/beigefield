"""Archive RPC selection and the unprovisioned Erigon sample. Heat stays 0."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from eth_scanner.chain.archive import (
    ERIGON_IMAGE,
    TRACE_PROBE_CU,
    historical_url,
    plan_archive,
    public_plan,
)

ARCHIVE = "https://archive.example/v2/supersecret"
CURRENT = "https://eth.example/v2/othersecret"
ROOT = Path(__file__).resolve().parents[2]

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
    "tests.test_disclosure",
    "tests.test_archive_node",
)


class ArchiveNodeTests(unittest.TestCase):
    def test_historical_reads_prefer_archive_then_the_current_rpc(self):
        both = plan_archive(historical=True, archive_url=ARCHIVE, current_url=CURRENT)
        fallen = plan_archive(historical=True, archive_url="", current_url=CURRENT)
        neither = plan_archive(historical=True, archive_url="", current_url="")
        self.assertEqual(both["source"], "archive")
        self.assertFalse(both["fallback"])
        self.assertEqual(both["heat_contribution"], 0)
        self.assertEqual(fallen["source"], "current")
        self.assertTrue(fallen["fallback"])
        self.assertEqual(neither["status"], "unset")
        self.assertEqual(historical_url(archive_url=ARCHIVE, current_url=CURRENT), ARCHIVE)
        self.assertEqual(historical_url(archive_url="", current_url=CURRENT), CURRENT)
        dumped = json.dumps(public_plan(both))
        self.assertNotIn("supersecret", dumped)
        self.assertNotIn("othersecret", dumped)
        self.assertNotIn("https://", dumped)
        self.assertEqual(public_plan(both)["heat_breakdown"], {"archive": True})
        self.assertEqual(both["probe_cu"], 0)
        self.assertFalse(both["probed"])

    def test_send_and_trace_probes_are_refused_without_a_call(self):
        def boom(*_args):
            raise AssertionError("rpc")

        sent = plan_archive(
            historical=True,
            method="eth_sendRawTransaction",
            archive_url=ARCHIVE,
            current_url=CURRENT,
            probe=True,
            fetch=boom,
        )
        traced = plan_archive(
            method="debug_traceTransaction",
            archive_url=ARCHIVE,
            probe=True,
            fetch=boom,
        )
        self.assertEqual(sent["status"], "refused")
        self.assertEqual(traced["status"], "refused")
        self.assertEqual(sent["_url"], "")
        self.assertGreaterEqual(TRACE_PROBE_CU, 1000)

    def test_a_requested_probe_uses_client_version(self):
        seen: list[str] = []

        def fetch(method, params):
            seen.append(method)
            self.assertEqual(params, [])
            return "erigon/3"

        report = plan_archive(
            historical=True,
            archive_url=ARCHIVE,
            current_url=CURRENT,
            probe=True,
            fetch=fetch,
        )
        self.assertEqual(seen, ["web3_clientVersion"])
        self.assertTrue(report["probed"])
        self.assertEqual(report["probe_cu"], 0)
        self.assertNotIn("debug_traceTransaction", report["calls"])
        self.assertNotIn("supersecret", json.dumps(public_plan(report)))

    def test_erigon_sample_stays_local_and_unstarted(self):
        compose = (ROOT / "infra" / "erigon" / "docker-compose.yml").read_text(encoding="utf-8")
        unit = (ROOT / "infra" / "erigon" / "erigon.service").read_text(encoding="utf-8")
        docs = (ROOT / "infra" / "erigon" / "README.md").read_text(encoding="utf-8")
        self.assertIn(ERIGON_IMAGE, compose)
        self.assertIn("--prune.mode=archive", compose)
        self.assertIn("127.0.0.1:8545:8545", compose)
        self.assertIn("--http.api=eth,web3,net,debug,trace", compose)
        self.assertNotIn("EXTERNAL_IP", compose)
        self.assertNotIn("eth_send", compose)
        self.assertNotIn("WantedBy=", unit)
        self.assertIn("--http.addr=127.0.0.1", unit)
        self.assertIn("--prune.mode=archive", unit)
        self.assertIn("2–4 TB", docs)
        self.assertIn("not provisioned", docs.lower())
        benchmark = (ROOT / ".github" / "workflows" / "eth-scanner-benchmark.yml").read_text(encoding="utf-8")
        for name in _REQUIRED:
            self.assertIn(name, benchmark)


if __name__ == "__main__":
    unittest.main()
