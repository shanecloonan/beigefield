"""Read-only Solana program configuration and source notes.

The RPC reads are getAccountInfo only. OtterSec's public verify endpoint
says whether a build is verified. Local Rust is scanned only when a path
is passed in. cargo-audit, clippy, and Soteria run only when asked and
the binary is already installed. Nothing here adds heat or sends a
transaction.
"""

from __future__ import annotations

import base64
import json
import shutil
import struct
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.chains.registry import normalize_solana_address
from eth_scanner.chains.solana_discover import RpcLimited, _rpc_call, rpc_url

UPGRADEABLE = "BPFLoaderUpgradeab1e11111111111111111111111"
LOADER_V2 = "BPFLoader2111111111111111111111111111111111"
LOADER_V1 = "BPFLoader1111111111111111111111111111111111"
MULTISIG_OWNERS = {
    "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf": "squads-v4",
    "GovER5Lthms3bLBqWub97yVrMmEogzX7xNjdXpPPCVZw": "spl-governance",
}
OTTER_STATUS = "https://verify.osec.io/status/{address}"

Rpc = Callable[[str, list[Any]], Any]
Fetch = Callable[[str], Any]


def inspect_program(
    address: str,
    *,
    rpc: Optional[Rpc] = None,
    fetch: Optional[Fetch] = None,
    source: Optional[str] = None,
    run_tools: bool = False,
) -> dict[str, Any]:
    """Configuration facts for one program. heat_contribution is 0."""
    program = normalize_solana_address(address)
    url, label = rpc_url()
    caller = rpc if rpc is not None else (lambda method, params: _rpc_call(url, method, params))
    report: dict[str, Any] = {
        "chain": "solana",
        "address": program,
        "heat_contribution": 0,
        "executable": None,
        "immutable": None,
        "upgrade_authority": None,
        "authority_kind": "unknown",
        "verified": None,
        "source_url": None,
        "idl": "not-derived",
        "rpc": label if rpc is None else "injected",
        "degraded": False,
        "findings": [],
        "evidence": [],
        "note": "Configuration and source notes. This stage adds no heat.",
    }
    try:
        _read_loader(report, caller)
    except RpcLimited:
        report["degraded"] = True
        report["authority_kind"] = "unknown"
        report["rpc_note"] = "RPC rate limited; configuration left unknown"
    except Exception as exc:  # noqa: BLE001
        report["degraded"] = True
        report["authority_kind"] = "unknown"
        report["rpc_note"] = "RPC read failed; configuration left unknown"
        report["rpc_error"] = type(exc).__name__
    try:
        _read_verify(report, fetch)
    except Exception as exc:  # noqa: BLE001
        report["verified"] = None
        report["verify_note"] = "verify endpoint unavailable"
        report["verify_error"] = type(exc).__name__
    if source:
        report["findings"] = scan_source(source)
        if run_tools:
            report["tools"] = run_installed_tools(source)
        else:
            report["tools"] = {"ran": False, "note": "external tools stay off unless --tools is set"}
    report["heat_contribution"] = 0
    return report


def scan_source(path_or_text: str) -> list[dict[str, Any]]:
    """Pattern notes on local Rust. Each one contributes 0 heat."""
    from pathlib import Path

    text = path_or_text
    candidate = Path(path_or_text)
    if candidate.exists() and candidate.is_dir():
        chunks = []
        for file in sorted(candidate.rglob("*.rs"))[:40]:
            try:
                chunks.append(file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        text = "\n".join(chunks)
    elif candidate.exists() and candidate.is_file():
        text = candidate.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    findings = []

    def add(rule: str, detail: str) -> None:
        findings.append({
            "rule": rule,
            "detail": detail,
            "severity": "low",
            "defensive_only": True,
            "heat_contribution": 0,
        })

    if "invoke(" in lowered or "invoke_signed(" in lowered:
        if "is_signer" not in lowered:
            add("missing-signer-check", "A CPI helper is present and this source never reads is_signer.")
        if "remaining_accounts" in lowered:
            add("arbitrary-cpi", "remaining_accounts is in scope next to a CPI helper.")
    if "accountinfo" in lowered and "owner" not in lowered:
        add("missing-owner-check", "AccountInfo is used and this source never mentions owner.")
    if "unchecked_" in lowered or "wrapping_add" in lowered or "wrapping_mul" in lowered:
        add("unchecked-math", "Unchecked or wrapping integer math is present.")
    if ("find_program_address" in lowered or "create_program_address" in lowered) and "bump" not in lowered:
        add("pda-bump", "A PDA helper is present and this source never mentions bump.")
    return findings


def run_installed_tools(path: str) -> dict[str, Any]:
    """Run a tool only when it is already on PATH. Never installs one."""
    import subprocess
    from pathlib import Path

    root = Path(path)
    folder = root if root.is_dir() else root.parent
    out: dict[str, Any] = {"crate": (folder / "Cargo.toml").exists()}
    if shutil.which("cargo-audit") and (folder / "Cargo.lock").exists():
        out["cargo-audit"] = _command(["cargo", "audit", "--json"], folder, subprocess)
    else:
        out["cargo-audit"] = {"skipped": "not installed" if not shutil.which("cargo-audit") else "no Cargo.lock"}
    if shutil.which("cargo") and out["crate"]:
        out["clippy"] = _command(
            ["cargo", "clippy", "--offline", "--message-format=short", "-q"],
            folder,
            subprocess,
        )
    else:
        out["clippy"] = {"skipped": "not installed" if not shutil.which("cargo") else "no Cargo.toml"}
    if shutil.which("soteria"):
        out["soteria"] = {"skipped": "binary present; no pinned local invocation in this pass"}
    else:
        out["soteria"] = {"skipped": "not installed"}
    return out


def _command(argv: list[str], folder: Any, subprocess: Any) -> dict[str, Any]:
    try:
        done = subprocess.run(
            argv,
            cwd=str(folder),
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"skipped": type(exc).__name__}
    text = (done.stdout or "") + (done.stderr or "")
    return {"returncode": done.returncode, "excerpt": text[:500], "heat_contribution": 0}


def _read_loader(report: dict[str, Any], rpc: Rpc) -> None:
    info = _account(rpc, report["address"])
    if not info:
        report["executable"] = False
        report["authority_kind"] = "missing"
        report["evidence"].append({"source": "getAccountInfo", "present": False})
        return
    report["executable"] = bool(info.get("executable"))
    owner = str(info.get("owner") or "")
    report["owner"] = owner
    raw = _data_bytes(info.get("data"))
    report["evidence"].append({
        "source": "getAccountInfo",
        "executable": report["executable"],
        "owner": owner,
        "data_len": len(raw),
    })
    if owner == LOADER_V2 or owner == LOADER_V1:
        report["immutable"] = True
        report["authority_kind"] = "immutable"
        report["upgrade_authority"] = None
        return
    if owner != UPGRADEABLE or len(raw) < 36:
        report["authority_kind"] = "unknown"
        return
    tag = struct.unpack_from("<I", raw, 0)[0]
    if tag != 2:
        report["authority_kind"] = "unknown"
        return
    programdata = _b58(raw[4:36])
    report["programdata"] = programdata
    pdata = _account(rpc, programdata)
    blob = _data_bytes((pdata or {}).get("data"))
    # ProgramData metadata is 45 bytes: u32 tag, u64 slot, u8 option, 32-byte key.
    # The key is present and zeroed when the program is immutable.
    if len(blob) < 45:
        report["authority_kind"] = "unknown"
        report["degraded"] = True
        return
    if struct.unpack_from("<I", blob, 0)[0] != 3:
        report["authority_kind"] = "unknown"
        return
    option = blob[12]
    if option == 0:
        report["immutable"] = True
        report["authority_kind"] = "immutable"
        report["upgrade_authority"] = None
        report["evidence"].append({"source": "programdata", "upgrade_authority": None})
        return
    if option != 1:
        report["authority_kind"] = "unknown"
        return
    authority = _b58(blob[13:45])
    report["immutable"] = False
    report["upgrade_authority"] = authority
    auth_account = _account(rpc, authority)
    auth_owner = str((auth_account or {}).get("owner") or "")
    if not auth_account:
        # A missing account is a bare key. An RPC error is handled above and stays unknown.
        kind = "single-key"
        report["authority_account"] = "absent"
    else:
        kind = MULTISIG_OWNERS.get(auth_owner, "single-key")
        report["authority_account"] = "present"
    report["authority_kind"] = kind
    report["authority_owner"] = auth_owner or None
    report["evidence"].append({
        "source": "programdata",
        "upgrade_authority": authority,
        "authority_owner": auth_owner or None,
        "authority_kind": kind,
    })


def _read_verify(report: dict[str, Any], fetch: Optional[Fetch]) -> None:
    url = OTTER_STATUS.format(address=report["address"])
    if fetch is not None:
        payload = fetch(url)
    else:
        payload = _http_json(url)
    if not isinstance(payload, dict):
        report["verified"] = None
        return
    verified = payload.get("is_verified")
    if verified is None:
        verified = payload.get("verified")
    report["verified"] = bool(verified) if verified is not None else None
    repo = payload.get("repo_url") or payload.get("repo")
    report["source_url"] = str(repo) if repo else None
    report["evidence"].append({
        "source": "ottersec-verify",
        "verified": report["verified"],
        "source_url": report["source_url"],
    })


def _account(rpc: Rpc, address: str) -> Optional[dict[str, Any]]:
    payload = rpc("getAccountInfo", [address, {"encoding": "base64"}])
    if isinstance(payload, dict) and "value" in payload:
        value = payload.get("value")
    elif isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        value = payload["result"].get("value")
    else:
        value = payload
    return value if isinstance(value, dict) else None


def _data_bytes(data: Any) -> bytes:
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except Exception:  # noqa: BLE001
            return b""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return b""


def _b58(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(raw, "big")
    chars = []
    while number:
        number, rem = divmod(number, 58)
        chars.append(alphabet[rem])
    pad = 0
    for byte in raw:
        if byte != 0:
            break
        pad += 1
    return "1" * pad + "".join(reversed(chars or ["1"]))


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "beigefield-scanner"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))
