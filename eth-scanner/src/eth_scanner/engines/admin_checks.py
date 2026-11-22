"""Admin / upgrade surface checks — EIP-1967 proxies, Safe, timelock, init.

Read-only + fork eth_call simulation only. Uninitialized implementation or
anyone-callable admin on fork sim → confirmed. Feeds eoa_admin /
privileged_callable for Lane B ($100k+ EOA admin).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from eth_scanner.engines.corroborate import (
    PROBE_SELECTORS,
    confirm_privileged_call,
    read_code,
    selector_in_bytecode,
)
from eth_scanner.research.keccak import selector4
from eth_scanner.research.proxy import (
    EIP1967_ADMIN_SLOT,
    EIP1967_BEACON_SLOT,
    EIP1967_IMPLEMENTATION_SLOT,
    eth_get_storage_at,
    storage_word_to_address,
)

# Gnosis Safe, older MultiSigWallet, and OZ TimelockController.
_SEL_GET_OWNERS = selector4("getOwners()")[2:]
_SEL_GET_THRESHOLD = selector4("getThreshold()")[2:]
_SEL_REQUIRED = selector4("required()")[2:]
_SEL_IS_CONFIRMED = selector4("isConfirmed(uint256)")[2:]
_SEL_GET_MIN_DELAY = selector4("getMinDelay()")[2:]
_SEL_IMPLEMENTATION = selector4("implementation()")[2:]
_SEL_PROXIABLE = selector4("proxiableUUID()")[2:]
_EIP1167 = "363d3d373d3d3d363d73"
# OpenZeppelin Initializable: ERC-7201 / legacy slot heuristics
_OZ_INITIALIZED_SLOT = "0x0000000000000000000000000000000000000000000000000000000000000000"


@dataclass
class AdminFinding:
    id: str
    title: str
    evidence: str
    confirmed: bool = False
    method: str = "storage"
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdminReport:
    ran: bool = False
    status: str = "skipped"
    proxy_kind: str = "none"  # eip1967 | transparent | uups | beacon | none
    implementation: Optional[str] = None
    admin: Optional[str] = None
    admin_class: str = "unknown"  # eoa | safe | timelock | contract | unknown
    admin_is_eoa: bool = False
    privileged_callable: bool = False
    eoa_admin: bool = False
    leads: list[AdminFinding] = field(default_factory=list)
    confirmed: list[AdminFinding] = field(default_factory=list)
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "status": self.status,
            "proxy_kind": self.proxy_kind,
            "implementation": self.implementation,
            "admin": self.admin,
            "admin_class": self.admin_class,
            "admin_is_eoa": self.admin_is_eoa,
            "privileged_callable": self.privileged_callable,
            "eoa_admin": self.eoa_admin,
            "leads": [f.to_dict() for f in self.leads],
            "confirmed": [f.to_dict() for f in self.confirmed],
            "duration_ms": self.duration_ms,
            "notes": list(self.notes),
            "meta": dict(self.meta),
            "artifact": dict(self.artifact),
        }


def run_admin_checks(
    *,
    address: str,
    rpc_url: str,
    funds_usd: Optional[float] = None,
    source: str = "",
    timeout_s: float = 30.0,
    lane_owner: str = "",
    lane_owner_kind: str = "",
) -> AdminReport:
    report = AdminReport()
    t0 = time.monotonic()
    if not rpc_url:
        report.notes.append("admin skipped — no RPC")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    report.ran = True
    deadline = t0 + max(8.0, float(timeout_s))

    impl = _safe_slot_addr(rpc_url, address, EIP1967_IMPLEMENTATION_SLOT)
    admin = _safe_slot_addr(rpc_url, address, EIP1967_ADMIN_SLOT)
    beacon = _safe_slot_addr(rpc_url, address, EIP1967_BEACON_SLOT)
    report.implementation = impl
    report.admin = admin

    if beacon and not impl:
        report.proxy_kind = "beacon"
    elif admin and impl:
        report.proxy_kind = "transparent"
    elif impl and not admin:
        report.proxy_kind = "uups"
    elif impl:
        report.proxy_kind = "eip1967"
    else:
        report.proxy_kind = "none"

    code = read_code(rpc_url, address)
    report.meta["code_status"] = code.get("status")
    if report.proxy_kind == "none" and code.get("status") == "ok" and _looks_custom_proxy(str(code.get("hex") or "")):
        report.proxy_kind = "custom"
        impl_addr = _implementation_of(rpc_url, address)
        if impl_addr:
            report.implementation = impl_addr
            report.notes.append("custom proxy implementation=%s" % impl_addr)

    controller = admin or _owner_of(rpc_url, address)
    if controller:
        report.admin = report.admin or controller
        report.admin_class, details = _classify_controller(rpc_url, controller, deadline)
        report.meta["controller_details"] = details
        report.admin_is_eoa = report.admin_class == "eoa" and details.get("code_status") == "ok"
        same_owner = (
            lane_owner
            and controller
            and lane_owner.lower() == controller.lower()
        )
        if same_owner and lane_owner_kind == "contract" and report.admin_class == "eoa":
            report.admin_class = "contract"
            report.admin_is_eoa = False
            report.notes.append("lane A owner kind=contract; getCode disagreement is not an EOA")
        if report.admin_is_eoa:
            report.eoa_admin = True
            lead = AdminFinding(
                id="admin-eoa",
                title="Admin/owner is an EOA",
                evidence="controller=%s class=eoa" % controller,
                confirmed=False,
                method="storage",
                extras={"controller": controller},
            )
            report.leads.append(lead)
            if funds_usd is not None and funds_usd >= 100_000:
                conf = AdminFinding(
                    id="admin-eoa-confirmed",
                    title="EOA admin on contract with funds >= $100k",
                    evidence="controller=%s funds_usd=%.0f" % (controller, funds_usd),
                    confirmed=True,
                    method="storage",
                    extras={"controller": controller, "funds_usd": funds_usd},
                )
                report.confirmed.append(conf)
        elif report.admin_class == "safe":
            report.notes.append(
                "admin is Safe threshold=%s owners=%s"
                % (details.get("threshold"), details.get("owners_n"))
            )
        elif report.admin_class == "timelock":
            report.notes.append("admin is Timelock minDelay=%ss" % details.get("min_delay"))
        elif report.admin_class == "multisig":
            report.notes.append("admin is a multisig (required/getOwners/isConfirmed)")

    # Uninitialized implementation: eth_call initialize() on impl must revert.
    impl_code = read_code(rpc_url, impl) if impl else {"hex": "", "status": "unknown"}
    if impl and time.monotonic() < deadline:
        verdict = confirm_privileged_call(
            rpc_url, impl, PROBE_SELECTORS["initialize()"],
            code_hex=str(impl_code.get("hex") or ""),
            source=source,
            signature="initialize()",
            timeout_s=min(8.0, deadline - time.monotonic()),
        )
        note = str(verdict.get("reason") or "")
        ok = bool(verdict.get("confirmed"))
        if ok:
            conf = AdminFinding(
                id="admin-uninit-impl",
                title="Implementation initialize() succeeds (uninitialized)",
                evidence="impl=%s %s" % (impl, note),
                confirmed=True,
                method="eth_call",
                extras={"implementation": impl, "probe": "initialize()"},
            )
            report.confirmed.append(conf)
            report.privileged_callable = True
            report.leads.append(AdminFinding(
                id="admin-uninit-impl-lead",
                title="Implementation may be uninitialized",
                evidence=note,
            ))
        else:
            report.notes.append("initialize() on impl: %s" % note[:120])

    # Anyone-callable upgrade/admin on the proxy itself.
    if time.monotonic() < deadline:
        for name, sel in (
            ("upgradeTo(address)", PROBE_SELECTORS["upgradeTo(address)"] + ("00" * 32)),
            ("changeAdmin(address)", PROBE_SELECTORS["changeAdmin(address)"] + ("00" * 32)),
            ("transferOwnership(address)", PROBE_SELECTORS["transferOwnership(address)"] + ("00" * 32)),
        ):
            if time.monotonic() > deadline:
                break
            verdict = confirm_privileged_call(
                rpc_url, address, sel[:8],
                code_hex=str(code.get("hex") or ""),
                impl_code_hex=str(impl_code.get("hex") or ""),
                source=source,
                signature=name,
                data_suffix=sel[8:] if len(sel) > 8 else "",
                timeout_s=min(6.0, deadline - time.monotonic()),
            )
            note = str(verdict.get("reason") or "")
            ok = bool(verdict.get("confirmed"))
            if ok:
                report.privileged_callable = True
                conf = AdminFinding(
                    id="admin-privileged-open",
                    title="Privileged admin function callable by outsider",
                    evidence="%s on %s — %s" % (name, address, note),
                    confirmed=True,
                    method="eth_call",
                    extras={"probe": name},
                )
                report.confirmed.append(conf)
                break

    # Source hint: UUPS without _disableInitializers already covered by clones;
    # note proxy kind for UI.
    if "UUPSUpgradeable" in (source or "") or "upgradeTo" in (source or ""):
        report.meta["source_upgradeable"] = True

    report.status = "ok"
    report.notes.append(
        "admin kind=%s class=%s eoa=%s priv=%s confirmed=%d"
        % (
            report.proxy_kind,
            report.admin_class,
            report.eoa_admin,
            report.privileged_callable,
            len(report.confirmed),
        )
    )
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.artifact = {
        "kind": "admin",
        "address": address.lower(),
        "proxy_kind": report.proxy_kind,
        "implementation": report.implementation,
        "admin": report.admin,
        "admin_class": report.admin_class,
        "confirmed": [f.to_dict() for f in report.confirmed],
        "leads": [f.to_dict() for f in report.leads],
        "notes": list(report.notes)[:10],
        "duration_ms": report.duration_ms,
    }
    return report


def admin_as_confirmed(report: AdminReport) -> list[dict[str, Any]]:
    rows = []
    for c in report.confirmed:
        extras = dict(c.extras)
        fact = str(extras.get("fact") or _FACT_FOR_ID.get(c.id) or "")
        if fact:
            extras["fact"] = fact
        rows.append({
            "lead_id": c.id,
            "confirmed": True,
            "method": c.method or "admin",
            "evidence": c.evidence[:500],
            "fact": fact,
            "extras": extras,
        })
    return rows


_FACT_FOR_ID = {
    "admin-eoa-confirmed": "eoa-admin",
    "admin-privileged-open": "privileged-callable",
    "admin-uninit-impl": "privileged-callable",
}


def admin_as_leads(report: AdminReport) -> list[dict[str, Any]]:
    return [
        {
            "id": lead.id,
            "engine": "admin",
            "rule": lead.id,
            "title": lead.title,
            "severity": "high",
            "evidence": lead.evidence,
            "generic": False,
        }
        for lead in report.leads
    ]


def _rpc(rpc_url: str, method: str, params: list[Any], timeout_s: float = 10.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(rpc_url, method, params, timeout_s=timeout_s)

def _safe_slot_addr(rpc_url: str, address: str, slot: str) -> Optional[str]:
    try:
        word = eth_get_storage_at(rpc_url, address, slot)
        return storage_word_to_address(word)
    except Exception:  # noqa: BLE001
        return None


def _owner_of(rpc_url: str, address: str) -> Optional[str]:
    for sel in ("8da5cb5b", "b449c54b", "f851a440"):  # owner(), getOwner(), admin()
        try:
            raw = str(_rpc(rpc_url, "eth_call", [{"to": address, "data": "0x" + sel}, "latest"]) or "")
            addr = storage_word_to_address(raw)
            if addr:
                return addr
        except Exception:  # noqa: BLE001
            continue
    return None


def _looks_custom_proxy(code_hex: str) -> bool:
    raw = (code_hex or "").lower()
    if _EIP1167 in raw:
        return True
    return any(selector_in_bytecode(raw, sel) for sel in (
        _SEL_IMPLEMENTATION, _SEL_PROXIABLE, PROBE_SELECTORS["upgradeTo(address)"],
    ))


def _wallet_kind(code_hex: str) -> str:
    """Bytecode dispatch for a Safe or an older multisig. Not an EOA."""
    owners = selector_in_bytecode(code_hex, _SEL_GET_OWNERS)
    required = selector_in_bytecode(code_hex, _SEL_REQUIRED)
    confirmed = selector_in_bytecode(code_hex, _SEL_IS_CONFIRMED)
    threshold = selector_in_bytecode(code_hex, _SEL_GET_THRESHOLD)
    if owners and required and confirmed:
        return "multisig"
    if owners and threshold:
        return "safe"
    return ""


def _implementation_of(rpc_url: str, address: str) -> Optional[str]:
    try:
        raw = str(_rpc(
            rpc_url, "eth_call",
            [{"to": address, "data": "0x" + _SEL_IMPLEMENTATION}, "latest"],
        ) or "")
    except Exception:  # noqa: BLE001
        return None
    return storage_word_to_address(raw)


def _classify_controller(
    rpc_url: str,
    controller: str,
    deadline: float,
) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {}
    read = read_code(rpc_url, controller)
    details["code_status"] = read.get("status")
    if read.get("status") != "ok":
        return "unknown", details
    sz = int(read.get("size") or 0)
    if sz == 0:
        return "eoa", {"code_size": 0, "code_status": "ok"}
    patterned = _wallet_kind(str(read.get("hex") or ""))
    if patterned:
        details.update({"code_size": sz, "code_status": "ok", "pattern": patterned})
        return patterned, details
    # Safe?
    try:
        if time.monotonic() < deadline:
            owners_raw = str(_rpc(
                rpc_url, "eth_call",
                [{"to": controller, "data": "0x" + _SEL_GET_OWNERS}, "latest"],
                timeout_s=min(6.0, max(1.0, deadline - time.monotonic())),
            ) or "")
            thr_raw = str(_rpc(
                rpc_url, "eth_call",
                [{"to": controller, "data": "0x" + _SEL_GET_THRESHOLD}, "latest"],
                timeout_s=min(6.0, max(1.0, deadline - time.monotonic())),
            ) or "")
            # owners is address[]; non-empty decode length prefix suggests Safe
            h = owners_raw.removeprefix("0x")
            if len(h) >= 128:
                # offset + length
                length = int(h[64:128], 16) if len(h) >= 128 else 0
                if 0 < length <= 64:
                    thr = int(thr_raw.removeprefix("0x") or "0", 16) if thr_raw else 0
                    details.update({"owners_n": length, "threshold": thr, "code_size": sz})
                    return "safe", details
    except Exception:  # noqa: BLE001
        pass
    # Timelock?
    try:
        if time.monotonic() < deadline:
            delay_raw = str(_rpc(
                rpc_url, "eth_call",
                [{"to": controller, "data": "0x" + _SEL_GET_MIN_DELAY}, "latest"],
                timeout_s=min(6.0, max(1.0, deadline - time.monotonic())),
            ) or "")
            if delay_raw and delay_raw not in {"0x", "0x0"}:
                delay = int(delay_raw.removeprefix("0x") or "0", 16)
                if delay > 0:
                    details.update({"min_delay": delay, "code_size": sz})
                    return "timelock", details
    except Exception:  # noqa: BLE001
        pass
    details["code_size"] = sz
    return "contract", details
