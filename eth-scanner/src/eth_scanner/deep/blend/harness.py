"""Write a local Foundry property project for one target or a small bundle.

The harness deploys or attaches the related contracts and checks that an
unprivileged caller does not end richer. It does not broadcast.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_FN_RX = re.compile(
    r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
)


def public_functions(source: str) -> list[str]:
    names: list[str] = []
    for name, args in _FN_RX.findall(source or ""):
        if name in {"receive", "fallback"} or name.startswith("_"):
            continue
        if name not in names:
            names.append(name if not args.strip() else name)
    return names[:12]


def write_project(dest: Path, contracts: list[dict[str, Any]]) -> Path:
    """contracts: [{name, source, address?}]. Local anvil / forge only."""
    root = Path(dest)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "test").mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    fnames: list[str] = []
    for item in contracts:
        name = str(item.get("name") or "Target")
        source = str(item.get("source") or "")
        if "pragma solidity" not in source:
            source = "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n" + source
        (root / "src" / ("%s.sol" % name)).write_text(source, encoding="utf-8")
        names.append(name)
        for fn in public_functions(source):
            if fn not in fnames:
                fnames.append(fn)
    joined = ", ".join('"%s"' % name for name in names) or '"Target"'
    harness = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IBound {
    function poke() external;
    function skim() external;
    function deposit() external payable;
    function withdraw(uint256 amount) external;
    function claim() external;
}

/// Conservation harness. Local simulation only. Does not send transactions.
contract ConservationHarness {
    address internal outsider = address(0xBEEF);
    address[] internal targets;

    function setUp() public {
        // Engines deploy this harness and the contracts under src/ beside it.
        // A compile or setUp failure is a skip, not a finding.
    }

    function _check(address target) internal {
        uint256 beforeBal = outsider.balance;
        (bool ok, ) = target.call(abi.encodeWithSignature("poke()"));
        ok;
        (bool ok2, ) = target.call(abi.encodeWithSignature("skim()"));
        ok2;
        if (outsider.balance > beforeBal) {
            uint256 delta = outsider.balance - beforeBal;
            require(false, string(abi.encodePacked("caller_profit_delta=", _u(delta))));
        }
    }

    /// Halmos symbolic check. A counterexample is evidence, not a transaction.
    function check_no_caller_profit(address target) public {
        _check(target);
    }

    /// Echidna property. False means the outsider balance rose. Local simulation only.
    function echidna_no_caller_profit() public returns (bool) {
        uint256 beforeBal = outsider.balance;
        _check(address(0));
        return outsider.balance <= beforeBal;
    }

    /// Medusa property. True means the outsider did not gain. Local only.
    function property_no_caller_profit() public returns (bool) {
        uint256 beforeBal = outsider.balance;
        (bool ok, ) = address(0).call(abi.encodeWithSignature("skim()"));
        ok;
        return outsider.balance <= beforeBal;
    }

    /// Medusa assertion entry. Compile or setUp failure is a skip.
    function fuzz_conservation(address target) public {
        uint256 beforeBal = outsider.balance;
        (bool ok, ) = target.call(abi.encodeWithSignature("skim()"));
        ok;
        assert(outsider.balance <= beforeBal);
    }

    function _u(uint256 value) internal pure returns (string memory) {
        if (value == 0) return "0";
        bytes memory buf = new bytes(78);
        uint256 i = 78;
        while (value != 0) {
            i--;
            buf[i] = bytes1(uint8(48 + value % 10));
            value /= 10;
        }
        bytes memory out = new bytes(78 - i);
        for (uint256 j = 0; j < out.length; j++) out[j] = buf[i + j];
        return string(out);
    }
}
"""
    # The unused helper keeps the file referencing every contract name so a
    # reviewer can see the bundle the fuzzers are pointed at.
    note = "\n".join("// bundle: %s" % name for name in names)
    # src/, not test/: Foundry and crytic-compile export src contracts to Medusa.
    (root / "src" / "ConservationHarness.sol").write_text(note + "\n" + harness, encoding="utf-8")
    (root / "foundry.toml").write_text(
        '[profile.default]\nsrc = "src"\nout = "out"\ntest = "test"\nsolc = "0.8.20"\n',
        encoding="utf-8",
    )
    (root / "medusa.json").write_text(json.dumps({
        "fuzzing": {
            "workers": 1,
            "timeout": 20,
            "testLimit": 50,
            "callSequenceLength": 8,
            "targetContracts": ["ConservationHarness"],
            "deploymentOrder": ["ConservationHarness"],
            "blockNumberDelayMax": 0,
            "blockTimestampDelayMax": 0,
            "testing": {
                "stopOnFailedTest": True,
                "testAllContracts": False,
                "assertionTesting": {"enabled": True, "testViewMethods": False},
                "propertyTesting": {"enabled": True, "testPrefixes": ["property_"]},
                "optimizationTesting": {"enabled": False},
            },
        },
        "compilation": {"platform": "crytic-compile", "platformConfig": {"target": "."}},
        "slither": {"useSlither": False},
    }, indent=2), encoding="utf-8")
    (root / "echidna.yaml").write_text(
        "testMode: property\ntestLimit: 50\nformat: text\ntimeout: 20\ncoverage: false\n",
        encoding="utf-8",
    )
    (root / "bundle.json").write_text(
        json.dumps({"contracts": names, "functions": fnames, "label": joined}, indent=2),
        encoding="utf-8",
    )
    return root
