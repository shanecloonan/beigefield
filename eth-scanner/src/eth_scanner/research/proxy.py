"""EIP-1967 implementation resolution, legacy proxy slots, and diamond facet listing.

No weak proxy guesses. Facets come from an explicit list or a read-only
EIP-2535 loupe `eth_call` (`facetAddresses` / `facetFunctionSelectors` /
`facets`). If the surface looks like a diamond and neither source is
available, mark `diamond-facets-missing` and stop that path. Never guess
facet ABIs from bytecode or constructor literals.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from eth_scanner.heuristics.invariant_pass import strip_comments
from eth_scanner.research.keccak import selector4
from eth_scanner.research.types import FacetEntry
from eth_scanner.types import SourceArtifact

LoupeCall = Callable[[str, str], str]

# EIP-1967 implementation slot = bytes32(uint256(keccak256("eip1967.proxy.implementation")) - 1)
EIP1967_IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN_SLOT = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
# keccak256("org.zeppelinos.proxy.implementation") — OpenZeppelin proxies before EIP-1967.
OZ_LEGACY_IMPLEMENTATION_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"
# keccak256("PROXIABLE") — EIP-1822.
EIP1822_IMPLEMENTATION_SLOT = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"
_MAX_FOLLOW = 24
_DIAMOND_HINT = re.compile(
    r"\b(?:Diamond|LibDiamond|facetAddresses|diamondCut|IDiamondLoupe|IDiamondCut)\b",
)
_PROXY_HINT = re.compile(
    r"\b(?:upgradeToAndCall|upgradeTo|changeAdmin|AdminUpgradeabilityProxy|UpgradeabilityProxy)\b",
)

_DIAMOND_LOUPE_NAMES = frozenset({
    "facetaddresses", "facetaddress", "facets", "facetfunctionselectors", "diamondcut",
})
_ADDR_RX = re.compile(r"0x[a-fA-F0-9]{40}")


def _rpc_call(rpc_url: str, method: str, params: list[Any], timeout_s: float = 15.0) -> Any:
    from eth_scanner.ingest.rpc_client import rpc_call
    return rpc_call(rpc_url, method, params, timeout_s=timeout_s)

def eth_get_storage_at(rpc_url: str, address: str, slot: str, timeout_s: float = 15.0) -> str:
    """Read-only `eth_getStorageAt`. Never sends a transaction."""
    return str(_rpc_call(rpc_url, "eth_getStorageAt", [address, slot, "latest"], timeout_s) or "")


def storage_word_to_address(word: str) -> Optional[str]:
    raw = (word or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if not raw or set(raw) <= {"0"}:
        return None
    if len(raw) < 40:
        raw = raw.zfill(40)
    addr = "0x" + raw[-40:]
    if set(addr[2:]) <= {"0"}:
        return None
    return addr


def looks_like_diamond(source: str, abi: Optional[list[dict[str, Any]]] = None) -> bool:
    names: set[str] = set()
    if abi:
        for item in abi:
            if item.get("type") == "function":
                names.add(str(item.get("name") or "").lower())
    clean = strip_comments(source or "", "solidity")
    for n in _DIAMOND_LOUPE_NAMES:
        if n in names or re.search(r"\b%s\b" % n, clean, re.I):
            names.add(n)
    return bool(names & _DIAMOND_LOUPE_NAMES)


def resolve_implementation(
    artifact: Optional[SourceArtifact],
    *,
    address: str = "",
    rpc_url: str = "",
    get_storage: Optional[Callable[[str, str, str], str]] = None,
) -> tuple[Optional[str], str, list[str]]:
    """Return (implementation, source_tag, notes).

    Order: explorer-reported Implementation, then EIP-1967 slot via RPC.
    Never infers an impl from bytecode patterns.
    """
    notes: list[str] = []
    if artifact and artifact.implementation:
        impl = artifact.implementation.strip().lower()
        if impl.startswith("0x") and len(impl) == 42:
            notes.append("implementation from explorer/artifact (not a bytecode guess)")
            return impl, "explorer", notes

    if not rpc_url and get_storage is None:
        notes.append("no RPC and no explorer implementation — EIP-1967 not read")
        return None, "", notes

    reader = get_storage or (lambda addr, slot, _rpc=rpc_url: eth_get_storage_at(_rpc, addr, slot))
    try:
        word = reader(address, EIP1967_IMPLEMENTATION_SLOT)
    except (OSError, TimeoutError, RuntimeError, urllib.error.URLError, ValueError) as exc:
        notes.append("EIP-1967 eth_getStorageAt failed: %s" % exc)
        return None, "", notes
    impl = storage_word_to_address(word)
    if impl:
        notes.append("implementation from EIP-1967 slot (eth_getStorageAt)")
        return impl, "eip-1967", notes
    notes.append("EIP-1967 implementation slot empty or zero")
    return None, "", notes


def eth_call(rpc_url: str, address: str, data: str, timeout_s: float = 15.0) -> str:
    """Read-only `eth_call`. Never sends a transaction."""
    return str(_rpc_call(rpc_url, "eth_call", [{"to": address, "data": data}, "latest"], timeout_s) or "")


def _hex_bytes(data: str) -> bytes:
    raw = (data or "").strip().lower()
    if raw.startswith("0x"):
        raw = raw[2:]
    if len(raw) % 2:
        raw = "0" + raw
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return b""


def decode_address_array(data: str) -> list[str]:
    """ABI-decode a top-level `address[]` return (EIP-2535 facetAddresses)."""
    blob = _hex_bytes(data)
    if len(blob) < 64:
        return []
    offset = int.from_bytes(blob[0:32], "big")
    if offset + 32 > len(blob):
        return []
    length = int.from_bytes(blob[offset:offset + 32], "big")
    if length > 256:
        return []
    out: list[str] = []
    pos = offset + 32
    for _ in range(length):
        if pos + 32 > len(blob):
            break
        word = blob[pos:pos + 32]
        addr = "0x" + word[-20:].hex()
        if set(addr[2:]) - {"0"}:
            out.append(addr)
        pos += 32
    return out


def decode_bytes4_array(data: str) -> list[str]:
    """ABI-decode a top-level `bytes4[]` return (facetFunctionSelectors)."""
    blob = _hex_bytes(data)
    if len(blob) < 64:
        return []
    offset = int.from_bytes(blob[0:32], "big")
    if offset + 32 > len(blob):
        return []
    length = int.from_bytes(blob[offset:offset + 32], "big")
    if length > 2048:
        return []
    out: list[str] = []
    pos = offset + 32
    for _ in range(length):
        if pos + 32 > len(blob):
            break
        out.append("0x" + blob[pos:pos + 4].hex())
        pos += 32
    return out


def decode_facets_tuples(data: str) -> list[FacetEntry]:
    """Best-effort ABI-decode of EIP-2535 `facets()` → (address, bytes4[])[]."""
    blob = _hex_bytes(data)
    if len(blob) < 64:
        return []
    head_off = int.from_bytes(blob[0:32], "big")
    if head_off + 32 > len(blob):
        return []
    n = int.from_bytes(blob[head_off:head_off + 32], "big")
    if n > 256:
        return []
    base = head_off
    out: list[FacetEntry] = []
    for i in range(n):
        slot = base + 32 + i * 32
        if slot + 32 > len(blob):
            break
        elem_rel = int.from_bytes(blob[slot:slot + 32], "big")
        elem = base + elem_rel
        if elem + 64 > len(blob):
            continue
        addr = "0x" + blob[elem + 12:elem + 32].hex()
        sel_rel = int.from_bytes(blob[elem + 32:elem + 64], "big")
        sel_at = elem + sel_rel
        sels: list[str] = []
        if sel_at + 32 <= len(blob):
            count = int.from_bytes(blob[sel_at:sel_at + 32], "big")
            if count <= 2048:
                pos = sel_at + 32
                for _ in range(count):
                    if pos + 32 > len(blob):
                        break
                    sels.append("0x" + blob[pos:pos + 4].hex())
                    pos += 32
        if set(addr[2:]) - {"0"}:
            out.append(FacetEntry(address=addr, selectors=sels, source="loupe:facets"))
    return out


def encode_address_array(addresses: list[str]) -> str:
    """ABI-encode `address[]` (tests + fixtures)."""
    raw = (32).to_bytes(32, "big") + len(addresses).to_bytes(32, "big")
    for addr in addresses:
        h = addr[2:] if addr.startswith("0x") else addr
        raw += bytes(12) + bytes.fromhex(h.zfill(40)[-40:])
    return "0x" + raw.hex()


def encode_bytes4_array(selectors: list[str]) -> str:
    """ABI-encode `bytes4[]` (tests + fixtures)."""
    raw = (32).to_bytes(32, "big") + len(selectors).to_bytes(32, "big")
    for sel in selectors:
        h = sel[2:] if sel.startswith("0x") else sel
        raw += bytes.fromhex(h.ljust(8, "0")[:8]) + bytes(28)
    return "0x" + raw.hex()


def _calldata_noargs(signature: str) -> str:
    return selector4(signature)


def _calldata_address(signature: str, address: str) -> str:
    h = (address or "").lower()
    if h.startswith("0x"):
        h = h[2:]
    return selector4(signature) + h.zfill(64)


def fetch_loupe_facets(
    address: str,
    *,
    rpc_url: str = "",
    eth_call_fn: Optional[LoupeCall] = None,
) -> tuple[list[FacetEntry], list[str]]:
    """Read-only EIP-2535 loupe. Does not guess facet ABIs."""
    notes: list[str] = []
    caller = eth_call_fn
    if caller is None:
        if not rpc_url:
            return [], notes

        def caller(addr: str, data: str, _rpc: str = rpc_url) -> str:
            return eth_call(_rpc, addr, data)

    try:
        raw_addrs = caller(address, _calldata_noargs("facetAddresses()"))
        addrs = decode_address_array(raw_addrs)
    except (OSError, TimeoutError, RuntimeError, urllib.error.URLError, ValueError) as exc:
        notes.append("loupe facetAddresses() eth_call failed: %s" % exc)
        addrs = []

    if addrs:
        out: list[FacetEntry] = []
        for facet in addrs:
            sels: list[str] = []
            try:
                raw_sels = caller(address, _calldata_address("facetFunctionSelectors(address)", facet))
                sels = decode_bytes4_array(raw_sels)
            except (OSError, TimeoutError, RuntimeError, urllib.error.URLError, ValueError) as exc:
                notes.append("loupe facetFunctionSelectors(%s) failed: %s" % (facet, exc))
            out.append(FacetEntry(address=facet, selectors=sels, source="loupe:facetAddresses"))
        notes.append("diamond facets from read-only loupe facetAddresses() (%d)" % len(out))
        return out, notes

    try:
        raw_facets = caller(address, _calldata_noargs("facets()"))
        rows = decode_facets_tuples(raw_facets)
    except (OSError, TimeoutError, RuntimeError, urllib.error.URLError, ValueError) as exc:
        notes.append("loupe facets() eth_call failed: %s" % exc)
        rows = []
    if rows:
        notes.append("diamond facets from read-only loupe facets() (%d)" % len(rows))
        return rows, notes
    if not notes:
        notes.append("loupe returned no facet addresses")
    return [], notes


def list_diamond_facets(
    source: str,
    *,
    address: str = "",
    abi: Optional[list[dict[str, Any]]] = None,
    explicit_facets: Optional[list[dict[str, Any]]] = None,
    rpc_url: str = "",
    eth_call_fn: Optional[LoupeCall] = None,
) -> tuple[list[FacetEntry], Optional[str], list[str]]:
    """List facets from an explicit list or a loupe eth_call. Never guess.

    If the surface looks like a diamond/loupe and facets cannot be listed,
    return status `diamond-facets-missing` and an empty list.
    """
    notes: list[str] = []
    if explicit_facets:
        out: list[FacetEntry] = []
        for row in explicit_facets:
            addr = str(row.get("address") or "").strip().lower()
            if not addr:
                continue
            sels = [str(s) for s in (row.get("selectors") or [])]
            out.append(FacetEntry(address=addr, selectors=sels, source=str(row.get("source") or "explicit")))
        if out:
            notes.append("diamond facets taken from an explicit list (no guess)")
            return out, "listed", notes

    if not looks_like_diamond(source, abi):
        return [], None, notes

    stray = _ADDR_RX.findall(source or "")
    if stray:
        notes.append(
            "diamond loupe present; %d address literal(s) in source were not treated as facets"
            % len(stray)
        )

    if (rpc_url or eth_call_fn) and address:
        fetched, loupe_notes = fetch_loupe_facets(
            address, rpc_url=rpc_url, eth_call_fn=eth_call_fn,
        )
        notes.extend(loupe_notes)
        if fetched:
            return fetched, "listed", notes
        notes.append("loupe eth_call produced no facets — diamond-facets-missing")
        return [], "diamond-facets-missing", notes

    if not rpc_url and eth_call_fn is None:
        notes.append("ETH_RPC_URL unset — loupe eth_call not attempted")
    notes.append("diamond loupe/cut surface without an explicit facet list — diamond-facets-missing")
    return [], "diamond-facets-missing", notes


def _remember(found: list[str], seen: set[str], addr: Optional[str]) -> None:
    if not addr or len(found) >= _MAX_FOLLOW:
        return
    cleaned = addr.strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", cleaned):
        return
    if cleaned in seen or set(cleaned[2:]) <= {"0"}:
        return
    seen.add(cleaned)
    found.append(cleaned)


def follow_runtime_addresses(
    address: str,
    source: str,
    *,
    rpc_url: str = "",
    get_storage: Optional[Callable[[str, str], str]] = None,
    eth_call_fn: Optional[LoupeCall] = None,
) -> list[str]:
    """Implementation and facet addresses for a non-EIP-1967 proxy or a diamond.

    Read-only. A token source is not followed. EIP-1967 is a different path.
    At most 24 addresses, and no bytecode guessing.
    """
    text = strip_comments(source or "", "solidity")
    diamond = bool(_DIAMOND_HINT.search(text))
    proxy = bool(_PROXY_HINT.search(text))
    if not diamond and not proxy:
        return []
    if not rpc_url and get_storage is None and eth_call_fn is None:
        return []

    found: list[str] = []
    seen = {(address or "").strip().lower()}

    if proxy:
        reader = get_storage or (
            (lambda addr, slot, _rpc=rpc_url: eth_get_storage_at(_rpc, addr, slot))
            if rpc_url else None
        )
        if reader is not None:
            for slot in (OZ_LEGACY_IMPLEMENTATION_SLOT, EIP1822_IMPLEMENTATION_SLOT):
                try:
                    word = reader(address, slot)
                except (OSError, TimeoutError, RuntimeError, urllib.error.URLError, ValueError):
                    continue
                _remember(found, seen, storage_word_to_address(word))
        if not found:
            caller = eth_call_fn
            if caller is None and rpc_url:
                def caller(addr: str, data: str, _rpc: str = rpc_url) -> str:
                    return eth_call(_rpc, addr, data)
            if caller is not None:
                try:
                    raw = caller(address, _calldata_noargs("implementation()"))
                except (OSError, TimeoutError, RuntimeError, urllib.error.URLError, ValueError):
                    raw = ""
                _remember(found, seen, storage_word_to_address(raw))

    if diamond:
        facets, _notes = fetch_loupe_facets(address, rpc_url=rpc_url, eth_call_fn=eth_call_fn)
        for facet in facets:
            _remember(found, seen, facet.address)
    return found
