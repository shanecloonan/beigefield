"""Properties for a vault plus the contracts around it.

Catalog properties go through the baseline gate. A strategy, oracle, or
router with no catalog entry is only a witness. Heat moves only when a
local fuzzer or prover fails a kept property.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.advanced.invariants import judge
from eth_scanner.fork_props.catalog import CLASS_PROPERTIES


def protocol_report(
    parts: dict[str, str],
    *,
    baseline_failures: Optional[set[str]] = None,
    local_failures: Optional[set[str]] = None,
) -> dict[str, Any]:
    proposed: list[str] = []
    witnesses: list[dict[str, Any]] = []
    for role, address in parts.items():
        props = CLASS_PROPERTIES.get(role) or []
        if not props:
            witnesses.append({
                "role": role,
                "address": address,
                "heat_contribution": 0,
            })
            continue
        for prop in props:
            proposed.append(str(prop["id"]))
    judged = judge(
        proposed,
        baseline_failures=baseline_failures,
        local_failures=local_failures,
    )
    judged["witnesses"] = witnesses
    judged["vault_present"] = "vault" in parts
    judged["note"] = (
        "Protocol properties use the baseline gate. "
        "Roles without a catalog entry are witnesses and add no heat."
    )
    return judged
