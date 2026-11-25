"""Read-only source lookup for one EVM chain.

Etherscan v2 is used when a key is already configured. Otherwise Sourcify's
public status endpoint is tried. A failure stays unknown. Nothing here is
heat, and the API key is never put in the result.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.chains.evm import evm_chain
from eth_scanner.ingest.etherscan import ETHERSCAN_V2

Fetch = Callable[[str], Any]
SOURCIFY = "https://sourcify.dev/server/v2/contract/{chain_id}/{address}"


def source_status(
    chain: str,
    address: str,
    *,
    fetch: Optional[Fetch] = None,
    api_key: str = "",
) -> dict[str, Any]:
    """Whether verified source is published. heat_contribution is 0."""
    cfg = evm_chain(chain)
    target = _address(address)
    report: dict[str, Any] = {
        "chain": cfg.name,
        "chain_id": cfg.chain_id,
        "address": target,
        "verified": None,
        "via": "unknown",
        "heat_contribution": 0,
        "note": "Source presence only. This stage adds no heat.",
    }
    if not target:
        report["note"] = "address was not a 20-byte account"
        return report
    key = (api_key or _first_key()).strip()
    try:
        if key:
            payload = _etherscan(cfg.chain_id, target, key, fetch)
            report["via"] = "etherscan-v2"
            report["verified"] = _etherscan_verified(payload)
        else:
            payload = _sourcify(cfg.chain_id, target, fetch)
            report["via"] = "sourcify"
            report["verified"] = _sourcify_verified(payload)
    except Exception as exc:  # noqa: BLE001
        report["verified"] = None
        report["via"] = "unknown"
        report["error"] = type(exc).__name__
    report["heat_contribution"] = 0
    return report


def _first_key() -> str:
    raw = os.environ.get("ETHERSCAN_API_KEYS") or os.environ.get("ETHERSCAN_API_KEY") or ""
    return raw.split(",")[0].strip()


def _address(value: str) -> str:
    text = (value or "").strip().lower()
    if len(text) == 42 and text.startswith("0x"):
        try:
            int(text[2:], 16)
        except ValueError:
            return ""
        return text
    return ""


def _etherscan(chain_id: int, address: str, key: str, fetch: Optional[Fetch]) -> Any:
    query = urllib.parse.urlencode({
        "chainid": chain_id,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": key,
    })
    return _load(ETHERSCAN_V2 + "?" + query, fetch)


def _sourcify(chain_id: int, address: str, fetch: Optional[Fetch]) -> Any:
    return _load(SOURCIFY.format(chain_id=chain_id, address=address), fetch)


def _load(url: str, fetch: Optional[Fetch]) -> Any:
    if fetch is not None:
        return fetch(url)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "beigefield-scanner"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _etherscan_verified(payload: Any) -> Optional[bool]:
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, list) and result:
        row = result[0] if isinstance(result[0], dict) else {}
        source = str(row.get("SourceCode") or "")
        name = str(row.get("ContractName") or "")
        if not source and not name:
            return False
        return bool(source.strip())
    if isinstance(payload, dict) and str(payload.get("message") or "").lower() == "notok":
        return None
    return None


def _sourcify_verified(payload: Any) -> Optional[bool]:
    if not isinstance(payload, dict):
        return None
    match = str(payload.get("match") or payload.get("status") or "").lower()
    if match in {"exact_match", "match", "perfect", "partial"}:
        return True
    if payload.get("match") is None and "match" in payload:
        return False
    if payload.get("error") or payload.get("message"):
        return False
    return None
