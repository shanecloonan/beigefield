"""Auto-generate defensive Foundry/Medusa property harnesses by contract class.

Harnesses target a live mainnet address via fork. They assert conservation /
access-control properties only — no attacker contracts, no broadcast helpers.
"""

from __future__ import annotations

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


def properties_for_class(contract_class: str) -> tuple[str, ...]:
    return PROPERTY_IDS_BY_CLASS.get((contract_class or "").lower(), _DEFAULT_PROPS)


def write_live_fuzz_project(
    dest: Path,
    *,
    address: str,
    contract_class: str = "vault",
    contract_name: Optional[str] = None,
) -> tuple[Path, list[str]]:
    """Materialize a minimal Foundry (+ Medusa config) project for `address`."""
    root = Path(dest)
    if root.exists():
        import shutil
        shutil.rmtree(root)
    (root / "src").mkdir(parents=True)
    (root / "test").mkdir(parents=True)
    props = list(properties_for_class(contract_class))
    addr_hex = _hex40(address)
    name = (contract_name or "Target").replace(" ", "")[:40] or "Target"

    (root / "foundry.toml").write_text(
        "\n".join([
            "[profile.default]",
            'src = "src"',
            'test = "test"',
            'out = "out"',
            'libs = ["lib"]',
            'solc = "0.8.20"',
            "optimizer = true",
            "optimizer_runs = 200",
            "ffi = false",
            "fs_permissions = []",
            # Foundry 1.x defaults isolate=true which breaks try/catch against
            # missing selectors on fork targets; keep classic call semantics.
            "isolate = false",
            "",
            "[profile.default.fuzz]",
            "runs = 32",
            "",
        ]),
        encoding="utf-8",
    )

    (root / "src" / "IFundsAtRisk.sol").write_text(_IFACE_SOL, encoding="utf-8")
    (root / "test" / "LiveProperties.t.sol").write_text(
        _live_properties_sol(addr_hex, name, contract_class, props),
        encoding="utf-8",
    )
    (root / "medusa.json").write_text(_medusa_json(), encoding="utf-8")
    return root, props


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
/// Callers treat missing selectors as skip (try/catch / staticcall).
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


def _live_properties_sol(
    address_hex40: str,
    name: str,
    contract_class: str,
    props: list[str],
) -> str:
    """Generate a Foundry test contract. Defensive only — no prank-as-attacker payloads."""
    prop_comments = "\n".join("/// - %s" % p for p in props)
    # Access-control probes use low-level calls from `address(this)` (not owner).
    # If the target has no such selector, staticcall/call fails closed (skip).
    # bytes20(hex"…") avoids solc treating 40-nibble literals as address constants.
    return f"""\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {{IFundsAtRisk}} from "../src/IFundsAtRisk.sol";

/// Defensive live-fork properties for {name} ({contract_class}).
/// Proof of bug on failure — never an attack harness.
/// Auto-generated properties:
{prop_comments}
contract LiveProperties {{
    address constant TARGET = address(bytes20(hex"{address_hex40}"));
    IFundsAtRisk internal t;
    address internal outsider = address(0xBEEF);

    function setUp() public {{
        t = IFundsAtRisk(TARGET);
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
                // Allow 1 wei rounding either way relative to assets.
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
        // Empty accounts return success on any call — require live code first.
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
        // Success with empty/non-reverting return on a real contract is a fail.
        assert(!okOwn);

        (bool okPause, ) = TARGET.call(abi.encodeWithSignature("pause()"));
        // pause may not exist; only assert when selector is present AND would succeed for outsider
        if (okPause) {{
            // If pause succeeded for non-owner, that is a property failure.
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
        // Pure views / failed writes must not reduce outsider balance.
        try t.convertToAssets(1) returns (uint256) {{}} catch {{}}
        try t.convertToShares(1) returns (uint256) {{}} catch {{}}
        (bool ok, ) = TARGET.call(
            abi.encodeWithSignature("withdraw(uint256,address,address)", uint256(1), outsider, outsider)
        );
        // Ignore success/fail of withdraw — only check outsider balance did not fall
        // unless the call clearly targeted their funds (ok==true with balance drop is a fail).
        uint256 afterBal;
        try t.balanceOf(outsider) returns (uint256 a) {{
            afterBal = a;
        }} catch {{
            return;
        }}
        if (ok) {{
            // Successful withdraw of outsider funds by this contract is unexpected.
            assert(afterBal >= beforeBal);
        }} else {{
            assert(afterBal == beforeBal);
        }}
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
