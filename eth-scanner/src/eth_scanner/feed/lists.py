"""Named scan lists for the deep lane.

List 1 is the funded curated master feed. Strong rows use the existing
hot / Lane B / tier / drain-prior rules.

List 2 is the $50–$1,900 sketchy feed. Rows outside that band are dropped.
Every in-band List 2 row is a deep-lane candidate. An explicit address is
accepted even when it is not otherwise strong.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

LIST1_ID = "list-1"
LIST2_ID = "list-2"
LIST2_MIN_USD = 50.0
LIST2_MAX_USD = 1900.0

LIST_META = {
    LIST1_ID: {
        "id": LIST1_ID,
        "name": "List 1",
        "kind": "funded-curated",
        "blurb": "Funded curated feed. Deep lane uses the existing strong-candidate rules.",
        "min_usd": None,
        "max_usd": None,
    },
    LIST2_ID: {
        "id": LIST2_ID,
        "name": "List 2",
        "kind": "sketchy",
        "blurb": "Janky and sketchy targets holding $50–$1,900. Rows outside that band are dropped.",
        "min_usd": LIST2_MIN_USD,
        "max_usd": LIST2_MAX_USD,
    },
}


def default_list2_path() -> Path:
    env = (os.environ.get("ETH_SCANNER_LIST2") or "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    return here.parents[3] / "data" / "list2_candidates.json"


def _held(raw: dict[str, Any]) -> float:
    value = raw.get("est_usd_held")
    if value in (None, ""):
        value = raw.get("funds_usd")
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _in_band(held: float) -> bool:
    return LIST2_MIN_USD <= held <= LIST2_MAX_USD


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("candidates") or payload.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return []
    return [row for row in rows if isinstance(row, dict)]


def load_list2(path: Optional[Path | str] = None) -> tuple[list[dict[str, Any]], int]:
    """Return (in-band rows, dropped count)."""
    src = Path(path) if path else default_list2_path()
    kept: list[dict[str, Any]] = []
    dropped = 0
    for raw in _read_rows(src):
        if not _in_band(_held(raw)):
            dropped += 1
            continue
        kept.append(_normalize_row(raw, LIST2_ID, deep_lane=True))
    kept.sort(key=lambda row: (-float(row["est_usd_held"]), row["address"]))
    return kept, dropped


def _normalize_row(raw: dict[str, Any], list_id: str, *, deep_lane: bool) -> dict[str, Any]:
    address = str(raw.get("address") or "").lower()
    return {
        "address": address,
        "protocol": str(raw.get("protocol") or ""),
        "est_usd_held": _held(raw),
        "tier": int(raw.get("tier") or 99),
        "candidate_reason": str(raw.get("candidate_reason") or ""),
        "drain_probability": float(raw.get("drain_probability") or 0.0),
        "contract_class": str(raw.get("contract_class") or raw.get("category") or ""),
        "list_id": list_id,
        "source": str(raw.get("source") or ""),
        "fixture": raw.get("fixture") or None,
        "deep_lane": bool(deep_lane),
        "bucket": "no",
    }


def _list1_rows() -> list[dict[str, Any]]:
    from eth_scanner.deep.strong import is_strong_candidate
    from eth_scanner.feed.master_list import load_master_candidates

    rows: list[dict[str, Any]] = []
    for cand in load_master_candidates():
        deep = is_strong_candidate(
            tier=cand.tier,
            funds_usd=cand.est_usd_held,
            heat=0,
            bucket=None,
            drain_probability=cand.drain_probability,
        )
        rows.append(_normalize_row(cand.to_dict(), LIST1_ID, deep_lane=deep))
    return rows


def contracts_for(list_id: str, *, list2_path: Optional[Path | str] = None) -> list[dict[str, Any]]:
    if list_id == LIST1_ID:
        return _list1_rows()
    if list_id == LIST2_ID:
        rows, _dropped = load_list2(list2_path)
        return rows
    raise ValueError("unknown list %s" % list_id)


def select_deep(
    list_id: str,
    *,
    address: Optional[str] = None,
    list2_path: Optional[Path | str] = None,
) -> list[dict[str, Any]]:
    """Deep-lane rows. An explicit address is kept even if it is not strong."""
    if list_id in {LIST1_ID, LIST2_ID, "all"}:
        chosen: list[dict[str, Any]] = []
        ids = (LIST1_ID, LIST2_ID) if list_id == "all" else (list_id,)
        for item in ids:
            rows = contracts_for(item, list2_path=list2_path)
            if address:
                want = address.lower()
                match = [row for row in rows if row["address"] == want]
                if match:
                    hit = dict(match[0])
                    hit["deep_lane"] = True
                    chosen.append(hit)
                continue
            chosen.extend(row for row in rows if row["deep_lane"])
        if address and not chosen:
            chosen.append({
                "address": address.lower(),
                "protocol": "on-demand",
                "est_usd_held": 0.0,
                "tier": 99,
                "candidate_reason": "on-demand",
                "drain_probability": 0.0,
                "contract_class": "",
                "list_id": None if list_id == "all" else list_id,
                "source": "on-demand",
                "fixture": None,
                "deep_lane": True,
                "bucket": "no",
            })
        return chosen
    raise ValueError("unknown list %s" % list_id)


def page_contracts(
    list_id: str,
    *,
    offset: int = 0,
    limit: int = 40,
    list2_path: Optional[Path | str] = None,
) -> dict[str, Any]:
    rows = contracts_for(list_id, list2_path=list2_path)
    start = max(0, int(offset))
    size = max(1, min(100, int(limit)))
    meta = dict(LIST_META[list_id])
    return {
        "list": meta,
        "total": len(rows),
        "offset": start,
        "limit": size,
        "deep_count": sum(1 for row in rows if row["deep_lane"]),
        "contracts": rows[start:start + size],
    }


def catalog(*, list2_path: Optional[Path | str] = None) -> dict[str, Any]:
    from eth_scanner.deep.blend.versions import pins_public

    list2, dropped = load_list2(list2_path)
    list1 = _list1_rows()
    lists = []
    for list_id, rows in ((LIST1_ID, list1), (LIST2_ID, list2)):
        meta = dict(LIST_META[list_id])
        meta["count"] = len(rows)
        meta["deep_count"] = sum(1 for row in rows if row["deep_lane"])
        if list_id == LIST2_ID:
            meta["dropped_out_of_band"] = dropped
        lists.append(meta)
    return {"ok": True, "lists": lists, "pins": pins_public()}
