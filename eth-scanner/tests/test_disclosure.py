"""Disclosure drafts stay on disk. The module does not send them."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eth_scanner.disclosure.draft import (
    SEAL_911_URL,
    draft_disclosure,
    public_report,
    security_txt_urls,
)

ADDRESS = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MODULE = Path(__file__).resolve().parents[1] / "src" / "eth_scanner" / "disclosure" / "draft.py"

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
)


class DisclosureDraftTests(unittest.TestCase):
    def test_the_module_has_no_send_path(self):
        text = MODULE.read_text(encoding="utf-8").lower()
        for banned in ("smtplib", "smtp", "sendmail", "mailto:", "post"):
            self.assertNotIn(banned, text)

    def test_lookup_gets_security_txt_and_the_draft_is_not_sent(self):
        seen: list[str] = []

        def fetch(url: str) -> tuple[int, str]:
            seen.append(url)
            if url.endswith("/.well-known/security.txt"):
                return 200, "Contact: safety@example.com\nPolicy: https://example.com/policy\n"
            return 404, ""

        with TemporaryDirectory() as tmp:
            report = draft_disclosure(
                address=ADDRESS,
                domain="example.com",
                slug="example",
                status="FP",
                lookup=True,
                fetch=fetch,
                dest=Path(tmp),
            )
            draft = (Path(tmp) / "disclosure.md").read_text(encoding="utf-8")
            stored = json.loads((Path(tmp) / "disclosure.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["triage"], "fp")
        self.assertFalse(report["sent"])
        self.assertEqual(report["heat_contribution"], 0)
        self.assertEqual(seen, security_txt_urls("example.com"))
        self.assertEqual(report["contacts"], ["safety@example.com"])
        self.assertEqual(report["urls"]["seal_911"], SEAL_911_URL)
        self.assertIn("immunefi.com/bug-bounty/example/", report["urls"]["immunefi"])
        self.assertIn("cantina.xyz/bounties/example", report["urls"]["cantina"])
        self.assertIn("Not sent", draft)
        self.assertFalse(stored["sent"])
        public = public_report(report)
        self.assertEqual(public["heat"], 0)
        self.assertEqual(public["heat_breakdown"]["disclosure_status"], "fp")
        self.assertTrue(public["heat_breakdown"]["disclosure"])

    def test_without_lookup_nothing_is_contacted(self):
        def boom(_url: str) -> tuple[int, str]:
            raise AssertionError("network")

        report = draft_disclosure(
            address=ADDRESS,
            domain="example.com",
            status="unreviewed",
            lookup=False,
            fetch=boom,
        )
        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["sent"])
        self.assertEqual(report["reads"], [])
        self.assertIn("security.txt", report["urls"]["security_txt"])

    def test_a_private_host_and_a_bad_note_are_refused(self):
        def boom(_url: str) -> tuple[int, str]:
            raise AssertionError("network")

        local = draft_disclosure(address=ADDRESS, domain="localhost", lookup=True, fetch=boom)
        noted = draft_disclosure(address=ADDRESS, note="exploit the vault", status="credible")
        self.assertEqual(local["status"], "refused")
        self.assertEqual(noted["status"], "refused")
        self.assertFalse(local["sent"])
        self.assertFalse(noted["disclosure"])

    def test_the_benchmark_list_keeps_every_module(self):
        root = Path(__file__).resolve().parents[2]
        benchmark = (root / ".github" / "workflows" / "eth-scanner-benchmark.yml").read_text(encoding="utf-8")
        for name in _REQUIRED:
            self.assertIn(name, benchmark)


if __name__ == "__main__":
    unittest.main()
