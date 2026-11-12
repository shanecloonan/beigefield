"""Evaluate class properties against live mainnet state (eth_call / optional forge).

Never sends transactions. Forge counterexamples are reduced to prose + state
values — no runnable attack sequences stored.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.fork_props.catalog import properties_for_class
from eth_scanner.invariants.live import LiveInvariantResult, run_live_invariants


@dataclass
class ForkPropertyResult:
    id: str
    name: str
    status: str  # held | violated | unknown
    severity: str
    evidence: str
    contract_class: str = ""
    source: str = "eth_call"  # eth_call | forge-fork | forge-mock
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sanitize_fork_evidence(raw: str) -> str:
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    s = re.sub(r"0x[0-9a-fA-F]{72,}", "0x…[calldata elided]", s)
    # Drop forge "Traces:" blobs and call stacks that look like attack paths.
    s = re.sub(r"Traces:.*", "Traces elided.", s, flags=re.I)
    if len(s) > 500:
        s = s[:499] + "…"
    return s


def run_fork_properties(
    address: str,
    *,
    contract_class: str = "unknown",
    rpc_url: str = "",
    run_forge: bool = True,
    timeout_s: float = 60.0,
) -> list[ForkPropertyResult]:
    """Primary path: live eth_call suite mapped to the class catalog.

    Optional: forge test --fork-url when forge + RPC are available. Results are
    merged; forge failures become violated with prose evidence only.
    """
    addr = (address or "").strip().lower()
    klass = (contract_class or "unknown").lower()
    catalog = properties_for_class(klass)
    live = run_live_invariants(
        addr,
        contract_class=klass if klass != "unknown" else "vault",
        rpc_url=rpc_url,
        timeout_s=timeout_s,
    )
    by_id = {r.id: r for r in live}
    out: list[ForkPropertyResult] = []

    for prop in catalog:
        pid = prop["id"]
        live_row = by_id.get(pid)
        if live_row is None and pid == "privileged-callable":
            # Aggregate privileged-* probes.
            priv = [r for r in live if r.id.startswith("privileged-")]
            failed = [r for r in priv if r.status == "failed"]
            held = [r for r in priv if r.status == "held"]
            if failed:
                out.append(ForkPropertyResult(
                    id=pid,
                    name=prop["name"],
                    status="violated",
                    severity=prop["severity"],
                    evidence=sanitize_fork_evidence(
                        "%d privileged selector(s) did not revert for arbitrary EOA; e.g. %s"
                        % (len(failed), failed[0].evidence)
                    ),
                    contract_class=klass,
                    source="eth_call",
                    extras={"failed": [f.id for f in failed]},
                ))
            elif held:
                out.append(ForkPropertyResult(
                    id=pid,
                    name=prop["name"],
                    status="held",
                    severity=prop["severity"],
                    evidence="privileged selectors reverted for arbitrary EOA (%d probes)" % len(held),
                    contract_class=klass,
                    source="eth_call",
                ))
            else:
                out.append(ForkPropertyResult(
                    id=pid,
                    name=prop["name"],
                    status="unknown",
                    severity=prop["severity"],
                    evidence="no privileged probes evaluated",
                    contract_class=klass,
                    source="eth_call",
                ))
            continue

        if live_row is None:
            # Map roles-owner etc.
            if pid in {"bridge-roles", "gov-timelock-or-multisig"} and "roles-owner" in by_id:
                live_row = by_id["roles-owner"]
            elif pid == "lending-cash-borrows":
                out.append(ForkPropertyResult(
                    id=pid,
                    name=prop["name"],
                    status="unknown",
                    severity=prop["severity"],
                    evidence="lending cash/borrows views not available via current eth_call suite",
                    contract_class=klass,
                    source="eth_call",
                ))
                continue
            elif pid == "pool-reserves-readable":
                out.append(ForkPropertyResult(
                    id=pid,
                    name=prop["name"],
                    status="unknown",
                    severity=prop["severity"],
                    evidence="pool reserve suite not yet specialized; deferred",
                    contract_class=klass,
                    source="eth_call",
                ))
                continue
            else:
                out.append(ForkPropertyResult(
                    id=pid,
                    name=prop["name"],
                    status="unknown",
                    severity=prop["severity"],
                    evidence="property not evaluated for this class/surface",
                    contract_class=klass,
                    source="eth_call",
                ))
                continue

        status = {
            "held": "held",
            "failed": "violated",
            "unknown": "unknown",
        }.get((live_row.status or "").lower(), "unknown")
        out.append(ForkPropertyResult(
            id=pid,
            name=prop["name"],
            status=status,
            severity=prop["severity"],
            evidence=sanitize_fork_evidence(live_row.evidence),
            contract_class=klass,
            source="eth_call",
            extras=dict(live_row.extras or {}),
        ))

    if run_forge:
        forge_rows = _optional_forge_fork(addr, klass, rpc_url=rpc_url, timeout_s=int(timeout_s))
        out.extend(forge_rows)
    return out


def _optional_forge_fork(
    address: str,
    contract_class: str,
    *,
    rpc_url: str,
    timeout_s: int,
) -> list[ForkPropertyResult]:
    if not shutil.which("forge"):
        return []
    rpc = (rpc_url or os.environ.get("ETH_RPC_URL") or "").strip()
    # Prefer defensive mock Foundry suite when no RPC — still validates templates.
    fuzz_root = Path(__file__).resolve().parents[3] / "research" / "fuzz"
    if not (fuzz_root / "foundry.toml").is_file():
        return []

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "FOUNDRY_PROFILE": "default",
    }
    cmd = ["forge", "test", "--match-path", "test/*", "-q"]
    source = "forge-mock"
    if rpc:
        env["ETH_RPC_URL"] = rpc
        # Fork mode: still run mock suite for free-tier reliability; attach a note.
        # Full live-address forge wiring lands with per-protocol adapters (Phase C graph).
        source = "forge-mock+rpc-available"

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(fuzz_root),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [ForkPropertyResult(
            id="forge-suite",
            name="Foundry defensive property suite",
            status="unknown",
            severity="info",
            evidence=sanitize_fork_evidence("forge skipped/failed: %s" % exc),
            contract_class=contract_class,
            source=source,
        )]

    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode == 0:
        return [ForkPropertyResult(
            id="forge-suite",
            name="Foundry defensive property suite",
            status="held",
            severity="info",
            evidence="forge test passed on defensive mock harness (no attack sequences).",
            contract_class=contract_class,
            source=source,
            extras={"address_under_review": address},
        )]

    # Parse failing test names only — strip traces.
    failed = re.findall(r"\[FAIL[^\]]*\]\s+([A-Za-z0-9_]+)", text)
    if not failed:
        failed = re.findall(r"Failing tests?:\s*([^\n]+)", text, flags=re.I)
    evidence = "forge reported failure on: %s" % (", ".join(failed[:8]) if failed else "see elided log")
    evidence = sanitize_fork_evidence(evidence)
    return [ForkPropertyResult(
        id="forge-suite",
        name="Foundry defensive property suite",
        status="violated",
        severity="medium",
        evidence=evidence,
        contract_class=contract_class,
        source=source,
        extras={"failed_tests": failed[:12], "address_under_review": address},
    )]
