"""Optional archive RPC. Historical reads prefer it and fall back.

Trace and debug support is not probed. A ``debug_traceTransaction``
probe costs about 1,000 CU, so the default plan spends none. Send and
mempool methods are refused. The URL is never returned in the public plan.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

ERIGON_IMAGE = "erigontech/erigon:v3.8.2"
PROBE_METHOD = "web3_clientVersion"
TRACE_PROBE_CU = 1000

_REFUSED = frozenset({
    "eth_sendTransaction",
    "eth_sendRawTransaction",
    "eth_sendUnsignedTransaction",
    "eth_newPendingTransactionFilter",
    "eth_getFilterChanges",
    "txpool_content",
    "txpool_inspect",
    "eth_subscribe",
})
_TRACE = frozenset({
    "debug_traceTransaction",
    "debug_traceCall",
    "debug_traceBlockByNumber",
    "trace_transaction",
    "trace_block",
    "trace_replayTransaction",
    "trace_replayBlockTransactions",
    "trace_filter",
})

Fetch = Callable[[str, list[Any]], Any]


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _configured(archive_url: Optional[str], current_url: Optional[str]) -> tuple[str, str]:
    if archive_url is None:
        archive_url = os.environ.get("ARCHIVE_RPC_URL") or ""
    if current_url is None:
        current_url = os.environ.get("ETH_RPC_URL") or ""
    return _clean(archive_url), _clean(current_url)


def historical_url(
    *,
    archive_url: Optional[str] = None,
    current_url: Optional[str] = None,
    method: str = "",
) -> str:
    """URL for a historical read. Empty when neither RPC is set.

    Callers pass this to the RPC client and do not print it.
    """
    plan = plan_archive(
        historical=True,
        method=method,
        archive_url=archive_url,
        current_url=current_url,
    )
    return str(plan.get("_url") or "")


def plan_archive(
    *,
    historical: bool = False,
    method: str = "",
    archive_url: Optional[str] = None,
    current_url: Optional[str] = None,
    probe: bool = False,
    fetch: Optional[Fetch] = None,
) -> dict[str, Any]:
    """Choose archive or the current RPC. A probe is off unless asked."""
    archive, current = _configured(archive_url, current_url)
    name = (method or "").strip()
    report: dict[str, Any] = {
        "status": "ok",
        "source": "unset",
        "historical": bool(historical or name in _TRACE),
        "method": name,
        "refused": False,
        "archive": bool(archive),
        "fallback": False,
        "probed": False,
        "probe_method": "",
        "probe_cu": 0,
        "trace_probe_cu": TRACE_PROBE_CU,
        "calls": [],
        "heat_contribution": 0,
        "_url": "",
        "note": "",
    }
    if name in _REFUSED:
        report["status"] = "refused"
        report["refused"] = True
        report["note"] = "Archive reads do not send transactions or open the mempool."
        return report
    wants_archive = bool(historical or name in _TRACE)
    if wants_archive and archive:
        report["source"] = "archive"
        report["_url"] = archive
    elif wants_archive and current:
        report["source"] = "current"
        report["fallback"] = True
        report["_url"] = current
    elif not wants_archive and current:
        report["source"] = "current"
        report["_url"] = current
    elif not wants_archive and archive:
        report["source"] = "archive"
        report["fallback"] = True
        report["_url"] = archive
    else:
        report["status"] = "unset"
        report["note"] = "ARCHIVE_RPC_URL and ETH_RPC_URL are unset. Nothing was contacted."
        return report
    if name in _TRACE and probe:
        report["status"] = "refused"
        report["refused"] = True
        report["_url"] = ""
        report["note"] = "A trace method is not used as the capability probe."
        return report
    if not probe:
        report["note"] = (
            "Archive is preferred for historical and trace reads, then the current RPC. "
            "Trace support is not probed, so a 1000 CU debug trace is not spent. Heat stays 0."
        )
        return report
    if fetch is None:
        report["note"] = "No client was provided. The trace probe was not sent."
        return report
    report["calls"].append(PROBE_METHOD)
    try:
        fetch(PROBE_METHOD, [])
    except Exception:
        report["note"] = "The client-version read failed. The RPC URL is not stored."
        return report
    report["probed"] = True
    report["probe_method"] = PROBE_METHOD
    report["probe_cu"] = 0
    report["note"] = "Capability used web3_clientVersion. debug_traceTransaction was not called."
    return report


def public_plan(report: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to print. The RPC URL is not one of them."""
    return {
        "status": report.get("status"),
        "source": report.get("source"),
        "historical": bool(report.get("historical")),
        "method": report.get("method") or "",
        "refused": bool(report.get("refused")),
        "archive": bool(report.get("archive")),
        "fallback": bool(report.get("fallback")),
        "probed": bool(report.get("probed")),
        "probe_method": report.get("probe_method") or "",
        "probe_cu": int(report.get("probe_cu") or 0),
        "calls": list(report.get("calls") or []),
        "heat": 0,
        "heat_breakdown": {"archive": bool(report.get("archive"))},
        "note": report.get("note"),
    }
