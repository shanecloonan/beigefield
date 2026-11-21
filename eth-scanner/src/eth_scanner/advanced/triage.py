"""Triage for manual-review rows. A note may lower heat. It cannot raise it."""

from __future__ import annotations

from typing import Any, Optional


MAYBE_BUCKET = "manual-review"


def apply_maybe(
    *,
    heat: int,
    bucket: str,
    lower_by: int = 0,
    note: str = "",
) -> dict[str, Any]:
    current = max(0, int(heat or 0))
    if bucket != MAYBE_BUCKET:
        return {
            "status": "skipped",
            "reason": "not a manual-review row",
            "heat": current,
            "heat_before": current,
            "heat_contribution": 0,
            "annotation": "",
        }
    drop = max(0, int(lower_by or 0))
    updated = max(0, current - drop)
    text = (note or "").strip()[:500]
    if drop == 0 and not text:
        return {
            "status": "skipped",
            "reason": "nothing to annotate",
            "heat": current,
            "heat_before": current,
            "heat_contribution": 0,
            "annotation": "",
        }
    return {
        "status": "ok",
        "reason": "",
        "heat": updated,
        "heat_before": current,
        "heat_contribution": updated - current,
        "annotation": text,
    }


def triage_report(
    *,
    heat: int = 0,
    bucket: str = "",
    lower_by: int = 0,
    note: str = "",
    configured: Optional[bool] = None,
) -> dict[str, Any]:
    """Skip when no key is configured and the caller did not pass a note."""
    if configured is None:
        from eth_scanner.triage_ai.explain import llm_configured

        configured = llm_configured()
    if not configured and not (note or "").strip() and int(lower_by or 0) <= 0:
        return {
            "status": "skipped",
            "reason": "no LLM key",
            "heat": max(0, int(heat or 0)),
            "heat_before": max(0, int(heat or 0)),
            "heat_contribution": 0,
            "annotation": "",
        }
    return apply_maybe(heat=heat, bucket=bucket, lower_by=lower_by, note=note)
