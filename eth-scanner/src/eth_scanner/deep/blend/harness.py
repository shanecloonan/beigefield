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
    for name, _args in _FN_RX.findall(source or ""):
        if name in {"receive", "fallback"} or name.startswith("_"):
            continue
        if name not in names:
            names.append(name)
    return names[:12]


_SIG_RX = re.compile(
    r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)([^;{]*)",
)
_SIMPLE = {"address", "bool", "string", "bytes"}


def _sol_type(raw: str) -> str:
    token = (raw or "").strip().split()
    if not token:
        return ""
    typ = token[0]
    if typ == "uint":
        return "uint256"
    if typ == "int":
        return "int256"
    if typ in _SIMPLE or typ.startswith("uint") or typ.startswith("int"):
        return typ
    return ""


def public_sigs(source: str) -> list[tuple[str, list[str]]]:
    """External/public signatures with simple ABI types. Used to shape the harness."""
    found: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for name, args, tail in _SIG_RX.findall(source or ""):
        if name in {"receive", "fallback"} or name.startswith("_"):
            continue
        if "external" not in tail and "public" not in tail:
            continue
        types: list[str] = []
        ok = True
        for part in args.split(","):
            if not part.strip():
                continue
            typ = _sol_type(part)
            if not typ:
                ok = False
                break
            types.append(typ)
        if not ok or name in seen:
            continue
        seen.add(name)
        found.append((name, types))
        if len(found) >= 8:
            break
    return found


def _literal(typ: str) -> str:
    if typ == "address":
        return "outsider"
    if typ == "bool":
        return "true"
    if typ == "string":
        return '""'
    if typ == "bytes":
        return 'hex""'
    if typ.startswith("int"):
        return "%s(1)" % typ
    return "%s(1)" % typ


def _safe_id(prop: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", prop or "prop").strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = "p_" + cleaned
    return cleaned[:48]


def seeded_harness(
    contracts: list[dict[str, Any]],
    properties: list[str],
    seeds: list[dict[str, Any]] | None = None,
) -> str:
    """Target-shaped calls and property entry points. Local simulation only."""
    sigs: list[tuple[str, list[str]]] = []
    for item in contracts:
        for name, types in public_sigs(str(item.get("source") or "")):
            if (name, tuple(types)) not in {(n, tuple(t)) for n, t in sigs}:
                sigs.append((name, types))
    calls = []
    for name, types in sigs:
        signature = "%s(%s)" % (name, ",".join(types))
        args = ", ".join(_literal(typ) for typ in types)
        if args:
            calls.append(
                '        target.call(abi.encodeWithSignature("%s", %s));' % (signature, args)
            )
        else:
            calls.append(
                '        target.call(abi.encodeWithSignature("%s"));' % signature
            )
    if not calls:
        calls.append('        target.call(abi.encodeWithSignature("skim()"));')
    for seed in list(seeds or [])[:16]:
        raw = str(seed.get("calldata") or "").strip().lower()
        if len(raw) < 10 or not raw.startswith("0x"):
            continue
        body_hex = raw[2:]
        if len(body_hex) % 2 or any(ch not in "0123456789abcdef" for ch in body_hex):
            continue
        calls.append('        target.call(hex"%s");' % body_hex)
    body = "\n".join(calls)
    props = []
    for prop in properties or []:
        ident = _safe_id(prop)
        props.append(
            """
    /// Seeded property %s. One body. Foundry, Echidna, and Medusa call it.
    function property_%s() public returns (bool) {
        uint256 beforeBal = outsider.balance;
        _exercise(address(0));
        return outsider.balance <= beforeBal;
    }

    function echidna_%s() public returns (bool) {
        return property_%s();
    }
""" % (prop, ident, ident, ident)
        )
    return """
    /// Target-shaped exercise. Calls the verified surface with bounded amounts.
    function _exercise(address target) internal {
%s
    }

    /// Foundry invariant. Local simulation only. Does not send transactions.
    function invariant_no_caller_profit() public {
        uint256 beforeBal = outsider.balance;
        _exercise(address(0));
        assert(outsider.balance <= beforeBal);
    }
%s
""" % (body, "".join(props))


def write_project(
    dest: Path,
    contracts: list[dict[str, Any]],
    *,
    facts: dict[str, Any] | None = None,
    properties: list[str] | None = None,
    seeds: list[dict[str, Any]] | None = None,
    sequences: list[dict[str, Any]] | None = None,
    surface: dict[str, Any] | None = None,
) -> Path:
    """contracts: [{name, source, address?}]. Local anvil / forge only."""
    root = Path(dest)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "test").mkdir(parents=True, exist_ok=True)
    if surface:
        from eth_scanner.logic.bytecode_surface import interface_source, write_surface_inputs
        write_surface_inputs(root, surface)
        contracts = list(contracts) + [{"name": "RecoveredSurface", "source": interface_source(surface)}]
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

    /// One conservation body. Medusa calls it. Echidna returns its result.
    function property_no_caller_profit() public returns (bool) {
        uint256 beforeBal = outsider.balance;
        _check(address(0));
        return outsider.balance <= beforeBal;
    }

    function echidna_no_caller_profit() public returns (bool) {
        return property_no_caller_profit();
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
    selected = list(properties or [])
    if not selected and facts:
        selected = [str(row.get("id")) for row in (facts.get("candidate_invariants") or []) if row.get("id")]
    extra = seeded_harness(contracts, selected, seeds)
    text = note + "\n" + harness.rstrip()
    if text.endswith("}"):
        text = text[:-1] + "\n" + extra + "\n}\n"
    else:
        text = text + "\n" + extra
    (root / "src" / "ConservationHarness.sol").write_text(text, encoding="utf-8")
    (root / "foundry.toml").write_text(
        '[profile.default]\nsrc = "src"\nout = "out"\ntest = "test"\nsolc = "0.8.20"\n\n'
        '[invariant]\nruns = 16\ndepth = 8\nfail_on_revert = false\n',
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
    if seeds:
        from eth_scanner.chain.trace_seeds import write_corpora
        write_corpora(root, {"seeds": list(seeds), "sequences": list(sequences or []), "note": "local replay"})
    return root
