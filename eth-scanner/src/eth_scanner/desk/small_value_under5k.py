"""Under-$5k high-likelihood queue for the signal-rerun job.

The historical rerun spends its clock on the hottest stored signals.
This queue is the contracts that already match the scanner's clone-class
and unverified-leftover rules, hold under $5,000 of native ETH plus the
major tokens the funds probe prices, and are not already in the first
small-value queue. One run takes the next batch only, and the Alchemy
proxy cap stays on that batch.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from eth_scanner.desk.signal_rerun import PER_CONTRACT_CU, load_seen, safe_address

FUNDS_MIN_USD = 100.0
FUNDS_MAX_USD = 5000.0
QUEUE_LIMIT = 300
SMALL_VALUE_BATCH = 75
# One batch stays near the measured ~2,600 CU per contract.
# 75 * 2,600 = 195,000, under this ceiling and under one historical 4M run.
SMALL_VALUE_BATCH_CU = 250_000
_CHUNK = 80

# First match wins. Scores sit in the same bands as the first small-value queue.
# A structural class outranks a bare unverified leftover (score 35 there).
REASON_SCORE = {
    "clone-proxy-takeover": 48,
    "clone-spot-oracle": 45,
    "clone-erc4626-inflation": 46,
    "lending-underscanned": 44,
    "amm-fork-thin-pool": 38,
    "unverified-leftover": 35,
}
REASON_PEAK = {
    "clone-proxy-takeover": 5,
    "clone-spot-oracle": 5,
    "clone-erc4626-inflation": 4,
    "lending-underscanned": 4,
    "amm-fork-thin-pool": 4,
    "unverified-leftover": 3,
}
# Major-token and router addresses. They are not custody targets.
NEVER_ADDRESSES = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
    "0x6b175474e89094c44da98b954eedeac495271d0f",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
    "0xca11bde05977b3631167028862be2a173976ca11",
    "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f",
    "0x1f98431c8ad98523631ae4a59f267346ea31f984",
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "0xe592427a0aece92de3edee1f18e0157c05861564",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
}

_CHAIN = re.compile(r"chain=([a-z0-9]+)")
_SIGNALS = re.compile(r"signals=([^;]*)")


def queue_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "small_value_under5k_queue.json"


def data_dir() -> Path:
    return queue_path().parent


def desk_dir() -> Path:
    return Path(__file__).resolve().parent


def assign_reason(signals: list[str], *, unverified: bool, family: str) -> str:
    """Pick the clone class the first small-value queue already used.

    Upgradeable, oracle, vault, and lending are the structural signals on
    the candidate rows. ERC-4626, Rari, Percent, and univ2-fork names are
    the same classes when the row was only tagged by protocol name.
    A decompilable contract with none of those is the unverified leftover.
    """
    sigs = {str(item).strip().lower() for item in signals if str(item).strip()}
    fam = (family or "").strip().lower()
    if "upgradeable" in sigs:
        return "clone-proxy-takeover"
    if "oracle" in sigs:
        return "clone-spot-oracle"
    if "vault" in sigs or fam == "erc4626":
        return "clone-erc4626-inflation"
    if "lending" in sigs or fam in {"rari", "percent"}:
        return "lending-underscanned"
    if fam == "univ2" or "amm" in sigs:
        return "amm-fork-thin-pool"
    if unverified:
        return "unverified-leftover"
    return ""


def family_from_protocol(name: str) -> str:
    text = (name or "").strip().lower()
    if text == "erc-4626 vault":
        return "erc4626"
    if text == "rari capital":
        return "rari"
    if text == "percent finance":
        return "percent"
    if text == "univ2-fork-unknown":
        return "univ2"
    return ""


def score_of(reason: str, *, unverified: bool) -> int:
    base = REASON_SCORE.get(reason, 0)
    if base and unverified and reason != "unverified-leftover":
        return base + 1
    return base


def peak_of(reason: str) -> int:
    return int(REASON_PEAK.get(reason, 0))


def _signals(reason: str) -> list[str]:
    match = _SIGNALS.search(reason or "")
    if not match:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip() and part.strip() != "—"]


def _chain(reason: str) -> str:
    match = _CHAIN.search(reason or "")
    return match.group(1) if match else ""


def _unverified(reason: str) -> bool:
    text = reason or ""
    return "decompilable" in text or "unverified" in text


def _funds(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _load_block(data: Path, desk: Path) -> set[str]:
    blocked: set[str] = set(NEVER_ADDRESSES)
    queue = json.loads((data / "small_value_queue.json").read_text(encoding="utf-8"))
    for row in queue.get("entries") or []:
        addr = safe_address(row.get("address"))
        if addr:
            blocked.add(addr)
    seed = json.loads((desk / "signal_rerun_seed.json").read_text(encoding="utf-8"))
    for row in seed if isinstance(seed, list) else []:
        addr = safe_address(row.get("address"))
        if addr:
            blocked.add(addr)
    blocked |= load_seen()
    hand_path = data / "excluded_hand.json"
    if hand_path.is_file():
        hand = json.loads(hand_path.read_text(encoding="utf-8"))
        for row in hand if isinstance(hand, list) else []:
            addr = safe_address(row.get("address") if isinstance(row, dict) else "")
            if addr:
                blocked.add(addr)
    return blocked


def _name_rules(data: Path) -> tuple[list[str], set[str]]:
    payload = json.loads((data / "lists.json").read_text(encoding="utf-8"))
    rules = payload.get("list2_rules") or {}
    substrings = [str(item).lower() for item in rules.get("exclude_name_substrings") or []]
    exact = {_compact(str(item)) for item in rules.get("exclude_exact_names") or []}
    return substrings, exact


def _excluded_name(name: str, substrings: list[str], exact: set[str]) -> bool:
    compact = _compact(name)
    if compact in exact:
        return True
    return any(item.replace(" ", "") in compact for item in substrings)


def collect_repo_candidates(data: Path | None = None, desk: Path | None = None) -> list[dict[str, Any]]:
    """Ethereum rows under $5k that are not already queued or named as canonical."""
    data = data or data_dir()
    desk = desk or desk_dir()
    blocked = _load_block(data, desk)
    substrings, exact = _name_rules(data)
    rows: list[dict[str, Any]] = []

    def add(raw: dict[str, Any]) -> None:
        addr = safe_address(raw.get("address"))
        if not addr or addr in blocked:
            return
        funds = _funds(raw.get("funds_usd"))
        if funds is None or funds < FUNDS_MIN_USD or funds >= FUNDS_MAX_USD:
            return
        name = str(raw.get("contract_name") or "")
        if _excluded_name(name, substrings, exact):
            return
        try:
            drain = float(raw.get("drain_probability") or 0)
        except (TypeError, ValueError):
            drain = 0.0
        if drain < 0:
            return
        rows.append({
            "address": addr,
            "contract_name": name,
            "funds_usd": funds,
            "signals": list(raw.get("signals") or []),
            "unverified": bool(raw.get("unverified")),
            "family": str(raw.get("family") or ""),
            "list": str(raw.get("list") or ""),
            "source": str(raw.get("source") or ""),
            "drain_probability": drain,
        })

    for row in json.loads((data / "master_candidates.json").read_text(encoding="utf-8")):
        reason = str(row.get("candidate_reason") or "")
        if _chain(reason) not in {"ethereum", "eth", "mainnet"}:
            continue
        add({
            "address": row.get("address"),
            "contract_name": row.get("protocol") or "",
            "funds_usd": row.get("est_usd_held"),
            "signals": _signals(reason),
            "unverified": _unverified(reason),
            "family": family_from_protocol(str(row.get("protocol") or "")),
            "list": "list-1",
            "source": "candidate-pool",
            "drain_probability": row.get("drain_probability") or 0,
        })
    for row in json.loads((data / "list2_candidates.json").read_text(encoding="utf-8")):
        reason = str(row.get("candidate_reason") or "")
        if _chain(reason) not in {"ethereum", "eth", "mainnet"}:
            continue
        add({
            "address": row.get("address"),
            "contract_name": row.get("protocol") or "",
            "funds_usd": row.get("funds_usd"),
            "signals": _signals(reason),
            "unverified": _unverified(reason),
            "family": family_from_protocol(str(row.get("protocol") or "")),
            "list": "list-2",
            "source": "candidate-pool",
            "drain_probability": row.get("drain_probability") or 0,
        })

    # Rows dropped only for the old list-1 floor. Same ETH funds probe.
    # Keep one address. A later reading at or above $5k drops it.
    excluded_best: dict[str, dict[str, Any]] = {}
    excluded_drop: set[str] = set()
    with (data / "excluded.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("excluded_reason") or "") != "below-2000-usd-priced":
                funds = _funds(row.get("est_usd_held"))
                addr = safe_address(row.get("address"))
                if addr and funds is not None and funds >= FUNDS_MAX_USD:
                    excluded_drop.add(addr)
                continue
            addr = safe_address(row.get("address"))
            funds = _funds(row.get("est_usd_held"))
            if not addr or funds is None:
                continue
            if funds >= FUNDS_MAX_USD:
                excluded_drop.add(addr)
                excluded_best.pop(addr, None)
                continue
            if addr in excluded_drop:
                continue
            current = excluded_best.get(addr)
            if current is None or funds > float(current["funds_usd"]):
                excluded_best[addr] = {
                    "address": addr,
                    "contract_name": row.get("protocol") or "",
                    "funds_usd": funds,
                    "signals": [],
                    "unverified": False,
                    "family": family_from_protocol(str(row.get("protocol") or "")),
                    "list": "excluded-below-2000",
                    "source": "excluded-below-2000",
                    "drain_probability": 0,
                }
    seen_addr = {str(row["address"]) for row in rows}
    for addr, row in excluded_best.items():
        if addr in seen_addr or addr in excluded_drop:
            continue
        add(row)
    return rows


def rank_candidates(
    rows: list[dict[str, Any]],
    *,
    limit: int = QUEUE_LIMIT,
    blocked: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Highest clone-class score first, then smaller funds. Cap is the queue size."""
    skip = blocked or set()
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        addr = safe_address(row.get("address"))
        if not addr or addr in skip or addr in seen:
            continue
        funds = _funds(row.get("funds_usd"))
        if funds is None or funds < FUNDS_MIN_USD or funds >= FUNDS_MAX_USD:
            continue
        signals = [str(item) for item in (row.get("signals") or [])]
        unverified = bool(row.get("unverified"))
        family = str(row.get("family") or "")
        reason = assign_reason(signals, unverified=unverified, family=family)
        if not reason:
            continue
        seen.add(addr)
        ranked.append({
            "address": addr,
            "chain": "ethereum",
            "contract_name": str(row.get("contract_name") or ""),
            "funds_usd": funds,
            "reason_class": reason,
            "score": score_of(reason, unverified=unverified),
            "peak_heat": peak_of(reason),
            "signals": signals,
            "unverified": unverified,
            "family": family,
            "list": str(row.get("list") or ""),
            "source": str(row.get("source") or ""),
        })
    ranked.sort(key=lambda item: (-int(item["score"]), float(item["funds_usd"]), item["address"]))
    cap = max(0, int(limit))
    return ranked[:cap], ranked[cap:]


def load_queue_entries() -> list[dict[str, Any]]:
    path = queue_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    rows = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        addr = safe_address(item.get("address"))
        if not addr:
            continue
        rows.append(dict(item, address=addr, chain="ethereum"))
    return rows


def as_signal_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Shape the historical rerun already scans. Peak is prior evidence, not new heat."""
    peak = peak_of(str(entry.get("reason_class") or "")) or int(entry.get("peak_heat") or 0)
    address = safe_address(entry.get("address"))
    name = str(entry.get("contract_name") or "")
    return {
        "chain": "ethereum",
        "address": address,
        "peak": peak,
        "reasons": [str(entry.get("reason_class") or "")],
        "name": name,
        "signal": True,
        "latest": {
            "chain": "ethereum",
            "address": address,
            "heat": 0,
            "blend_heat": 0,
            "blend_bucket": "",
            "heat_breakdown": {"original_peak": peak} if peak else {},
            "contract_name": name,
            "created_at": "1970-01-01T00:00:00Z",
        },
    }


def take_batch(
    entries: list[dict[str, Any]],
    *,
    skip: set[str],
    batch_size: int,
    budget_cu: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Next unscanned prefix that fits the batch size and the CU ceiling.

    Returns the selected queue entries, the deferred entries, and the proxy cap.
    """
    size = max(0, int(batch_size))
    room = min(max(0, int(budget_cu)), SMALL_VALUE_BATCH_CU)
    estimate = size * PER_CONTRACT_CU
    select_cap = min(room, estimate) if size else 0
    proxy_cap = min(room, estimate + PER_CONTRACT_CU * 4) if size else 0
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    spent = 0
    for entry in entries:
        addr = safe_address(entry.get("address"))
        if not addr or addr in skip:
            continue
        over_size = len(selected) >= size
        over_cu = spent + PER_CONTRACT_CU > select_cap
        if over_size or over_cu:
            deferred.append({
                "chain": "ethereum",
                "address": addr,
                "peak": int(entry.get("peak_heat") or 0),
                "reason": "batch" if over_size else "cu budget",
            })
            continue
        selected.append(dict(entry, address=addr))
        spent += PER_CONTRACT_CU
    return selected, deferred, proxy_cap


def finished_addresses(store: Any, addresses: list[str]) -> tuple[set[str], str]:
    """Addresses this job already wrote as done. The next batch starts after them."""
    wanted = {addr for addr in (safe_address(item) for item in addresses) if addr}
    done: set[str] = set()
    for row in getattr(store, "test_runs", None) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("discovery_source") or "") != "signal_rerun":
            continue
        if str(row.get("status") or "") != "done":
            continue
        addr = safe_address(row.get("address"))
        if addr in wanted:
            done.add(addr)
    req = getattr(store, "_req", None)
    if not callable(req):
        return done, ""
    note = ""
    pending = [addr for addr in addresses if addr not in done]
    for offset in range(0, len(pending), _CHUNK):
        chunk = pending[offset : offset + _CHUNK]
        if not chunk:
            continue
        query = {
            "select": "address,status,discovery_source",
            "address": "in.(%s)" % ",".join(chunk),
            "discovery_source": "eq.signal_rerun",
            "status": "eq.done",
            "limit": "1000",
        }
        try:
            rows = req("GET", "test_scan_runs", query=query)
        except Exception as exc:  # noqa: BLE001 — a missed lookup rescans the batch
            note = str(exc)[:180]
            break
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            addr = safe_address(row.get("address"))
            if addr in wanted:
                done.add(addr)
    return done, note


def prepare_batch(
    store: Any,
    *,
    budget_cu: int,
    batch_size: int = 0,
) -> dict[str, Any]:
    """Select the next under-$5k batch. Does not read the historical signal tables."""
    entries = load_queue_entries()
    size = int(batch_size) if int(batch_size or 0) > 0 else SMALL_VALUE_BATCH
    skip = set(load_seen())
    finished, err = finished_addresses(store, [str(row.get("address") or "") for row in entries])
    skip |= finished
    selected_entries, deferred, proxy_cap = take_batch(
        entries,
        skip=skip,
        batch_size=size,
        budget_cu=budget_cu,
    )
    notes = [
        "small-value under $%d batch, %d queued, %d already finished"
        % (int(FUNDS_MAX_USD), len(entries), len(finished)),
    ]
    if err:
        notes.append("finished lookup failed; this batch may repeat: " + err)
    selected = [as_signal_row(row) for row in selected_entries]
    plan = {
        "mode": "small-value-under5k",
        "rows_read": len(entries),
        "signals": len(entries),
        "queue": len(entries),
        "pending": len(entries) - len([row for row in entries if safe_address(row.get("address")) in skip]),
        "skipped_finished": len([row for row in entries if safe_address(row.get("address")) in skip]),
        "selected": len(selected),
        "deferred_budget": deferred,
        "other_chain": [],
        "notes": notes,
        "budget_cu": proxy_cap,
        "batch_size": size,
    }
    return {
        "selected": selected,
        "deferred": deferred,
        "budget_cu": proxy_cap,
        "plan": plan,
    }
