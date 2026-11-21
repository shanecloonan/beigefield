"""Allowlisted invariant proposals.

A name is kept only when it is one of the defensive catalog properties and
it did not fail on the known-good baseline. Heat moves only when a local
fuzzer or prover then fails that same property. An LLM is not called here.
Without a configured key the command skips, and a model is never allowed
to invent a property outside the catalog.
"""

from __future__ import annotations

from typing import Any, Optional

from eth_scanner.fork_props.catalog import CLASS_PROPERTIES


ALLOWED = frozenset(
    str(prop["id"])
    for props in CLASS_PROPERTIES.values()
    for prop in props
    if prop.get("id")
)


def judge(
    proposed: list[str],
    *,
    baseline_failures: Optional[set[str]] = None,
    local_failures: Optional[set[str]] = None,
) -> dict[str, Any]:
    baseline = set(baseline_failures or ())
    local = set(local_failures or ())
    kept: list[str] = []
    dropped: list[dict[str, str]] = []
    reproduced: list[str] = []
    for name in proposed:
        if name not in ALLOWED:
            dropped.append({"id": name, "reason": "outside the defensive allowlist"})
            continue
        if name in baseline:
            dropped.append({"id": name, "reason": "failed the known-good baseline"})
            continue
        kept.append(name)
        if name in local:
            reproduced.append(name)
    return {
        "status": "ok",
        "kept": kept,
        "dropped": dropped,
        "reproduced": reproduced,
        "heat_contribution": len(reproduced),
        "note": (
            "Heat moves only when a local fuzzer or prover fails a property "
            "that held on the known-good baseline."
        ),
    }


def report(
    proposed: Optional[list[str]] = None,
    *,
    baseline_failures: Optional[set[str]] = None,
    local_failures: Optional[set[str]] = None,
) -> dict[str, Any]:
    if proposed is None:
        from eth_scanner.triage_ai.explain import llm_configured

        if not llm_configured():
            return {
                "status": "skipped",
                "reason": "no LLM key",
                "kept": [],
                "dropped": [],
                "reproduced": [],
                "heat_contribution": 0,
                "note": "Invariant proposals are skipped without a configured key. Heat stays 0.",
            }
        proposed = []
    return judge(
        list(proposed),
        baseline_failures=baseline_failures,
        local_failures=local_failures,
    )
