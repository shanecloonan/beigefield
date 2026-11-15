"""Named master lists. Read-only selection — no exploit or attack logic.

List 1 is the funded, credible-but-less-audited curated feed
(``master_candidates.json`` plus the hand-ranked overlay). Its scan order
stays drain-probability, then tier, then dollars. Bounds are the list's own
min/max ($2,000–$9,000,000 in the committed config).

List 2 is the junk-drawer / sketchy-contract list. It is a different build:
small-dollar contracts only, no big names, no canonical protocols. Ranking
favors abandoned, unaudited, odd-pattern, or previously-hacked lineage.
Dollars are a membership test, not the sort key.

When ``list2_candidates.json`` (or ``.csv``, same shape as
``hand_ranked_candidates``) is present under ``eth-scanner/data/`` or the
bot store, List 2 loads that file and then applies this filter. Until that
file exists, List 2 is seeded from ``excluded.csv`` rows dropped for the old
sub-$2,000 floor. Addresses are never invented.

Live range checks read min/max from the list a contract belongs to
(``data/lists.json``). Heat promotion thresholds are unchanged.
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from eth_scanner.feed.master_list import (
    MasterCandidate,
    _from_raw,
    load_master_candidates,
)

LIST1_ID = "list-1"
LIST2_ID = "list-2"
ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")

_CACHE: dict[str, Any] = {}


def data_dir() -> Path:
    env = (os.environ.get("ETH_SCANNER_DATA_DIR") or "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    return here.parents[3] / "data"


def lists_config_path() -> Path:
    env = (os.environ.get("ETH_SCANNER_LISTS_JSON") or "").strip()
    if env:
        return Path(env)
    return data_dir() / "lists.json"


def manual_path() -> Path:
    env = (os.environ.get("ETH_SCANNER_LIST_MANUAL") or "").strip()
    if env:
        return Path(env)
    return data_dir() / "lists" / "manual.json"


def clear_list_cache() -> None:
    _CACHE.clear()


@dataclass
class ListConfig:
    id: str
    name: str
    strategy: str
    summary: str
    min_funds_usd: float
    max_funds_usd: float


@dataclass
class NamedList:
    config: ListConfig
    candidates: list[MasterCandidate]
    source: str
    source_path: str = ""
    total_usd: float = 0.0
    manual_count: int = 0

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name


@dataclass
class List2Rules:
    below_floor_marker: str = "below-2000"
    exclude_reason_markers: list[str] = field(default_factory=list)
    exclude_name_substrings: list[str] = field(default_factory=list)
    exclude_exact_names: list[str] = field(default_factory=list)
    generic_labels: list[str] = field(default_factory=list)
    sketchy_weights: list[tuple[re.Pattern[str], int]] = field(default_factory=list)


def normalize_address(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if text.startswith("0x") and ADDRESS_RE.match(text):
        return text
    return ""


def normalize_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (raw or "").lower())


def load_lists_document() -> dict[str, Any]:
    path = lists_config_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("lists.json must be an object")
    return payload


def random_phase_enabled() -> bool:
    """Loop toggle. File default is on. ``ETH_SCANNER_RANDOM_SCAN`` overrides it."""
    env = os.environ.get("ETH_SCANNER_RANDOM_SCAN")
    if env is not None and str(env).strip() != "":
        return str(env).strip().lower() in {"1", "true", "yes", "on"}
    try:
        return bool(random_scan_config().get("enabled", True))
    except (OSError, ValueError, json.JSONDecodeError):
        return True


def random_scan_config() -> dict[str, Any]:
    """Operational random-scan params. The desk reads these; they are not code constants."""
    doc = load_lists_document()
    raw = doc.get("random_scan") if isinstance(doc.get("random_scan"), dict) else {}
    gap = raw.get("gap_ms", 8000)
    history = raw.get("history_cap", 20)
    session = raw.get("session_cap", 40)
    try:
        gap_ms = int(gap)
    except (TypeError, ValueError):
        gap_ms = 8000
    try:
        history_cap = int(history)
    except (TypeError, ValueError):
        history_cap = 20
    try:
        session_cap = int(session)
    except (TypeError, ValueError):
        session_cap = 40
    out: dict[str, Any] = {
        "enabled": raw.get("enabled", True) is not False,
        "gap_ms": gap_ms,
        "history_cap": max(1, history_cap),
        "session_cap": max(1, session_cap),
    }
    # Optional band for the random phase. Absent means "use the scanner floor".
    if "min_funds_usd" in raw and raw.get("min_funds_usd") not in (None, ""):
        try:
            out["min_funds_usd"] = float(raw.get("min_funds_usd"))
        except (TypeError, ValueError):
            pass
    if "max_funds_usd" in raw and raw.get("max_funds_usd") not in (None, ""):
        try:
            out["max_funds_usd"] = float(raw.get("max_funds_usd"))
        except (TypeError, ValueError):
            pass
    return out


def list_configs() -> list[ListConfig]:
    doc = load_lists_document()
    out: list[ListConfig] = []
    for raw in doc.get("lists") or []:
        if not isinstance(raw, dict):
            continue
        list_id = str(raw.get("id") or "").strip()
        if not list_id:
            continue
        out.append(ListConfig(
            id=list_id,
            name=str(raw.get("name") or list_id),
            strategy=str(raw.get("strategy") or ""),
            summary=str(raw.get("summary") or ""),
            min_funds_usd=float(raw.get("min_funds_usd") or 0),
            max_funds_usd=float(raw.get("max_funds_usd") or 0),
        ))
    return out


def get_list_config(list_id: str) -> ListConfig:
    wanted = (list_id or LIST1_ID).strip() or LIST1_ID
    for cfg in list_configs():
        if cfg.id == wanted:
            return cfg
    known = ", ".join(c.id for c in list_configs()) or "(none)"
    raise KeyError("unknown master list %s (known: %s)" % (wanted, known))


def list2_rules() -> List2Rules:
    doc = load_lists_document()
    raw = doc.get("list2_rules") if isinstance(doc.get("list2_rules"), dict) else {}
    weights: list[tuple[re.Pattern[str], int]] = []
    for row in raw.get("sketchy_weights") or []:
        if not isinstance(row, dict):
            continue
        pattern = str(row.get("pattern") or "").strip()
        if not pattern:
            continue
        try:
            weight = int(row.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        weights.append((re.compile(pattern, re.I), weight))
    return List2Rules(
        below_floor_marker=str(raw.get("below_floor_marker") or "below-2000"),
        exclude_reason_markers=[str(x) for x in (raw.get("exclude_reason_markers") or [])],
        exclude_name_substrings=[normalize_name(str(x)) for x in (raw.get("exclude_name_substrings") or []) if normalize_name(str(x))],
        exclude_exact_names=[normalize_name(str(x)) for x in (raw.get("exclude_exact_names") or []) if normalize_name(str(x))],
        generic_labels=[normalize_name(str(x)) for x in (raw.get("generic_labels") or [])],
        sketchy_weights=weights,
    )


def is_big_or_canonical_name(protocol: str, slug: str, rules: Optional[List2Rules] = None) -> bool:
    """Household protocols and canonical venues. List 2 leaves these out."""
    rules = rules or list2_rules()
    for side in (normalize_name(protocol), normalize_name(slug)):
        if not side:
            continue
        if side in rules.exclude_exact_names:
            return True
        for sub in rules.exclude_name_substrings:
            if sub and sub in side:
                return True
    return False


def reason_is_excluded(reason: str, rules: Optional[List2Rules] = None) -> bool:
    rules = rules or list2_rules()
    low = (reason or "").lower()
    return any(marker.lower() in low for marker in rules.exclude_reason_markers)


def sketchy_score(blob: str, protocol: str, rules: Optional[List2Rules] = None) -> int:
    """Higher means more junk-drawer / sketchy. This is not List 1's drain sort."""
    rules = rules or list2_rules()
    score = 0
    for pattern, weight in rules.sketchy_weights:
        if pattern.search(blob or ""):
            score += weight
    label = normalize_name(protocol)
    if label and label not in set(rules.generic_labels):
        score += 10
    else:
        score += 1
    return score


def _sketchy_blob(row: MasterCandidate) -> str:
    return " ".join(
        part for part in (
            row.protocol,
            row.slug,
            row.category,
            row.candidate_reason,
            row.evidence_note,
            row.contract_class,
            row.source,
            row.audits,
            row.label,
            row.forked_from or "",
        ) if part
    )


def rank_sketchy(rows: list[MasterCandidate], rules: Optional[List2Rules] = None) -> list[MasterCandidate]:
    """List 2 order: sketchy traits, then name, then address. Not by dollars."""
    rules = rules or list2_rules()
    scored: list[tuple[int, str, str, int, MasterCandidate]] = []
    for index, row in enumerate(rows):
        score = sketchy_score(_sketchy_blob(row), row.protocol, rules)
        scored.append((score, (row.protocol or "").lower(), row.address, index, row))
    scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return [item[4] for item in scored]


def in_band(usd: float, cfg: ListConfig) -> bool:
    return float(cfg.min_funds_usd) <= float(usd) <= float(cfg.max_funds_usd)


def select_list2(rows: list[MasterCandidate], cfg: ListConfig, *, from_excluded: bool) -> list[MasterCandidate]:
    """List 2 filter. Distinct from List 1, which keeps the curated feed as committed."""
    rules = list2_rules()
    kept: list[MasterCandidate] = []
    seen: set[str] = set()
    for row in rows:
        if row.address in seen:
            continue
        if from_excluded:
            reason = row.candidate_reason or ""
            if rules.below_floor_marker.lower() not in reason.lower():
                continue
            if not in_band(row.est_usd_held, cfg):
                continue
        elif row.est_usd_held > 0 and not in_band(row.est_usd_held, cfg):
            continue
        if reason_is_excluded(row.candidate_reason, rules):
            continue
        if is_big_or_canonical_name(row.protocol, row.slug, rules):
            continue
        seen.add(row.address)
        kept.append(row)
    return rank_sketchy(kept, rules)


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        raw_rows = payload.get("candidates") or payload.get("rows") or []
    elif isinstance(payload, list):
        raw_rows = payload
    else:
        return []
    return [row for row in raw_rows if isinstance(row, dict)]


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _candidates_from_rows(raw_rows: list[dict[str, Any]]) -> list[MasterCandidate]:
    out: list[MasterCandidate] = []
    for raw in raw_rows:
        if "candidate_reason" not in raw and raw.get("excluded_reason"):
            raw = dict(raw)
            raw["candidate_reason"] = raw.get("excluded_reason")
        row = _from_raw(raw)
        if row is not None:
            out.append(row)
    return out


def _list2_candidate_paths() -> list[Path]:
    env = (os.environ.get("ETH_SCANNER_LIST2") or "").strip()
    roots = [data_dir(), data_dir() / "lists", Path("/cursor/stores/bot/scanner-list")]
    paths: list[Path] = []
    if env:
        paths.append(Path(env))
    for root in roots:
        paths.append(root / "list2_candidates.json")
        paths.append(root / "list2_candidates.csv")
    return paths


def _find_list2_file() -> Optional[Path]:
    for path in _list2_candidate_paths():
        if path.is_file():
            return path
    return None


def _load_table(path: Path) -> list[MasterCandidate]:
    if path.suffix.lower() == ".csv":
        return _candidates_from_rows(_read_csv_rows(path))
    return _candidates_from_rows(_read_json_rows(path))


def load_manual_addresses() -> dict[str, list[str]]:
    path = manual_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in payload.items():
        addrs: list[str] = []
        seen: set[str] = set()
        rows = value if isinstance(value, list) else []
        for item in rows:
            raw = item.get("address") if isinstance(item, dict) else item
            addr = normalize_address(str(raw or ""))
            if not addr or addr in seen:
                continue
            seen.add(addr)
            addrs.append(addr)
        out[str(key)] = addrs
    return out


def _manual_candidates(addresses: list[str]) -> list[MasterCandidate]:
    rows: list[MasterCandidate] = []
    for addr in addresses:
        rows.append(MasterCandidate(
            address=addr,
            protocol="Manual",
            slug="manual",
            category="manual",
            est_usd_held=0.0,
            candidate_reason="manual-entry",
            tier=99,
            rank=10**9,
            source="manual",
            evidence_note="Added on the list config or from the /test form.",
        ))
    return rows


def _merge_manual(base: list[MasterCandidate], list_id: str) -> tuple[list[MasterCandidate], int]:
    extra = load_manual_addresses().get(list_id) or []
    if not extra:
        return base, 0
    seen = {row.address for row in base}
    added = [row for row in _manual_candidates(extra) if row.address not in seen]
    # Manual entries stay visible at the front. They are not re-ranked.
    return added + base, len(added)


def load_named_list(list_id: str = LIST1_ID) -> NamedList:
    cfg = get_list_config(list_id)
    if cfg.id == LIST2_ID:
        found = _find_list2_file()
        if found is not None:
            rows = select_list2(_load_table(found), cfg, from_excluded=False)
            source = "list2_candidates"
            source_path = str(found)
        else:
            excluded = data_dir() / "excluded.csv"
            rows = select_list2(_load_table(excluded), cfg, from_excluded=True) if excluded.is_file() else []
            source = "excluded_fallback"
            source_path = str(excluded)
    else:
        # List 1 contents stay the curated feed. Bounds apply at scan time.
        rows = load_master_candidates()
        source = "master_candidates"
        source_path = str(data_dir() / "master_candidates.json")
    merged, manual_count = _merge_manual(rows, cfg.id)
    total = round(sum(float(row.est_usd_held or 0) for row in merged), 2)
    return NamedList(
        config=cfg,
        candidates=merged,
        source=source,
        source_path=source_path,
        total_usd=total,
        manual_count=manual_count,
    )


def bounds_for_list(list_id: str) -> tuple[float, float]:
    cfg = get_list_config(list_id)
    return cfg.min_funds_usd, cfg.max_funds_usd


def _membership() -> dict[str, list[tuple[str, float, float]]]:
    cached = _CACHE.get("membership")
    if isinstance(cached, dict):
        return cached
    mapping: dict[str, list[tuple[str, float, float]]] = {}
    for cfg in list_configs():
        try:
            named = load_named_list(cfg.id)
        except (OSError, ValueError, KeyError):
            continue
        for row in named.candidates:
            mapping.setdefault(row.address, []).append((cfg.id, cfg.min_funds_usd, cfg.max_funds_usd))
    _CACHE["membership"] = mapping
    return mapping


def bounds_for_address(address: str) -> Optional[tuple[float, float]]:
    """Range for a contract that sits on exactly one list. Several lists: caller must say which."""
    addr = normalize_address(address)
    if not addr:
        return None
    hits = _membership().get(addr) or []
    if len(hits) != 1:
        return None
    _list_id, low, high = hits[0]
    return low, high


def cursor_id_for(list_id: str) -> str:
    """List 1 keeps the existing master-list cursor. Other lists get their own."""
    if (list_id or LIST1_ID) in {"", LIST1_ID}:
        return "master-list"
    safe = re.sub(r"[^a-z0-9-]+", "-", list_id.lower()).strip("-")
    return "master-list-%s" % safe


def dedupe_key_for(list_id: str, address: str) -> str:
    addr = normalize_address(address)
    if (list_id or LIST1_ID) in {"", LIST1_ID}:
        return "master-list:%s" % addr
    return "master-list:%s:%s" % (list_id, addr)


def _blend_row(row: MasterCandidate, list_id: str, *, deep_lane: bool) -> dict[str, Any]:
    """Shape Blend already consumes. Heat rules are not applied here."""
    return {
        "address": row.address,
        "protocol": row.protocol,
        "est_usd_held": float(row.est_usd_held or 0.0),
        "tier": int(row.tier or 99),
        "candidate_reason": row.candidate_reason,
        "drain_probability": float(row.drain_probability or 0.0),
        "contract_class": row.contract_class,
        "list_id": list_id,
        "source": row.source,
        "fixture": None,
        "deep_lane": bool(deep_lane),
        "bucket": "no",
    }


def list_meta(list_id: str) -> dict[str, Any]:
    """Bounds come from data/lists.json. List 2 stays the sketchy junk-drawer."""
    cfg = get_list_config(list_id)
    kind = "sketchy" if cfg.id == LIST2_ID else "funded-curated"
    return {
        "id": cfg.id,
        "name": cfg.name,
        "kind": kind,
        "blurb": cfg.summary,
        "min_usd": cfg.min_funds_usd,
        "max_usd": cfg.max_funds_usd,
    }


def load_list2(path: Optional[Path | str] = None) -> tuple[list[dict[str, Any]], int]:
    """In-band List 2 rows for Blend, plus how many file rows fell outside the band.

    Every kept row is a deep-lane candidate. The production file is the
    live-verified sketchy feed. A caller can pass another file in tests.
    """
    cfg = get_list_config(LIST2_ID)
    src = Path(path) if path else (_find_list2_file() or (data_dir() / "list2_candidates.json"))
    parsed = _load_table(src) if src.is_file() else []
    dropped = 0
    inside: list[MasterCandidate] = []
    for row in parsed:
        if row.est_usd_held > 0 and not in_band(row.est_usd_held, cfg):
            dropped += 1
            continue
        inside.append(row)
    ranked = select_list2(inside, cfg, from_excluded=False)
    return [_blend_row(row, LIST2_ID, deep_lane=True) for row in ranked], dropped


def _list1_rows() -> list[dict[str, Any]]:
    from eth_scanner.deep.strong import is_strong_candidate

    rows: list[dict[str, Any]] = []
    for cand in load_master_candidates():
        deep = is_strong_candidate(
            tier=cand.tier,
            funds_usd=cand.est_usd_held,
            heat=0,
            bucket=None,
            drain_probability=cand.drain_probability,
        )
        rows.append(_blend_row(cand, LIST1_ID, deep_lane=deep))
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
    """Deep-lane rows. An explicit address is kept even when it is not strong."""
    if list_id not in {LIST1_ID, LIST2_ID, "all"}:
        raise ValueError("unknown list %s" % list_id)
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
    meta = list_meta(list_id)
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
    lists: list[dict[str, Any]] = []
    for item, rows in ((LIST1_ID, list1), (LIST2_ID, list2)):
        meta = list_meta(item)
        meta["count"] = len(rows)
        meta["deep_count"] = sum(1 for row in rows if row["deep_lane"])
        if item == LIST2_ID:
            meta["dropped_out_of_band"] = dropped
        lists.append(meta)
    return {"ok": True, "lists": lists, "pins": pins_public()}


def append_manual_address(list_id: str, address: str) -> tuple[bool, str]:
    """Validate, dedupe, and append to the per-list manual file. Code edits of that file work too."""
    cfg = get_list_config(list_id)
    addr = normalize_address(address)
    if not addr:
        return False, "Enter a 0x address with 40 hex characters."
    named = load_named_list(cfg.id)
    if any(row.address == addr for row in named.candidates):
        return False, "That address is already on %s." % cfg.name
    path = manual_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_manual_addresses()
    rows = list(current.get(cfg.id) or [])
    rows.append(addr)
    current[cfg.id] = rows
    # Preserve other lists already in the file.
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if isinstance(existing, dict):
            for key, value in existing.items():
                current.setdefault(str(key), value if isinstance(value, list) else [])
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    clear_list_cache()
    return True, addr
