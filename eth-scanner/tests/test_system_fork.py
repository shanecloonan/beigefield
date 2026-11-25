"""A system fork names fund-flow dependencies. Heat stays 0. No broadcast."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eth_scanner.forks.system import MAX_DEPENDENCIES, plan_system, public_report

TARGET = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _addr(n: int) -> str:
    return "0x%040x" % n


def _vault() -> str:
    return """
contract Vault {
    function poke() external {
        IOracle(%s).latestAnswer();
        IPair(%s).getReserves();
        ILending(%s).borrow();
        IERC20(%s).transfer(msg.sender, 1);
    }
}
""" % (_addr(1), _addr(2), _addr(3), _addr(4))


class SystemForkTests(unittest.TestCase):
    def test_shortlist_and_verified_source_are_required(self):
        def boom(*_args):
            raise AssertionError("rpc")

        off = plan_system(_vault(), address=TARGET, on_shortlist=False, verified=True, caller=boom)
        unverified = plan_system(_vault(), address=TARGET, on_shortlist=True, verified=False, caller=boom)
        self.assertEqual(off["status"], "skipped")
        self.assertFalse(off["system"])
        self.assertEqual(unverified["status"], "skipped")
        self.assertEqual(off["heat_contribution"], 0)

    def test_a_public_url_is_refused_before_any_call(self):
        def boom(*_args):
            raise AssertionError("rpc")

        report = plan_system(
            _vault(),
            address=TARGET,
            fork_url="https://eth-mainnet.example/v2/supersecret",
            on_shortlist=True,
            verified=True,
            execute=True,
            caller=boom,
        )
        self.assertEqual(report["status"], "refused")
        self.assertTrue(report["refused"])
        self.assertFalse(report["system"])
        self.assertNotIn("supersecret", json.dumps(report))
        self.assertNotIn("eth-mainnet.example", json.dumps(public_report(report)))

    def test_dependency_roles_are_capped_and_the_body_is_dropped(self):
        lines = ["contract Vault { function poke() external {"]
        for n in range(1, 6):
            lines.append("IOracle(%s).latestAnswer();" % _addr(n))
        for n in range(100, 108):
            lines.append("token.approve(%s, 1);" % _addr(n))
        lines.append("} } // notStoredBody")
        report = plan_system(
            "\n".join(lines),
            address=TARGET,
            on_shortlist=True,
            verified=True,
        )
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["system"])
        self.assertTrue(report["truncated"])
        self.assertEqual(report["dependency_count"], MAX_DEPENDENCIES)
        self.assertEqual(report["heat_contribution"], 0)
        roles = [row["role"] for row in report["dependencies"]]
        self.assertEqual(roles.count("oracle"), 5)
        self.assertNotIn(_addr(107), [row["address"] for row in report["dependencies"]])
        self.assertNotIn("notStoredBody", json.dumps(report))
        self.assertNotIn("http", json.dumps(public_report(report)))

    def test_run_reads_code_on_loopback_only(self):
        seen: list[str] = []

        def caller(url, method, params):
            seen.append(method)
            self.assertIn("127.0.0.1", url)
            self.assertEqual(method, "eth_getCode")
            addr = params[0]
            if addr == _addr(1):
                return "0x6001"
            return "0x"

        with TemporaryDirectory() as tmp:
            report = plan_system(
                _vault(),
                address=TARGET,
                fork_url="http://127.0.0.1:8545",
                on_shortlist=True,
                verified=True,
                execute=True,
                caller=caller,
                dest=Path(tmp),
            )
            text = (Path(tmp) / "test" / "SystemFork.t.sol").read_text(encoding="utf-8")
            manifest = (Path(tmp) / "system.json").read_text(encoding="utf-8")
        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["executed"])
        self.assertEqual(report["loaded"], 1)
        self.assertFalse(report["target_present"])
        self.assertEqual(set(seen), {"eth_getCode"})
        self.assertNotIn("eth_send", json.dumps(report))
        self.assertIn("public view", text)
        self.assertNotIn("call{value", text)
        self.assertNotIn("http", manifest)
        self.assertEqual(public_report(report)["heat"], 0)
        self.assertEqual(public_report(report)["heat_breakdown"], {"system": True})

    def test_an_empty_graph_does_not_count_as_a_system(self):
        report = plan_system(
            "contract Vault { function poke() external {} }",
            address=TARGET,
            on_shortlist=True,
            verified=True,
        )
        self.assertEqual(report["status"], "empty")
        self.assertFalse(report["system"])


if __name__ == "__main__":
    unittest.main()
