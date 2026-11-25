"""Run the AGPL ERC-4626 suites as external checkouts.

The property bodies stay in the submodules under ``eth-scanner/external``.
This module writes a thin MIT adapter and a fuzzer config into the work
directory. It does not copy, import, or vendor the suite source.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

PINS: dict[str, dict[str, str]] = {
    "erc4626-tests": {
        "url": "https://github.com/a16z/erc4626-tests",
        "commit": "ac485460e014f22807c1ff687e0b4dc3af96ee40",
        "license": "AGPL-3.0",
        "marker": "ERC4626.test.sol",
    },
    "crytic-properties": {
        "url": "https://github.com/crytic/properties",
        "commit": "5ea14b813ff296e24b4257ab52a0402360f916f6",
        "license": "AGPL-3.0",
        "marker": "contracts/ERC4626/ERC4626PropertyTests.sol",
    },
}

CRYTIC_CONTRACT = "CryticERC4626PropertyTests"
FORGE_TIMEOUT_S = 40
FUZZ_TIMEOUT_S = 20
_ENV = {
    "erc4626-tests": "ETH_SCANNER_ERC4626_DIR",
    "crytic-properties": "ETH_SCANNER_CRYTIC_DIR",
}
_FAIL = re.compile(
    r"\[FAIL[^\]]*\]\s*(?:[A-Za-z0-9_.]*\.)?((?:test_|prop_|echidna_|property_)[A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_HEX = re.compile(r"0x[0-9a-fA-F]{8,}")
Runner = Callable[[list[str], Path, int], tuple[int, str]]


def pins() -> dict[str, dict[str, str]]:
    return {name: dict(row) for name, row in PINS.items()}


def looks_like_erc4626(contract_class: str = "", source: str = "") -> bool:
    blob = "%s\n%s" % (contract_class or "", source or "")
    low = blob.lower()
    if "4626" in low:
        return True
    return "totalassets" in low and "deposit" in low


def suite_root(name: str, override: Optional[Path] = None) -> Optional[Path]:
    """Return a checkout that contains the pinned marker, or None."""
    pin = PINS.get(name)
    if pin is None:
        return None
    candidates: list[Path] = []
    if override is not None:
        candidates.append(Path(override))
    env = os.environ.get(_ENV[name], "").strip()
    if env:
        candidates.append(Path(env))
    bundled = Path(__file__).resolve().parents[3] / "external" / name
    candidates.append(bundled)
    marker = pin["marker"]
    for root in candidates:
        if (root / marker).is_file():
            return root
    return None


def _address(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise ValueError("address must be 20 bytes of hex")
    return "0x" + raw


def harness_source(vault: str, asset: str) -> str:
    """MIT adapter. The inherited property bodies stay in the external suite."""
    vault = _address(vault)
    asset = _address(asset)
    return "\n".join([
        "// SPDX-License-Identifier: MIT",
        "pragma solidity ^0.8.20;",
        "",
        'import "erc4626-tests/ERC4626.test.sol";',
        "",
        "/// Points the external suite at one vault. Property bodies are not copied.",
        "contract ThinFork4626 is ERC4626Test {",
        "    function setUp() public override {",
        "        _vault_ = %s;" % vault,
        "        _underlying_ = %s;" % asset,
        "        _delta_ = 0;",
        "        _vaultMayBeEmpty = true;",
        "        _unlimitedAmount = false;",
        "        _skipRoundTripShares = false;",
        "    }",
        "}",
        "",
    ])


def parse_property_failures(text: str, *, source: str) -> list[dict[str, str]]:
    """Keep the property name. Drop calldata and any other long hex."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _FAIL.finditer(text or ""):
        name = match.group(1)[:80]
        low = name.lower()
        if "setup" in low or "constructor" in low:
            continue
        if name in seen:
            continue
        seen.add(name)
        rows.append({
            "id": name,
            "status": "failed",
            "source": source,
            "evidence": "external property failed",
        })
        if len(rows) >= 8:
            break
    return rows


def _local_fork(url: str) -> bool:
    from eth_scanner.deep.blend.ityfuzz_runner import local_rpc
    return bool(url) and local_rpc(url)


def _default_runner(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, _HEX.sub("0x…", text)[:4000]


def _property_files(root: Path) -> list[str]:
    folder = root / "contracts" / "ERC4626" / "properties"
    if not folder.is_dir():
        return []
    names = [
        path.stem
        for path in sorted(folder.glob("*.sol"))
        if path.stem != "VaultProxy"
    ]
    return names


def _write_crytic_config(dest: Path, root: Path) -> dict[str, Any]:
    dest.mkdir(parents=True, exist_ok=True)
    target = str(root.resolve())
    medusa = {
        "fuzzing": {
            "workers": 1,
            "timeout": FUZZ_TIMEOUT_S,
            "testLimit": 50,
            "callSequenceLength": 20,
            "targetContracts": [CRYTIC_CONTRACT],
            "corpusDir": "corpus",
            "testing": {
                "stopOnFailedTest": True,
                "assertionTesting": {"enabled": True, "testViewMethods": False},
                "propertyTesting": {"enabled": True, "testPrefixes": ["verify_", "property_"]},
            },
        },
        "compilation": {
            "platform": "crytic-compile",
            "platformConfig": {"target": target, "args": []},
        },
    }
    echidna = "\n".join([
        "testMode: assertion",
        "testLimit: 50",
        "timeout: %d" % FUZZ_TIMEOUT_S,
        "workers: 1",
        "corpusDir: corpus",
        "# target %s in %s" % (CRYTIC_CONTRACT, target),
        "",
    ])
    (dest / "medusa.json").write_text(json.dumps(medusa, indent=2) + "\n", encoding="utf-8")
    (dest / "echidna.yaml").write_text(echidna, encoding="utf-8")
    (dest / "properties.txt").write_text(
        "\n".join(_property_files(root)) + "\n",
        encoding="utf-8",
    )
    return medusa


def _write_harness(dest: Path, suite: Path, vault: str, asset: str) -> Path:
    project = dest / "erc4626"
    (project / "test").mkdir(parents=True, exist_ok=True)
    harness = project / "test" / "ThinFork4626.t.sol"
    harness.write_text(harness_source(vault, asset), encoding="utf-8")
    forge_std = Path(__file__).resolve().parents[1] / "engines" / "forge_std_min"
    remappings = [
        "erc4626-tests/=%s/" % suite.resolve().as_posix(),
        "forge-std/=%s/" % forge_std.resolve().as_posix(),
    ]
    foundry = "\n".join([
        "[profile.default]",
        'src = "src"',
        'test = "test"',
        'out = "out"',
        'solc = "0.8.20"',
        "ffi = false",
        "remappings = [%s]" % ", ".join('"%s"' % row for row in remappings),
        "",
    ])
    (project / "foundry.toml").write_text(foundry, encoding="utf-8")
    return harness


def prepare_external_suites(
    *,
    vault: str,
    asset: str = "",
    dest: Path,
    fork_url: str = "",
    run: bool = False,
    contract_class: str = "",
    source: str = "",
    roots: Optional[dict[str, Optional[Path]]] = None,
    runner: Optional[Runner] = None,
) -> dict[str, Any]:
    """Write the adapter and the fuzzer config. Run only on a local fork."""
    from eth_scanner.heat import evidence_heat

    report: dict[str, Any] = {
        "status": "skipped",
        "vault": "",
        "asset": "",
        "erc4626": False,
        "crytic": False,
        "harness": "",
        "config_dir": "",
        "properties": [],
        "results": [],
        "fuzz_results": [],
        "heat": 0,
        "heat_contribution": 0,
        "note": "",
        "pins": pins(),
    }
    if (contract_class or source) and not looks_like_erc4626(contract_class, source):
        report["note"] = "Not an ERC-4626 vault. The external suites were not run."
        return report
    try:
        vault_addr = _address(vault)
    except ValueError:
        report["status"] = "invalid"
        report["note"] = "Vault address is not 20 bytes of hex."
        return report
    report["vault"] = vault_addr
    if not asset:
        report["status"] = "needs-asset"
        report["note"] = "The asset address is required before the fork harness is written."
        return report
    try:
        asset_addr = _address(asset)
    except ValueError:
        report["status"] = "invalid"
        report["note"] = "Asset address is not 20 bytes of hex."
        return report
    report["asset"] = asset_addr

    if run and not _local_fork(fork_url):
        report["status"] = "refused"
        report["note"] = "A run needs a local anvil fork. No public RPC was contacted."
        return report

    chosen = roots or {}
    erc = chosen.get("erc4626-tests", suite_root("erc4626-tests"))
    crytic = chosen.get("crytic-properties", suite_root("crytic-properties"))
    if erc is None and crytic is None:
        report["note"] = "Neither external suite is checked out."
        return report

    dest = Path(dest)
    failures: list[dict[str, str]] = []
    if erc is not None:
        harness = _write_harness(dest, erc, vault_addr, asset_addr)
        report["erc4626"] = True
        report["harness"] = str(harness)
        report["status"] = "planned"
        if run:
            forge = shutil.which("forge")
            if runner is None and forge is None:
                report["note"] = "forge is not installed. The harness was written and not run."
            else:
                code, text = (runner or _default_runner)(
                    [forge or "forge", "test", "--match-contract", "ThinFork4626",
                     "--fuzz-runs", "16", "--fork-url", fork_url],
                    harness.parent.parent,
                    FORGE_TIMEOUT_S,
                )
                failures = parse_property_failures(text, source="fork-simulation")
                report["results"] = failures
                report["status"] = "failed" if failures else ("ran" if code == 0 else "forge-failed")
    if crytic is not None:
        config = dest / "crytic"
        medusa = _write_crytic_config(config, crytic)
        report["crytic"] = True
        report["config_dir"] = str(config)
        report["properties"] = list(medusa["fuzzing"]["targetContracts"])
        report["property_files"] = _property_files(crytic)
        if report["status"] == "skipped":
            report["status"] = "planned"
        if run:
            fuzz_notes = _run_fuzzers(crytic, config, runner)
            report["fuzz_results"] = fuzz_notes
    if not report["note"]:
        report["note"] = (
            "External suites stay in their own checkouts. "
            "A local fork property failure is invariant heat. Fuzzer output is not."
        )
    heat, breakdown = evidence_heat(
        funds_usd=None,
        invariant_results=failures,
        external_suite=report,
    )
    report["heat"] = heat
    report["heat_breakdown"] = {
        "erc4626_suite": breakdown.get("erc4626_suite"),
        "crytic_properties": breakdown.get("crytic_properties"),
        "invariants_failed": breakdown.get("invariants_failed"),
        "total": breakdown.get("total"),
    }
    return report


def _run_fuzzers(
    root: Path,
    config: Path,
    runner: Optional[Runner],
) -> list[dict[str, str]]:
    """Medusa and Echidna, time-boxed, against the external contract name."""
    rows: list[dict[str, str]] = []
    call = runner or _default_runner
    medusa = shutil.which("medusa")
    if medusa:
        _code, text = call(
            [medusa, "fuzz", "--config", str(config / "medusa.json")],
            root,
            FUZZ_TIMEOUT_S,
        )
        rows.extend(parse_property_failures(text, source="fuzz"))
    echidna = shutil.which("echidna")
    if echidna:
        _code, text = call(
            [echidna, str(root / "contracts" / "ERC4626" / "ERC4626PropertyTests.sol"),
             "--contract", CRYTIC_CONTRACT,
             "--config", str(config / "echidna.yaml")],
            root,
            FUZZ_TIMEOUT_S,
        )
        rows.extend(parse_property_failures(text, source="fuzz"))
    return rows[:8]
