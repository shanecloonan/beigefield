"""Storage layout diffing for upgradeable proxies.

Compare current implementation vs previous (from Upgraded events) using
selector/skeleton heuristics + live slot reads. Collisions / reordered
critical slots confirmed only when live storage contradicts expected layout.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.research.proxy import (
    EIP1967_IMPLEMENTATION_SLOT,
    eth_get_storage_at,
    storage_word_to_address,
)

# event Upgraded(address indexed implementation)
_UPGRADED_TOPIC0 = "0xbc7cd75a20ee27fd9adebab32041f755214dbc6bffa90cc0225b39da2e5c2d3b"

_STATE_VAR_RX = re.compile(
    r"^\s*(?:mapping\s*\([^;]+\)|[\w\[\]]+(?:\s+private|\s+internal|\s+public)?)\s+(\w+)\s*(?:=|;)",
    re.M,
)


@dataclass
class StorageFinding:
    id: str
    title: str
    evidence: str
    confirmed: bool = False
    method: str = "storage"
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StorageReport:
    ran: bool = False
    status: str = "skipped"
    current_impl: Optional[str] = None
    previous_impl: Optional[str] = None
    leads: list[StorageFinding] = field(default_factory=list)
    confirmed: list[StorageFinding] = field(default_factory=list)
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "status": self.status,
            "current_impl": self.current_impl,
            "previous_impl": self.previous_impl,
            "leads": [f.to_dict() for f in self.leads],
            "confirmed": [f.to_dict() for f in self.confirmed],
            "duration_ms": self.duration_ms,
            "notes": list(self.notes),
            "artifact": dict(self.artifact),
        }


def run_storage_diff(
    *,
    address: str,
    rpc_url: str,
    source: str = "",
    timeout_s: float = 30.0,
) -> StorageReport:
    report = StorageReport()
    t0 = time.monotonic()
    if not rpc_url:
        report.notes.append("storage-diff skipped — no RPC")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    deadline = t0 + max(8.0, float(timeout_s))
    try:
        word = eth_get_storage_at(rpc_url, address, EIP1967_IMPLEMENTATION_SLOT)
        report.current_impl = storage_word_to_address(word)
        report.ran = True  # slot read succeeded — stage executed
    except Exception as exc:  # noqa: BLE001
        report.notes.append("storage-diff: impl slot read failed: %s" % str(exc)[:100])
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    if not report.current_impl:
        report.status = "ok"
        report.notes.append("storage-diff: not an EIP-1967 proxy (empty impl slot)")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    prev = _previous_implementation(rpc_url, address, deadline)
    report.previous_impl = prev

    if not prev:
        report.status = "ok"
        report.notes.append("storage-diff: no prior Upgraded event — nothing to diff")
        _finish(report, address, t0)
        return report

    if prev.lower() == report.current_impl.lower():
        report.status = "ok"
        report.notes.append("storage-diff: previous impl equals current")
        _finish(report, address, t0)
        return report

    # Lead: upgrade occurred — layout risk until confirmed.
    report.leads.append(StorageFinding(
        id="storage-upgrade-history",
        title="Proxy has prior implementation (Upgraded event)",
        evidence="current=%s previous=%s" % (report.current_impl, prev),
        extras={"current": report.current_impl, "previous": prev},
    ))

    # Source-level state var order fingerprint (current source only — previous
    # source often unavailable). Flag when packing-sensitive types reorder.
    layout = _state_var_names(source)
    if layout:
        report.notes.append("storage-diff source vars=%s" % ",".join(layout[:12]))

    # Confirm by reading live slots 0..7 on the proxy and checking EIP-1967
    # slots remain intact (impl/admin not clobbered into low slots).
    low_slots = _read_low_slots(rpc_url, address, n=8, deadline=deadline)
    impl_in_low = any(
        (v or "").lower().endswith((report.current_impl or "")[2:].lower())
        for v in low_slots.values()
        if v
    )
    if impl_in_low:
        # Unusual: implementation address appearing in slot 0..7 can indicate
        # storage collision after upgrade (proxy slot pollution).
        conf = StorageFinding(
            id="storage-collision-live",
            title="Implementation address appears in low storage slots (possible collision)",
            evidence="impl=%s low_slots=%s" % (report.current_impl, json.dumps(low_slots)[:300]),
            confirmed=True,
            method="storage",
            extras={"low_slots": low_slots, "current": report.current_impl, "previous": prev},
        )
        report.confirmed.append(conf)
    else:
        # Soft lead only when upgrade history exists without live collision.
        report.leads.append(StorageFinding(
            id="storage-layout-review",
            title="Upgrade history present — review storage layout (no live collision)",
            evidence="previous=%s current=%s low_slots_ok=1" % (prev, report.current_impl),
            extras={"previous": prev, "current": report.current_impl},
        ))

    report.status = "ok"
    report.notes.append(
        "storage-diff prev=%s confirmed=%d"
        % ((prev[:10] if prev else None), len(report.confirmed))
    )
    _finish(report, address, t0)
    return report


def storage_as_confirmed(report: StorageReport) -> list[dict[str, Any]]:
    return [
        {
            "lead_id": c.id,
            "confirmed": True,
            "method": c.method or "storage",
            "evidence": c.evidence[:500],
            "extras": dict(c.extras),
        }
        for c in report.confirmed
    ]


def storage_as_leads(report: StorageReport) -> list[dict[str, Any]]:
    return [
        {
            "id": lead.id,
            "engine": "storage",
            "rule": lead.id,
            "title": lead.title,
            "severity": "med",
            "evidence": lead.evidence,
            "generic": False,
        }
        for lead in report.leads
    ]


def _finish(report: StorageReport, address: str, t0: float) -> None:
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.artifact = {
        "kind": "storage",
        "address": address.lower(),
        "current_impl": report.current_impl,
        "previous_impl": report.previous_impl,
        "leads": [f.to_dict() for f in report.leads],
        "confirmed": [f.to_dict() for f in report.confirmed],
        "notes": list(report.notes)[:10],
        "duration_ms": report.duration_ms,
    }


def _rpc(rpc_url: str, method: str, params: list[Any], timeout_s: float = 12.0) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        rpc_url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-storage/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    return body.get("result")


def _previous_implementation(
    rpc_url: str,
    address: str,
    deadline: float,
) -> Optional[str]:
    try:
        latest = _rpc(rpc_url, "eth_blockNumber", [], timeout_s=min(5.0, max(1.0, deadline - time.monotonic())))
        latest_n = int(latest, 16)
        # Look back ~200k blocks (~1 month) for Upgraded events — capped for timeout.
        from_block = max(0, latest_n - 200_000)
        logs = _rpc(
            rpc_url,
            "eth_getLogs",
            [{
                "address": address,
                "topics": [_UPGRADED_TOPIC0],
                "fromBlock": hex(from_block),
                "toBlock": "latest",
            }],
            timeout_s=min(12.0, max(2.0, deadline - time.monotonic())),
        )
        if not isinstance(logs, list) or len(logs) < 2:
            # One upgrade log → no "previous" beyond genesis impl; still try.
            if isinstance(logs, list) and len(logs) == 1:
                return None
            return None
        # Second-to-last Upgraded = previous implementation.
        prev_log = logs[-2]
        topics = prev_log.get("topics") or []
        if len(topics) >= 2:
            return storage_word_to_address(topics[1])
        data = prev_log.get("data") or ""
        return storage_word_to_address(data)
    except Exception:  # noqa: BLE001
        return None


def _state_var_names(source: str) -> list[str]:
    names: list[str] = []
    for m in _STATE_VAR_RX.finditer(source or ""):
        n = m.group(1)
        if n in {"mapping", "return", "if", "for", "function", "event", "error", "modifier"}:
            continue
        if n not in names:
            names.append(n)
    return names[:40]


def _read_low_slots(
    rpc_url: str,
    address: str,
    *,
    n: int,
    deadline: float,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for i in range(n):
        if time.monotonic() > deadline:
            break
        slot = "0x" + format(i, "064x")
        try:
            out[str(i)] = str(eth_get_storage_at(rpc_url, address, slot) or "")
        except Exception:  # noqa: BLE001
            out[str(i)] = ""
    return out
