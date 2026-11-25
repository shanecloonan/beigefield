"""Fetch verified source from Sourcify, then Etherscan. Cache the text.

The same Sourcify response also keeps compiler metadata and the storage
layout. The API key never appears in the result. A failed lookup returns an
empty source and adds no heat. A layout is evidence for later checks, not a
finding by itself.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from eth_scanner.ingest.unpack import flatten_sources, parse_etherscan_sources
from eth_scanner.store.supabase import normalize_address

Fetch = Callable[[str], Any]
SOURCIFY = (
    "https://sourcify.dev/server/v2/contract/{chain_id}/{address}"
    "?fields=stdJsonInput,metadata,storageLayout"
)
MAX_SOURCE_CHARS = 1_500_000
MAX_SLOTS = 64


def _http_json(url: str, timeout_s: float = 12.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "beigefield-eth-scanner"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def solidity_from_payload(payload: Any) -> str:
    """Pull Solidity text out of a Sourcify or Etherscan body."""
    if isinstance(payload, str):
        return _cap(payload if _looks_like_source(payload) else "")
    if not isinstance(payload, dict):
        return ""
    std = payload.get("stdJsonInput")
    if isinstance(std, dict):
        return _from_sources(std.get("sources"))
    result = payload.get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        raw = str(result[0].get("SourceCode") or "")
        files = parse_etherscan_sources(raw)
        if files:
            return _cap(flatten_sources(files))
        return _cap(raw if _looks_like_source(raw) else "")
    if isinstance(payload.get("sources"), dict):
        return _from_sources(payload.get("sources"))
    return ""


def _from_sources(sources: Any) -> str:
    if not isinstance(sources, dict):
        return ""
    files: dict[str, str] = {}
    for path, spec in sources.items():
        content = spec.get("content") if isinstance(spec, dict) else spec
        if isinstance(content, str) and content.strip():
            files[str(path)] = content
    parsed = parse_etherscan_sources(json.dumps({"sources": {
        path: {"content": content} for path, content in files.items()
    }}))
    if parsed:
        return _cap(flatten_sources(parsed))
    return _cap(flatten_sources(files) if files else "")


def _looks_like_source(text: str) -> bool:
    head = text[:4000]
    return "pragma " in head or "contract " in head or "function " in head


def _cap(text: str) -> str:
    if len(text) <= MAX_SOURCE_CHARS:
        return text
    return text[:MAX_SOURCE_CHARS]


def _short(value: Any, limit: int = 80) -> str:
    return " ".join(str(value or "").split())[:limit]


def metadata_summary(payload: Any) -> dict[str, Any]:
    """Compiler and language only. Settings and bytecode stay out of the result."""
    empty = {"present": False, "language": "", "compiler": "", "contract": ""}
    if not isinstance(payload, dict):
        return empty
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    compilation = payload.get("compilation") if isinstance(payload.get("compilation"), dict) else {}
    compiler = ""
    if isinstance(meta.get("compiler"), dict):
        compiler = _short(meta["compiler"].get("version"))
    if not compiler:
        compiler = _short(compilation.get("compilerVersion") or compilation.get("compiler"))
    language = _short(meta.get("language") or compilation.get("language"), 40)
    contract = _short(compilation.get("name") or "")
    present = bool(compiler or language or meta)
    return {
        "present": present,
        "language": language,
        "compiler": compiler,
        "contract": contract,
    }


def storage_slots(payload: Any) -> list[dict[str, Any]]:
    """Slot, offset, label, and type. The types map itself is not stored."""
    if not isinstance(payload, dict):
        return []
    layout = payload.get("storageLayout") or payload.get("storage_layout")
    if not isinstance(layout, dict):
        return []
    types = layout.get("types") if isinstance(layout.get("types"), dict) else {}
    rows: list[dict[str, Any]] = []
    for item in list(layout.get("storage") or [])[:MAX_SLOTS]:
        if not isinstance(item, dict):
            continue
        type_id = item.get("type")
        type_name = type_id if isinstance(type_id, str) else ""
        spec = types.get(type_id) if isinstance(type_id, str) else None
        if isinstance(spec, dict) and spec.get("label"):
            type_name = str(spec.get("label"))
        try:
            offset = int(item.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        slot = _short(item.get("slot"), 66)
        if not slot and not item.get("label"):
            continue
        rows.append({
            "label": _short(item.get("label"), 80),
            "slot": slot,
            "offset": max(0, offset),
            "type": _short(type_name, 80),
        })
    return rows


def _cache_path(cache_dir: Path, address: str) -> Path:
    return cache_dir / ("%s.sol.json" % address)


def _read_cache(cache_dir: Optional[Path], address: str) -> Optional[dict[str, Any]]:
    if cache_dir is None:
        return None
    path = _cache_path(cache_dir, address)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not str(data.get("source") or "").strip():
        return None
    if "storage_layout" not in data or "metadata" not in data:
        return None
    data["cached"] = True
    data["address"] = address
    data["storage_layout"] = list(data.get("storage_layout") or [])
    data["metadata"] = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    data["heat_contribution"] = 0
    return data


def _write_cache(cache_dir: Optional[Path], row: dict[str, Any]) -> None:
    if cache_dir is None or not str(row.get("source") or "").strip():
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, str(row["address"]))
    path.write_text(json.dumps({
        "address": row["address"],
        "via": row.get("via") or "",
        "source": row.get("source") or "",
        "verified": True,
        "metadata": row.get("metadata") or {},
        "storage_layout": list(row.get("storage_layout") or []),
    }), encoding="utf-8")


def fetch_verified_source(
    address: str,
    *,
    chain_id: int = 1,
    cache_dir: Optional[Path] = None,
    fetch_json: Optional[Fetch] = None,
    etherscan_get: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """Return verified source text. Empty source on a miss. Never raises for I/O."""
    addr = normalize_address(address)
    cached = _read_cache(cache_dir, addr)
    if cached is not None:
        cached["heat_contribution"] = 0
        return cached
    report: dict[str, Any] = {
        "address": addr,
        "source": "",
        "via": "",
        "verified": False,
        "cached": False,
        "metadata": {"present": False, "language": "", "compiler": "", "contract": ""},
        "storage_layout": [],
        "heat_contribution": 0,
        "note": "",
    }
    getter = fetch_json or _http_json
    try:
        payload = getter(SOURCIFY.format(chain_id=int(chain_id), address=addr))
        text = solidity_from_payload(payload)
        meta = metadata_summary(payload)
        slots = storage_slots(payload)
    except Exception as exc:  # noqa: BLE001 — a missed fetch is an empty source
        text = ""
        meta = report["metadata"]
        slots = []
        report["note"] = "sourcify unavailable (%s)" % type(exc).__name__
    if text.strip():
        report.update(
            source=text,
            via="sourcify",
            verified=True,
            note="",
            metadata=meta,
            storage_layout=slots,
        )
        _write_cache(cache_dir, report)
        return report
    if etherscan_get is not None:
        try:
            payload = etherscan_get(addr)
            text = solidity_from_payload(payload)
            meta = metadata_summary(payload)
            slots = storage_slots(payload)
        except Exception as exc:  # noqa: BLE001
            text = ""
            meta = report["metadata"]
            slots = []
            report["note"] = (report["note"] + "; etherscan unavailable (%s)" % type(exc).__name__).strip("; ")
        if text.strip():
            report.update(
                source=text,
                via="etherscan",
                verified=True,
                note="",
                metadata=meta,
                storage_layout=slots,
            )
            _write_cache(cache_dir, report)
            return report
    if not report["note"]:
        report["note"] = "no verified source"
    return report
