"""Requeue contracts whose latest high-heat scan is older than 14 days.

The rank key is the latest heat. The peak is kept so a contract that used
to be hot is scanned again even when the newest row is cooler. Drained
rows (already-exploited / dead) are not requeued.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from eth_scanner.feed.lists import normalize_address

STALE_AFTER_S = 14 * 24 * 60 * 60
STALE_MIN_HEAT = 1


def plan_stale(runs: list[dict[str, Any]], now: Optional[datetime] = None) -> list[dict[str, Any]]:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    grouped: dict[str, dict[str, Any]] = {}
    for row in runs or []:
        address = normalize_address(str(row.get("address") or ""))
        if not address or not _finished(row):
            continue
        heat = _heat(row)
        scanned = _when(row.get("created_at"))
        current = grouped.get(address)
        if current is None:
            grouped[address] = {
                "address": address,
                "heat": heat,
                "peak_heat": heat,
                "scanned_at": scanned,
                "liveness": _liveness(row),
                "history_count": 1,
            }
            continue
        current["peak_heat"] = max(int(current["peak_heat"]), heat)
        current["history_count"] = int(current["history_count"]) + 1
        if _newer(scanned, heat, current):
            current["heat"] = heat
            current["scanned_at"] = scanned
            current["liveness"] = _liveness(row)
    planned = []
    for row in grouped.values():
        if row["liveness"] in {"dead", "already-exploited"}:
            continue
        if int(row["peak_heat"]) < STALE_MIN_HEAT:
            continue
        scanned = row["scanned_at"]
        if scanned is None:
            age = STALE_AFTER_S
        else:
            age = (moment - scanned).total_seconds()
        if age < STALE_AFTER_S:
            continue
        planned.append({
            "address": row["address"],
            "heat": row["heat"],
            "peak_heat": row["peak_heat"],
            "history_count": row["history_count"],
        })
    planned.sort(key=lambda item: (-int(item["peak_heat"]), item["address"]))
    return planned


def apply_stale(store: Any, addresses: list[str]) -> list[str]:
    """Mark each address pending. A store without requeue_target changes nothing."""
    fn = getattr(store, "requeue_target", None)
    if not callable(fn):
        return []
    done = []
    for address in addresses:
        if fn(address):
            done.append(normalize_address(address))
    return done


def _finished(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").strip().lower() in {"", "done", "dropped", "gated"}


def _heat(row: dict[str, Any]) -> int:
    values = []
    for key in ("blend_heat", "heat"):
        try:
            if row.get(key) is not None and row.get(key) != "":
                values.append(int(float(row.get(key))))
        except (TypeError, ValueError):
            continue
    return max(values) if values else 0


def _liveness(row: dict[str, Any]) -> str:
    raw = row.get("heat_breakdown")
    if isinstance(raw, str):
        try:
            import json
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if not isinstance(raw, dict):
        return "live"
    block = raw.get("liveness")
    status = str((block or {}).get("status") or "") if isinstance(block, dict) else ""
    if status in {"dead", "already-exploited"}:
        return status
    return "live"


def _when(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _newer(scanned: Optional[datetime], heat: int, current: dict[str, Any]) -> bool:
    prev = current["scanned_at"]
    if scanned is None and prev is None:
        return heat > int(current["heat"])
    if scanned is None:
        return False
    if prev is None or scanned > prev:
        return True
    if scanned == prev and heat > int(current["heat"]):
        return True
    return False
