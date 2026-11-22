"""Cross-contract paths are leads. They do not add heat or change detectors."""

from __future__ import annotations

import unittest

from eth_scanner.advanced.reachability import reachability_report, resolve_public
from eth_scanner.research.detectors import run_custom_detectors
from eth_scanner.stages.fusion import annotate_stages, complete_stage

_SPLIT = """
contract Pool {
    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
contract Router {
    address public pool;
    function deposit(address to, uint256 amount) external {
        Pool(pool).mint(to, amount);
    }
    function admin(address to, uint256 amount) external onlyOwner {
        Pool(pool).mint(to, amount);
    }
}
"""

_SAME = """
contract Vault {
    function deposit(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
"""

_SIG = """
contract Nonces {
    mapping(address => uint256) public nonces;
    function consume(address user) external {
        nonces[user] += 1;
    }
}
contract Router {
    function relay(address user, bytes memory sig) external {
        address signer = ecrecover(bytes32(0), 27, bytes32(0), bytes32(0));
        Nonces(user).consume(user);
    }
}
"""

_SIG_SAME = """
contract Router {
    mapping(address => uint256) public nonces;
    function relay(address user, bytes memory sig) external {
        address signer = ecrecover(bytes32(0), 27, bytes32(0), bytes32(0));
        nonces[user] += 1;
    }
}
"""

_LIB = """
library Pull {
    function take(address token, address who, uint256 amount) internal {
        IERC20(token).transferFrom(who, address(this), amount);
    }
}
contract Router {
    function deposit(address token, address who, uint256 amount) external {
        Pull.take(token, who, amount);
    }
}
"""


class ReachabilityTests(unittest.TestCase):
    def test_router_to_pool_is_a_lead_without_heat(self) -> None:
        report = reachability_report(_SPLIT, resolved={"pool": "0x" + "ab" * 20})
        self.assertEqual(report["heat_contribution"], 0)
        lead = report["leads"][0]
        self.assertEqual(lead["kind"], "accounting-split")
        self.assertEqual(lead["entry"], "Router.deposit")
        self.assertEqual(lead["sink"], "Pool.mint")
        self.assertEqual(lead["target"], "0x" + "ab" * 20)
        self.assertEqual(lead["heat_contribution"], 0)
        self.assertNotIn("admin", [row["entry"] for row in report["leads"]])

    def test_same_contract_and_same_nonce_are_not_cross_contract(self) -> None:
        self.assertEqual(reachability_report(_SAME)["leads"], [])
        self.assertEqual(reachability_report(_SIG_SAME)["leads"], [])

    def test_signature_and_nonce_in_different_contracts(self) -> None:
        report = reachability_report(_SIG)
        self.assertEqual(report["leads"][0]["kind"], "signature-nonce-split")
        self.assertEqual(report["leads"][0]["heat_contribution"], 0)

    def test_library_value_move_is_a_lead(self) -> None:
        report = reachability_report(_LIB)
        self.assertEqual(report["leads"][0]["kind"], "library-misuse")
        self.assertEqual(report["leads"][0]["sink"], "Pull.take")

    def test_public_getter_is_read_only_and_a_lead_does_not_change_heat(self) -> None:
        word = "0x" + "00" * 12 + "cd" * 20

        def call(_to: str, _data: str) -> str:
            return word

        found = resolve_public("contract R { address public pool; }", "0x" + "11" * 20, call)
        self.assertEqual(found["pool"], "0x" + "cd" * 20)
        self.assertEqual(resolve_public("contract R { address public pool; }", "0x" + "11" * 20, None), {})
        start = annotate_stages({"privileged_callable": 4, "total": 4}, heat=4)
        done = complete_stage(start, "cross-contract", facts=[{
            "fact": "accounting-split",
            "heat": 0,
            "direction": "support",
        }], confidence=0.4)
        self.assertEqual(done["fused_heat"], 4)

    def test_detectors_are_unchanged(self) -> None:
        address = "0x" + "22" * 20
        before = [row.id for row in run_custom_detectors(address=address, source=_SPLIT)]
        reachability_report(_SPLIT)
        after = [row.id for row in run_custom_detectors(address=address, source=_SPLIT)]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
