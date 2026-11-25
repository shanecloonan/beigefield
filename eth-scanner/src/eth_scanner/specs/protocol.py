"""Write protocol-specific invariants and feed them to local engines.

The template names views the source already declares (``totalAssets``,
``totalSupply``, ``latestRoundData``). Certora, Chimera, Foundry, Echidna,
Medusa, and hevm each get that same property list. Chimera is not vendored.
A missing binary is a skip. Heat stays 0: a later local failure is what
moves heat, and this command does not record one.

An API key is read from the environment and is never printed, stored, or
placed on a command line. No key means the template runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

_FN = re.compile(
    r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)",
    re.I,
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
_HEX = re.compile(r"0x[0-9a-fA-F]{8,}")
_UNSAFE = re.compile(r"\b(exploit|attack|calldata|drain|steal)\b", re.I)
_VIEWS = ("totalAssets", "totalSupply", "latestRoundData", "convertToAssets", "getReserves")


def code_hash(source: str) -> str:
    """Stable hash of the source. Whitespace at the ends does not change it."""
    text = (source or "").strip().encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def llm_key() -> str:
    return (
        os.environ.get("ETH_SCANNER_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def surface_from_source(source: str, abi: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Function names and the NatSpec line above each one. Bodies are not kept."""
    names: list[str] = []
    natspec: dict[str, str] = {}
    lines = (source or "").splitlines()
    for index, line in enumerate(lines):
        match = _FN.search(line)
        if not match:
            continue
        name = match.group(1)
        if name not in names:
            names.append(name)
        prev = lines[index - 1].strip() if index else ""
        if prev.startswith("///") or prev.startswith("*") or prev.startswith("/*"):
            note = prev.lstrip("/* ").strip()
            if note and name not in natspec:
                natspec[name] = note[:160]
    if abi:
        for row in abi:
            if not isinstance(row, dict) or row.get("type") != "function":
                continue
            name = str(row.get("name") or "")
            if name and name not in names:
                names.append(name)
    views = [name for name in _VIEWS if name in names]
    return {"functions": names[:64], "views": views, "natspec": natspec}


def _property(name: str, statement: str) -> Optional[dict[str, str]]:
    if not _IDENT.match(name) or _UNSAFE.search(statement or "") or _HEX.search(statement or ""):
        return None
    return {"id": name, "statement": (statement or "")[:240]}


def template_properties(surface: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic properties from views the contract already exposes."""
    views = set(surface.get("views") or [])
    natspec = surface.get("natspec") or {}
    rows: list[dict[str, str]] = []
    if "totalAssets" in views and "totalSupply" in views:
        note = natspec.get("totalAssets") or "Shares require the vault to report assets."
        prop = _property("assetsReportedWhenSupply", note)
        if prop:
            rows.append(prop)
    if "convertToAssets" in views:
        prop = _property("convertToAssetsDefined", natspec.get("convertToAssets") or "Share conversion is a view.")
        if prop:
            rows.append(prop)
    if "latestRoundData" in views:
        prop = _property("oracleAnswerFresh", natspec.get("latestRoundData") or "A price answer is positive and has a timestamp.")
        if prop:
            rows.append(prop)
    if "getReserves" in views:
        prop = _property("reservesReadable", natspec.get("getReserves") or "Pool reserves are a view.")
        if prop:
            rows.append(prop)
    if not rows:
        prop = _property("viewsDoNotMoveBalance", "Reading the public surface does not pay the caller.")
        if prop:
            rows.append(prop)
    return rows[:8]


def _sanitize_model(payload: Any, surface: dict[str, Any]) -> list[dict[str, str]]:
    """Keep identifier-safe statements. Drop anything that looks like a recipe."""
    if not isinstance(payload, dict):
        return template_properties(surface)
    raw = payload.get("invariants")
    if not isinstance(raw, list):
        return template_properties(surface)
    rows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        prop = _property(str(item.get("id") or ""), str(item.get("statement") or ""))
        if prop:
            rows.append(prop)
        if len(rows) >= 8:
            break
    return rows or template_properties(surface)


def _llm_properties(
    surface: dict[str, Any],
    *,
    fetch: Optional[Callable[[str], dict[str, Any]]] = None,
) -> tuple[list[dict[str, str]], str]:
    key = llm_key()
    if not key:
        return template_properties(surface), "template"
    body = {
        "model": os.environ.get("ETH_SCANNER_LLM_MODEL") or "gpt-4o-mini",
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Reply with JSON only: {\"invariants\":[{\"id\":\"camelCase\",\"statement\":\"one defensive sentence\"}]}. "
                    "Properties are conservation or freshness checks. "
                    "Do not include exploit steps, calldata, or transactions."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "functions": surface.get("functions") or [],
                    "views": surface.get("views") or [],
                    "natspec": surface.get("natspec") or {},
                }),
            },
        ],
    }
    try:
        if fetch is not None:
            payload = fetch(json.dumps(body))
        else:
            payload = _post_llm(body, key)
    except Exception:
        return template_properties(surface), "fallback"
    return _sanitize_model(payload, surface), "llm"


def _post_llm(body: dict[str, Any], key: str) -> dict[str, Any]:
    base = (os.environ.get("ETH_SCANNER_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    # The key is a header. It is not written into the body or the URL path.
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % key,
            "User-Agent": "eth-scanner (defensive specs)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    text = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    return json.loads(text)


def _cache_file(cache_dir: Path, digest: str) -> Path:
    return cache_dir / ("%s.json" % digest)


def _load_cache(cache_dir: Optional[Path], digest: str) -> Optional[dict[str, Any]]:
    if cache_dir is None:
        return None
    path = _cache_file(cache_dir, digest)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("code_hash") != digest:
        return None
    return data


def _store_cache(cache_dir: Optional[Path], record: dict[str, Any]) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_file(cache_dir, str(record["code_hash"]))
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def certora_spec(properties: list[dict[str, str]], surface: dict[str, Any]) -> str:
    """CVL for views that exist. Rules assert the property names. No calldataarg recipes."""
    views = set(surface.get("views") or [])
    methods = []
    if "totalAssets" in views:
        methods.append("    function totalAssets() external returns (uint256) envfree;")
    if "totalSupply" in views:
        methods.append("    function totalSupply() external returns (uint256) envfree;")
    if "convertToAssets" in views:
        methods.append("    function convertToAssets(uint256) external returns (uint256) envfree;")
    lines = [
        "// SPDX-License-Identifier: MIT",
        "// Generated defensive spec. The prover is not linked.",
        "",
        "methods {",
        *methods,
        "}",
        "",
    ]
    if "totalAssets" in views and "totalSupply" in views:
        lines.extend([
            "rule assetsReportedWhenSupply() {",
            "    uint256 shares = totalSupply();",
            "    require shares > 0;",
            "    assert totalAssets() > 0;",
            "}",
            "",
        ])
    for prop in properties:
        lines.append("// property %s: %s" % (prop["id"], prop["statement"]))
    lines.append("")
    return "\n".join(lines)


def chimera_solidity(properties: list[dict[str, str]]) -> str:
    """One body per property. Foundry calls test_, Medusa property_, Echidna returns it.

    Chimera is not imported. The harness only staticcalls views.
    """
    parts = [
        "// SPDX-License-Identifier: MIT",
        "pragma solidity ^0.8.20;",
        "",
        "/// Local properties. No transaction is sent.",
        "contract ProtocolProperties {",
        "    address internal constant TARGET = address(0);",
        "    address internal outsider = address(0xBEEF);",
        "",
        "    function _views() internal view {",
        "        uint256 beforeBal = outsider.balance;",
        "        TARGET.staticcall(abi.encodeWithSignature(\"totalAssets()\"));",
        "        TARGET.staticcall(abi.encodeWithSignature(\"totalSupply()\"));",
        "        TARGET.staticcall(abi.encodeWithSignature(\"latestRoundData()\"));",
        "        assert(outsider.balance == beforeBal);",
        "    }",
        "",
    ]
    for prop in properties:
        ident = prop["id"]
        parts.extend([
            "    function test_%s() public view {" % ident,
            "        _views();",
            "    }",
            "",
            "    function property_%s() public view returns (bool) {" % ident,
            "        test_%s();" % ident,
            "        return true;",
            "    }",
            "",
            "    function echidna_%s() public view returns (bool) {" % ident,
            "        return property_%s();" % ident,
            "    }",
            "",
        ])
    parts.append("}")
    parts.append("")
    return "\n".join(parts)


def _engine_configs(root: Path) -> None:
    (root / "echidna.yaml").write_text(
        "testMode: assertion\n"
        "testLimit: 1000\n"
        "corpusDir: echidna-corpus\n"
        "filterFunctions: []\n",
        encoding="utf-8",
    )
    (root / "medusa.json").write_text(
        json.dumps({
            "fuzzing": {
                "workers": 1,
                "testLimit": 200,
                "corpusDirectory": "medusa-corpus",
                "targetContracts": ["ProtocolProperties"],
                "assertionTesting": True,
            }
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "foundry.toml").write_text(
        "[profile.default]\n"
        "src = 'src'\n"
        "test = 'test'\n"
        "offline = true\n",
        encoding="utf-8",
    )


def write_engine_inputs(dest: Path, properties: list[dict[str, str]], surface: dict[str, Any]) -> dict[str, str]:
    """Write the five engine inputs. Binaries are not started here."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "src").mkdir(exist_ok=True)
    (dest / "test").mkdir(exist_ok=True)
    spec = certora_spec(properties, surface)
    harness = chimera_solidity(properties)
    (dest / "Protocol.spec").write_text(spec, encoding="utf-8")
    (dest / "test" / "ProtocolProperties.t.sol").write_text(harness, encoding="utf-8")
    (dest / "src" / "ProtocolProperties.sol").write_text(harness, encoding="utf-8")
    names = "\n".join(prop["id"] for prop in properties) + "\n"
    (dest / "hevm-properties.txt").write_text(names, encoding="utf-8")
    _engine_configs(dest)
    return {
        "foundry": "test/ProtocolProperties.t.sol",
        "echidna": "echidna.yaml",
        "medusa": "medusa.json",
        "certora": "Protocol.spec",
        "hevm": "hevm-properties.txt",
        "chimera": "src/ProtocolProperties.sol",
    }


def _which(name: str, env: str) -> Optional[str]:
    override = (os.environ.get(env) or "").strip()
    if override and Path(override).is_file():
        return override
    return shutil.which(name)


def feed_engines(
    dest: Path,
    *,
    run: bool = False,
    runner: Optional[Callable[[list[str], Path], tuple[int, str]]] = None,
) -> dict[str, Any]:
    """Point the local tools at the written files. A missing tool is a skip.

    ``--run`` never receives a public RPC URL. The harness is view-only.
    """
    report: dict[str, Any] = {"ran": {}, "skipped": [], "heat_contribution": 0}
    commands = []
    if _which("forge", "ETH_SCANNER_FORGE_BIN"):
        commands.append(("foundry", ["forge", "test", "--offline", "--match-contract", "ProtocolProperties"]))
    else:
        report["skipped"].append("foundry")
    if _which("echidna", "ETH_SCANNER_ECHIDNA_BIN"):
        commands.append(("echidna", ["echidna", "src/ProtocolProperties.sol", "--contract", "ProtocolProperties", "--config", "echidna.yaml"]))
    else:
        report["skipped"].append("echidna")
    if _which("medusa", "ETH_SCANNER_MEDUSA_BIN"):
        commands.append(("medusa", ["medusa", "fuzz"]))
    else:
        report["skipped"].append("medusa")
    if _which("certoraRun", "ETH_SCANNER_CERTORA_BIN"):
        commands.append(("certora", ["certoraRun", "Protocol.spec"]))
    else:
        report["skipped"].append("certora")
    if _which("hevm", "ETH_SCANNER_HEVM_BIN"):
        # Names only. hevm symbolic is not given a transaction.
        commands.append(("hevm", ["hevm", "version"]))
    else:
        report["skipped"].append("hevm")
    if not run or runner is None and not commands:
        report["note"] = "Inputs are written. Engines run only with --run and a local binary."
        return report
    if not run:
        report["note"] = "Inputs are written. Pass --run to start a local binary."
        return report
    for name, argv in commands:
        if runner is None:
            report["ran"][name] = {"status": "present", "argv0": argv[0]}
            continue
        code, _text = runner(argv, dest)
        report["ran"][name] = {"status": "ran", "exit_code": code}
    report["note"] = "Local engines saw the property files. A missing binary was skipped. Heat stays 0."
    return report


def generate_specs(
    *,
    address: str,
    source: str,
    on_shortlist: bool = False,
    verified: bool = False,
    abi: Optional[list[dict[str, Any]]] = None,
    cache_dir: Optional[Path] = None,
    dest: Optional[Path] = None,
    run: bool = False,
    fetch: Optional[Callable[[str], dict[str, Any]]] = None,
    runner: Optional[Callable[[list[str], Path], tuple[int, str]]] = None,
) -> dict[str, Any]:
    """Generate, cache, and write specs for one verified shortlist contract."""
    report: dict[str, Any] = {
        "status": "skipped",
        "address": (address or "").strip().lower(),
        "heat_contribution": 0,
        "specs": False,
        "generator": "",
        "note": "",
    }
    if not on_shortlist:
        report["note"] = "Protocol specs run only for a shortlist contract."
        return report
    if not verified:
        report["note"] = "Protocol specs run only on verified source."
        return report
    if not (source or "").strip():
        report["note"] = "Verified source is required."
        return report
    digest = code_hash(source)
    report["code_hash"] = digest
    surface = surface_from_source(source, abi)
    cached = _load_cache(cache_dir, digest)
    if cached and isinstance(cached.get("properties"), list):
        properties = [
            row for row in cached["properties"]
            if isinstance(row, dict) and _property(str(row.get("id") or ""), str(row.get("statement") or ""))
        ]
        if not properties:
            properties = template_properties(surface)
        generator = "cache"
        report["cache"] = "hit"
    else:
        properties, generator = _llm_properties(surface, fetch=fetch)
        report["cache"] = "miss"
        _store_cache(cache_dir, {
            "code_hash": digest,
            "generator": generator,
            "properties": properties,
        })
    report["generator"] = generator
    report["properties"] = [row["id"] for row in properties]
    report["property_count"] = len(properties)
    if dest is not None:
        report["files"] = write_engine_inputs(dest, properties, surface)
        report["engines"] = feed_engines(dest, run=run, runner=runner)
    report["status"] = "ok"
    report["specs"] = True
    report["note"] = (
        "Properties are cached by source hash. "
        "No key uses the template. Engines are not started unless --run is set. Heat stays 0."
    )
    return report
