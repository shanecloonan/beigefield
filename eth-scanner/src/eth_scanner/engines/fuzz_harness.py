"""Auto-generate defensive Foundry/Medusa/Halmos property harnesses by class.

Harnesses assert conservation / access-control only — no attacker contracts,
no broadcast. Halmos uses vm.etch (supports it); Foundry may additionally
`--fork-url` for live state.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

# Properties emitted per family — used for logging/counts.
PROPERTY_IDS_BY_CLASS: dict[str, tuple[str, ...]] = {
    "vault": (
        "solvency_assets_cover_shares",
        "share_price_round_trip",
        "access_control_non_owner",
        "no_third_party_balance_drop",
    ),
    "staking": (
        "solvency_assets_cover_shares",
        "share_price_round_trip",
        "access_control_non_owner",
        "no_third_party_balance_drop",
    ),
    "lending": (
        "solvency_assets_cover_shares",
        "access_control_non_owner",
        "no_third_party_balance_drop",
    ),
    "pool": (
        "solvency_assets_cover_shares",
        "share_price_round_trip",
        "access_control_non_owner",
        "no_third_party_balance_drop",
    ),
    "bridge": (
        "access_control_non_owner",
        "no_third_party_balance_drop",
    ),
    "maker": (
        "solvency_assets_cover_shares",
        "access_control_non_owner",
    ),
    "custody": (
        "access_control_non_owner",
        "no_third_party_balance_drop",
    ),
}

_DEFAULT_PROPS = (
    "access_control_non_owner",
    "no_third_party_balance_drop",
)

# Cap etched runtime bytecode so the harness stays compilable in CI.
_MAX_ETCH_BYTES = 24_576

# Precompiled MockBound runtime (solc 0.8.20) — Halmos cannot `new` / deployCode,
# so the no-bytecode fallback etches this constant instead of deploying.
MOCK_BOUND_RUNTIME_HEX = (
    "608060405234801561000f575f80fd5b506004361061009b575f3560e01c80638456cb59116100"
    "635780638456cb59146100fc5780638da5cb5b14610104578063c6e6f592146100bb578063f2fde38b"
    "146100d4578063f851a4401461012f575f80fd5b806301e1d1141461009f57806307a2d13a146100bb"
    "57806318160ddd146100cc5780633659cfe6146100d457806370a08231146100e9575b5f80fd5b6100"
    "a860015481565b6040519081526020015b60405180910390f35b6100a86100c9366004610175565b90"
    "565b6100a85f5481565b6100e76100e236600461018c565b610140565b005b6100a86100f736600461"
    "018c565b505f90565b6100e7610140565b600254610117906001600160a01b031681565b6040516001"
    "600160a01b0390911681526020016100b2565b6002546001600160a01b0316610117565b6040516246"
    "1bcd60e51b815260206004820152600660248201526519195b9a595960d21b60448201526064016040"
    "5180910390fd5b5f60208284031215610185575f80fd5b5035919050565b5f6020828403121561019c"
    "575f80fd5b81356001600160a01b03811681146101b2575f80fd5b939250505056fea2646970667358"
    "221220116249f34511d9203c831b7d604372805dd8c53fe2811adb8aef6b4ccc3974a764736f6c6343"
    "0008140033"
)

_PRAGMA_RX = re.compile(r"pragma\s+solidity\s+([^;]+);", re.I)
_COMPILER_RX = re.compile(r"v?(0\.\d+\.\d+)")


def properties_for_class(contract_class: str) -> tuple[str, ...]:
    return PROPERTY_IDS_BY_CLASS.get((contract_class or "").lower(), _DEFAULT_PROPS)


def detect_solc_version(
    *,
    source: str = "",
    compiler: Optional[str] = None,
    default: str = "0.8.20",
) -> str:
    """Pick a solc version from Etherscan compiler string or pragma."""
    if compiler:
        m = _COMPILER_RX.search(compiler)
        if m:
            return m.group(1)
    m = _PRAGMA_RX.search(source or "")
    if m:
        raw = m.group(1).strip()
        # Take the highest concrete 0.x.y mentioned.
        found = _COMPILER_RX.findall(raw)
        if found:
            # Prefer 0.8.x for harness/Test compatibility when range allows.
            eights = [v for v in found if v.startswith("0.8.")]
            return eights[-1] if eights else found[-1]
    return default


def harness_solc_version(
    *,
    source: str = "",
    compiler: Optional[str] = None,
    floor: str = "0.8.20",
) -> str:
    """Solc for the LiveProperties harness — must satisfy pragma ^0.8.20.

    Target contracts may be 0.4.x / 0.8.18; we only compile our etch harness,
    so floor at 0.8.20 (and prefer the target's 0.8.x when newer).
    """
    detected = detect_solc_version(source=source, compiler=compiler, default=floor)
    return _max_solc(detected, floor)


def _max_solc(a: str, b: str) -> str:
    def parts(v: str) -> tuple[int, int, int]:
        try:
            x, y, z = (v or "0.0.0").split(".")[:3]
            return int(x), int(y), int(z)
        except (TypeError, ValueError):
            return (0, 0, 0)
    return a if parts(a) >= parts(b) else b


def write_live_fuzz_project(
    dest: Path,
    *,
    address: str,
    contract_class: str = "vault",
    contract_name: Optional[str] = None,
    solc_version: Optional[str] = None,
    compiler: Optional[str] = None,
    source: str = "",
    runtime_bytecode: str = "",
    source_dir: Optional[Path] = None,
    allow_mock_etch: bool = False,
    include_target_sources: bool = False,
) -> tuple[Path, list[str]]:
    """Materialize a Foundry (+ Medusa/Halmos) project with forge-std + etch setUp.

    Halmos cannot `new`/deployCode — pass allow_mock_etch=True so missing
    runtime bytecode falls back to etching MOCK_BOUND_RUNTIME_HEX. Foundry
    fork fuzz should leave allow_mock_etch=False and rely on --fork-url.

    Target sources are NOT copied by default: multi-file Etherscan trees often
    reference @openzeppelin/... that we do not vendor, and that broke CI
    compile. Etch uses runtime bytecode only.
    """
    root = Path(dest)
    if root.exists():
        shutil.rmtree(root)
    (root / "src").mkdir(parents=True)
    (root / "test").mkdir(parents=True)
    (root / "lib" / "forge-std" / "src").mkdir(parents=True)

    props = list(properties_for_class(contract_class))
    addr_hex = _hex40(address)
    name = (contract_name or "Target").replace(" ", "")[:40] or "Target"
    # Always compile harness at >=0.8.20 (pragma on LiveProperties/MockBound).
    solc = solc_version or harness_solc_version(source=source, compiler=compiler)

    # Vendor minimal forge-std (Vm + Test) for Halmos etch support.
    _copy_forge_std(root / "lib" / "forge-std" / "src")
    (root / "remappings.txt").write_text(
        "forge-std/=lib/forge-std/src/\n",
        encoding="utf-8",
    )

    remaps_extra: list[str] = []
    if include_target_sources:
        remaps_extra = _materialize_target_sources(root, source=source, source_dir=source_dir)

    remappings_toml = 'remappings = ["forge-std/=lib/forge-std/src/"'
    for r in remaps_extra:
        remappings_toml += ', "%s"' % r.replace('"', "")
    remappings_toml += "]"

    (root / "foundry.toml").write_text(
        "\n".join([
            "[profile.default]",
            'src = "src"',
            'test = "test"',
            'out = "out"',
            'libs = ["lib"]',
            'solc = "%s"' % solc,
            "optimizer = true",
            "optimizer_runs = 200",
            "ffi = false",
            "fs_permissions = []",
            "isolate = false",
            "evm_version = \"shanghai\"",
            "auto_detect_solc = false",
            remappings_toml,
            "",
            "[profile.default.fuzz]",
            "runs = 32",
            "",
        ]),
        encoding="utf-8",
    )

    (root / "src" / "IFundsAtRisk.sol").write_text(_IFACE_SOL, encoding="utf-8")
    (root / "src" / "MockBound.sol").write_text(_MOCK_BOUND_SOL, encoding="utf-8")

    etch_hex = _runtime_hex(runtime_bytecode)
    if etch_hex and (len(etch_hex) // 2) > _MAX_ETCH_BYTES:
        etch_hex = ""
    if not etch_hex and allow_mock_etch:
        etch_hex = MOCK_BOUND_RUNTIME_HEX

    (root / "test" / "LiveProperties.t.sol").write_text(
        _live_properties_sol(
            addr_hex, name, contract_class, props,
            etch_hex=etch_hex,
        ),
        encoding="utf-8",
    )
    (root / "medusa.json").write_text(_medusa_json(), encoding="utf-8")
    return root, props


def _copy_forge_std(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).resolve().parent / "forge_std_min"
    for name in ("Vm.sol", "Test.sol"):
        src = here / name
        if src.is_file():
            shutil.copy2(src, dest / name)


def _materialize_target_sources(
    root: Path,
    *,
    source: str,
    source_dir: Optional[Path],
) -> list[str]:
    """Place verified sources under src/target and return extra remappings."""
    remaps: list[str] = []
    target_root = root / "src" / "target"
    if source_dir and Path(source_dir).is_dir():
        files = list(Path(source_dir).rglob("*.sol"))[:80]
        if files:
            target_root.mkdir(parents=True, exist_ok=True)
            for f in files:
                rel = f.relative_to(source_dir)
                out = target_root / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(f, out)
                except OSError:
                    continue
            remaps.append("target/=src/target/")
            return remaps

    # Flattened IR form: // ----- file: path -----
    chunks = re.split(r"^// ----- file: (.+?) -----\s*$", source or "", flags=re.M)
    if len(chunks) >= 3:
        target_root.mkdir(parents=True, exist_ok=True)
        # chunks: [preamble, path1, body1, path2, body2, ...]
        for i in range(1, len(chunks) - 1, 2):
            rel = chunks[i].strip().replace("\\", "/")
            body = chunks[i + 1]
            if ".." in rel or not rel.endswith(".sol"):
                continue
            out = target_root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
        remaps.append("target/=src/target/")
    return remaps


def _runtime_hex(bytecode: str) -> str:
    raw = (bytecode or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    raw = "".join(c for c in raw if c in "0123456789abcdef")
    if len(raw) < 4 or len(raw) % 2:
        return ""
    return raw


def _hex40(address: str) -> str:
    """40 lowercase hex digits (no 0x) for Solidity hex\"…\" bytes20 literals."""
    a = (address or "").strip().lower()
    if a.startswith("0x"):
        a = a[2:]
    a = "".join(c for c in a if c in "0123456789abcdef")
    if len(a) != 40:
        a = (a + "0" * 40)[:40]
    return a


_IFACE_SOL = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// Minimal read/write surface for defensive fork properties.
interface IFundsAtRisk {
    function totalAssets() external view returns (uint256);
    function totalSupply() external view returns (uint256);
    function convertToAssets(uint256 shares) external view returns (uint256);
    function convertToShares(uint256 assets) external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function owner() external view returns (address);
    function admin() external view returns (address);
    function paused() external view returns (bool);
    function deposit(uint256 assets, address receiver) external returns (uint256);
    function withdraw(uint256 assets, address receiver, address owner_) external returns (uint256);
    function transferOwnership(address newOwner) external;
    function pause() external;
    function unpause() external;
    function upgradeTo(address newImplementation) external;
}
"""

_MOCK_BOUND_SOL = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// Bound mock used when runtime bytecode is unavailable / too large for etch.
/// Returns conservative values so Halmos can *execute* check_* paths.
contract MockBound {
    uint256 public totalSupply = 1e18;
    uint256 public totalAssets = 1e18;
    address public owner = address(0x1);

    function convertToAssets(uint256 shares) external pure returns (uint256) {
        return shares;
    }
    function convertToShares(uint256 assets) external pure returns (uint256) {
        return assets;
    }
    function balanceOf(address) external pure returns (uint256) {
        return 0;
    }
    function admin() external view returns (address) {
        return owner;
    }
    function transferOwnership(address) external pure {
        revert("denied");
    }
    function pause() external pure {
        revert("denied");
    }
    function upgradeTo(address) external pure {
        revert("denied");
    }
}
"""


def _live_properties_sol(
    address_hex40: str,
    name: str,
    contract_class: str,
    props: list[str],
    *,
    etch_hex: str = "",
) -> str:
    """Generate Foundry/Halmos test contract with vm.etch setUp."""
    prop_comments = "\n".join("/// - %s" % p for p in props)
    if etch_hex:
        setup_body = f"""\
        // Etch runtime bytecode (live or MockBound hex) — Halmos has no createSelectFork/`new`.
        vm.etch(TARGET, hex"{etch_hex}");
        t = IFundsAtRisk(TARGET);
"""
    else:
        setup_body = """\
        // Fork mode: TARGET already has code via --fork-url (Foundry/Medusa).
        t = IFundsAtRisk(TARGET);
"""

    return f"""\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {{Test}} from "forge-std/Test.sol";
import {{IFundsAtRisk}} from "../src/IFundsAtRisk.sol";

/// Defensive live-fork properties for {name} ({contract_class}).
/// Proof of bug on failure — never an attack harness.
/// Auto-generated properties:
{prop_comments}
contract LiveProperties is Test {{
    address constant TARGET = address(bytes20(hex"{address_hex40}"));
    IFundsAtRisk internal t;
    address internal outsider = address(0xBEEF);

    function setUp() public {{
{setup_body}
    }}

    /// Solvency: share claim never exceeds assets (+1 wei rounding).
    function test_solvency_assets_cover_shares() public view {{
        try t.totalSupply() returns (uint256 supply) {{
            try t.totalAssets() returns (uint256 assets) {{
                try t.convertToAssets(supply) returns (uint256 claim) {{
                    assert(claim <= assets + 1);
                }} catch {{}}
            }} catch {{}}
        }} catch {{}}
    }}

    /// Share-price monotonic under a dry convert round-trip (no state change).
    function testFuzz_share_price_round_trip(uint96 assets) public view {{
        if (assets == 0) return;
        try t.convertToShares(uint256(assets)) returns (uint256 shares) {{
            if (shares == 0) return;
            try t.convertToAssets(shares) returns (uint256 back) {{
                if (back > uint256(assets)) {{
                    assert(back - uint256(assets) <= 1);
                }} else {{
                    assert(uint256(assets) - back <= 1 + (uint256(assets) / 1e6));
                }}
            }} catch {{}}
        }} catch {{}}
    }}

    /// Non-owner must not freely take ownership / pause / upgrade.
    function test_access_control_non_owner() public {{
        if (TARGET.code.length == 0) return;

        address own;
        bool hasOwner;
        try t.owner() returns (address o) {{
            own = o;
            hasOwner = true;
        }} catch {{
            try t.admin() returns (address a) {{
                own = a;
                hasOwner = true;
            }} catch {{
                return;
            }}
        }}
        if (!hasOwner) return;
        if (own == address(0) || own == address(this)) return;

        (bool okOwn, ) = TARGET.call(abi.encodeWithSignature("transferOwnership(address)", outsider));
        assert(!okOwn);

        (bool okPause, ) = TARGET.call(abi.encodeWithSignature("pause()"));
        if (okPause) {{
            assert(false);
        }}

        (bool okUp, ) = TARGET.call(
            abi.encodeWithSignature("upgradeTo(address)", outsider)
        );
        if (okUp) {{
            assert(false);
        }}
    }}

    /// Snapshot: calling view convert helpers must not drop an outsider's balance.
    function test_no_third_party_balance_drop() public {{
        uint256 beforeBal;
        bool hasBal;
        try t.balanceOf(outsider) returns (uint256 b) {{
            beforeBal = b;
            hasBal = true;
        }} catch {{
            return;
        }}
        if (!hasBal) return;
        try t.convertToAssets(1) returns (uint256) {{}} catch {{}}
        try t.convertToShares(1) returns (uint256) {{}} catch {{}}
        (bool ok, ) = TARGET.call(
            abi.encodeWithSignature("withdraw(uint256,address,address)", uint256(1), outsider, outsider)
        );
        uint256 afterBal;
        try t.balanceOf(outsider) returns (uint256 a) {{
            afterBal = a;
        }} catch {{
            return;
        }}
        if (afterBal > beforeBal) {{
            uint256 delta = afterBal - beforeBal;
            require(false, string(abi.encodePacked("caller_profit_delta=", _u256(delta))));
        }}
        assert(afterBal == beforeBal);
    }}

    function _u256(uint256 value) internal pure returns (string memory) {{
        if (value == 0) return "0";
        bytes memory buf = new bytes(78);
        uint256 i = 78;
        while (value != 0) {{
            i--;
            buf[i] = bytes1(uint8(48 + value % 10));
            value /= 10;
        }}
        bytes memory out = new bytes(78 - i);
        for (uint256 j = 0; j < out.length; j++) out[j] = buf[i + j];
        return string(out);
    }}

    // Halmos entrypoints (check_*) — same properties, symbolic path.
    function check_solvency_assets_cover_shares() public view {{
        test_solvency_assets_cover_shares();
    }}

    function check_share_price_round_trip(uint96 assets) public view {{
        testFuzz_share_price_round_trip(assets);
    }}

    function check_access_control_non_owner() public {{
        test_access_control_non_owner();
    }}

    function check_no_third_party_balance_drop() public {{
        test_no_third_party_balance_drop();
    }}
}}
"""


def _medusa_json() -> str:
    return """\
{
  "fuzzing": {
    "workers": 0,
    "timeout": 55,
    "testLimit": 200,
    "callSequenceLength": 8,
    "corpusDirectory": "medusa-corpus",
    "targetContracts": ["LiveProperties"],
    "deploymentOrder": ["LiveProperties"],
    "constructorArgs": {},
    "deployerAddress": "0x10000",
    "senderAddresses": ["0x20000", "0x30000"],
    "blockNumberDelayMax": 0,
    "blockTimestampDelayMax": 0
  },
  "compilation": {
    "platform": "crytic-compile",
    "platformConfig": {
      "target": ".",
      "solcVersion": "",
      "exportDirectory": ""
    }
  },
  "slither": { "useSlither": false }
}
"""
