"""Per-run compute-unit budget for the capped Alchemy endpoint.

Shane's org cap is $50/month, about 96 million CU. These estimates are the
conservative published Alchemy costs (debug traces counted at 1,000 CU).
A method that is not listed costs ``DEFAULT_UNKNOWN_CU``. Charging before
the call means a 429 still counts.

Default trace-seed cap is 2,500 CU. Fifty candidate scans a day for a month
is about 3.8 million CU for seeds alone, well under the cap. Raise it with
``ETH_SCANNER_TRACE_SEED_CU`` only after checking the monthly total.
"""

from __future__ import annotations

import os
from typing import Any

# Conservative Alchemy compute-unit costs. Over-estimates spend fewer calls.
CU_ESTIMATES: dict[str, int] = {
    "eth_blockNumber": 10,
    "eth_getBalance": 19,
    "eth_getCode": 19,
    "eth_getStorageAt": 17,
    "eth_getTransactionByHash": 17,
    "eth_call": 26,
    "eth_getProof": 80,
    "eth_getLogs": 75,
    "alchemy_getAssetTransfers": 120,
    "trace_filter": 150,
    "debug_traceTransaction": 1000,
}

DEFAULT_UNKNOWN_CU = 100
DEFAULT_TRACE_SEED_CU = 2500
# Storage preload and liveness checks have their own smaller caps.
DEFAULT_STORAGE_CU = 1500
DEFAULT_LIVENESS_CU = 400

# Fifty scans/day * 30 days * (2500 + 1500 + 400) CU.
MONTHLY_SCAN_EXAMPLE = {
    "scans_per_day": 50,
    "days": 30,
    "cu_per_scan": DEFAULT_TRACE_SEED_CU + DEFAULT_STORAGE_CU + DEFAULT_LIVENESS_CU,
    "monthly_cu": 50 * 30 * (DEFAULT_TRACE_SEED_CU + DEFAULT_STORAGE_CU + DEFAULT_LIVENESS_CU),
    "org_cap_cu": 96_000_000,
}


class CuBudgetExceeded(RuntimeError):
    """The per-run cap would be crossed. Callers stop and keep partial evidence."""


class CuBudget:
    """In-memory cap plus a result cache so a repeated read is free."""

    def __init__(self, cap: int):
        self.cap = max(0, int(cap))
        self.spent = 0
        self.calls: list[str] = []
        self.cache: dict[str, Any] = {}
        self.stopped = False

    def cost(self, method: str) -> int:
        return int(CU_ESTIMATES.get(method, DEFAULT_UNKNOWN_CU))

    def allow(self, method: str) -> bool:
        return not self.stopped and self.spent + self.cost(method) <= self.cap

    def charge(self, method: str) -> int:
        amount = self.cost(method)
        if self.spent + amount > self.cap:
            self.stopped = True
            raise CuBudgetExceeded("%s would pass the %d CU cap" % (method, self.cap))
        self.spent += amount
        self.calls.append(method)
        return amount

    def snapshot(self) -> dict[str, Any]:
        return {
            "cap": self.cap,
            "spent": self.spent,
            "calls": list(self.calls),
            "stopped": self.stopped,
            "estimates": dict(CU_ESTIMATES),
        }


def cap_from_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default
