"""Read-only on-chain funds probe for the ETH scanner floor check.

Native ETH + major ERC-20 balances via Multicall3, optional ERC-4626
asset()/totalAssets() (and token()/underlying() getters), USD pricing with
a short in-process TTL cache. Never sends a transaction.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
AGGREGATE3_SELECTOR = "82ad56cb"
GET_ETH_BALANCE_SELECTOR = "4d2301cc"
BALANCE_OF_SELECTOR = "70a08231"
DECIMALS_SELECTOR = "313ce567"
ASSET_SELECTOR = "38d52e0f"
TOTAL_ASSETS_SELECTOR = "01e1d114"
TOKEN_SELECTOR = "fc0c546a"
UNDERLYING_SELECTOR = "6f307dc3"

# Mainnet major tokens (defensive funds-at-risk surface).
MAJOR_TOKENS: list[tuple[str, str, str, int | None]] = [
    # symbol, address, coingecko/llama id hint, known decimals (None → probe)
    ("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "ethereum", 18),
    ("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "usd-coin", 6),
    ("USDT", "0xdac17f958d2ee523a2206206994597c13d831ec7", "tether", 6),
    ("DAI", "0x6b175474e89094c44da98b954eedeac495271d0f", "dai", 18),
    ("WBTC", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", "wrapped-bitcoin", 8),
    ("stETH", "0xae7ab96520de3a18e5e111b5eaab095312d7fe84", "staked-ether", 18),
    ("wstETH", "0x7f39c581f595b53a5c1df47d1b2b8b17df4c43fa", "wrapped-steth", 18),
    ("USDe", "0x4c9edd5852cd905f086c759e8383e09bff1e68b3", "ethena-usde", 18),
]

STABLE_SYMBOLS = {"USDC", "USDT", "DAI", "USDe"}

PUBLIC_RPCS = (
    "https://ethereum.publicnode.com",
    "https://cloudflare-eth.com",
    "https://rpc.ankr.com/eth",
    "https://eth.llamarpc.com",
)

DEFAULT_MIN_FUNDS_USD = 100.0
# Random/discovery intake only. Unset, this also defaults to $100.
# Override with ETH_SCANNER_DISCOVERY_MIN_USD. List 1's membership band
# ($2,000–$9,000,000) is independent of the live scanner / Lane-B floor.
DEFAULT_DISCOVERY_MIN_USD = 100.0
PRICE_TTL_S = 300.0
RPC_TIMEOUT_S = 8.0

_price_cache: dict[str, tuple[float, float]] = {}  # key -> (price, fetched_at)


def discovery_min_usd() -> float:
    """Intake floor for the random/discovery lane.

    ``ETH_SCANNER_DISCOVERY_MIN_USD`` wins. Unset means $100, matching the
    live scanner / Lane-B funds floor. List 1's membership band stays its own
    $2,000–$9,000,000 range in lists.json.
    """
    raw = os.environ.get("ETH_SCANNER_DISCOVERY_MIN_USD")
    if raw is None or str(raw).strip() == "":
        return float(DEFAULT_DISCOVERY_MIN_USD)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return float(DEFAULT_DISCOVERY_MIN_USD)


@dataclass
class FundsAsset:
    symbol: str
    address: Optional[str]
    amount_raw: int
    decimals: int
    amount: float
    price_usd: float
    usd: float
    kind: str  # native | erc20 | vault-asset | underlying

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FundsSnapshot:
    status: str  # ok | unknown | skipped | override
    total_usd: Optional[float]
    breakdown: list[FundsAsset] = field(default_factory=list)
    checked_at: Optional[str] = None
    rpc_url: Optional[str] = None
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_usd": self.total_usd,
            "breakdown": [a.to_dict() for a in self.breakdown],
            "checked_at": self.checked_at,
            "rpc_url": _host_only(self.rpc_url),
            "error": self.error,
            "notes": list(self.notes),
        }


def format_funds_floor_reason(total_usd: float, floor_usd: float) -> str:
    """Match the owner-facing drop_reason wording."""
    return "below funds floor ($%s < $%s)" % (
        _fmt_usd(total_usd),
        _fmt_usd(floor_usd, commas=True, force_int_if_whole=True),
    )


def format_funds_ceiling_reason(total_usd: float, ceiling_usd: float) -> str:
    """Live balance above the list's configured maximum."""
    return "above funds ceiling ($%s > $%s)" % (
        _fmt_usd(total_usd),
        _fmt_usd(ceiling_usd, commas=True, force_int_if_whole=True),
    )


def funds_range_reason(total_usd: float, min_usd: float | None, max_usd: float | None) -> str | None:
    """None when the balance sits inside the list range."""
    if min_usd is not None and total_usd < float(min_usd):
        return format_funds_floor_reason(total_usd, float(min_usd))
    if max_usd is not None and total_usd > float(max_usd):
        return format_funds_ceiling_reason(total_usd, float(max_usd))
    return None


def resolve_rpc_urls(preferred: str = "") -> list[str]:
    from eth_scanner.ingest.rpc_client import is_rpc_usable
    urls: list[str] = []
    pref = (preferred or "").strip()
    if pref:
        urls.append(pref.rstrip("/"))
    for u in PUBLIC_RPCS:
        if u not in urls:
            urls.append(u)
    usable = [u for u in urls if is_rpc_usable(u)]
    return usable


def probe_contract_funds(
    address: str,
    *,
    rpc_url: str = "",
    min_funds_usd: float = DEFAULT_MIN_FUNDS_USD,  # noqa: ARG001 — reserved for callers
    timeout_s: float = RPC_TIMEOUT_S,
) -> FundsSnapshot:
    """Read-only funds probe. Failures return status=unknown (never silent drop)."""
    addr = _norm_addr(address)
    checked = _now()
    last_err = ""
    for rpc in resolve_rpc_urls(rpc_url):
        try:
            snap = _probe_via_rpc(addr, rpc, timeout_s=timeout_s)
            snap.checked_at = checked
            snap.rpc_url = rpc
            return snap
        except Exception as exc:  # noqa: BLE001 — soft-fail to next RPC / unknown
            last_err = str(exc)
            continue
    return FundsSnapshot(
        status="unknown",
        total_usd=None,
        breakdown=[],
        checked_at=checked,
        error=last_err or "funds probe failed",
        notes=["funds lookup failed — continuing without a floor drop"],
    )


def probe_funds_batch(
    addresses: list[str],
    *,
    rpc_url: str = "",
    timeout_s: float = 20.0,
    batch_size: int = 40,
) -> dict[str, FundsSnapshot]:
    """Cheap floor probe for many addresses: native ETH + major ERC-20s only.

    Packs Multicall3 getEthBalance + balanceOf(majors) per address (no vault
    getters). Used by the 30d backfill before full Lane A.
    """
    out: dict[str, FundsSnapshot] = {}
    addrs = [_norm_addr(a) for a in addresses if a]
    if not addrs:
        return out
    checked = _now()
    rpcs = resolve_rpc_urls(rpc_url)
    if not rpcs:
        for a in addrs:
            out[a] = FundsSnapshot(
                status="unknown", total_usd=None, checked_at=checked,
                error="no RPC", notes=["funds batch: no RPC"],
            )
        return out

    eth_price = 0.0
    try:
        eth_price = _eth_price()
    except Exception:  # noqa: BLE001
        eth_price = 0.0
    token_prices: dict[str, float] = {}
    for symbol, token, hint, _dec in MAJOR_TOKENS:
        try:
            if symbol in STABLE_SYMBOLS:
                token_prices[token] = 1.0
            else:
                token_prices[token] = _price_for_hint(hint, symbol)
        except Exception:  # noqa: BLE001
            token_prices[token] = 0.0

    for i in range(0, len(addrs), max(1, batch_size)):
        chunk = addrs[i : i + batch_size]
        snap_map: Optional[dict[str, FundsSnapshot]] = None
        last_err = ""
        for rpc in rpcs:
            try:
                snap_map = _probe_batch_via_rpc(
                    chunk, rpc, timeout_s=timeout_s,
                    eth_price=eth_price, token_prices=token_prices, checked_at=checked,
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                continue
        if snap_map is None:
            for a in chunk:
                out[a] = FundsSnapshot(
                    status="unknown", total_usd=None, checked_at=checked,
                    error=last_err or "funds batch failed",
                    notes=["funds batch failed — treat as unknown"],
                )
        else:
            out.update(snap_map)
        time.sleep(0.05)
    return out


def _price_for_hint(hint: str, symbol: str) -> float:
    if symbol in STABLE_SYMBOLS:
        return 1.0
    if hint == "ethereum":
        return _eth_price()
    # Reuse llama/coingecko path via existing helpers when possible.
    try:
        if hint in {"usd-coin", "tether", "dai", "ethena-usde"}:
            return 1.0
        # Map common hints to coingecko ids already used elsewhere.
        cg = {
            "wrapped-bitcoin": "wrapped-bitcoin",
            "staked-ether": "staked-ether",
            "wrapped-steth": "wrapped-steth",
        }.get(hint, hint)
        p = _fetch_coingecko(cg)
        return float(p or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _probe_batch_via_rpc(
    addresses: list[str],
    rpc: str,
    *,
    timeout_s: float,
    eth_price: float,
    token_prices: dict[str, float],
    checked_at: str,
) -> dict[str, FundsSnapshot]:
    mc_calls: list[tuple[str, bool, bytes]] = []
    # Per address: getEthBalance + balanceOf each major.
    for addr in addresses:
        mc_calls.append((MULTICALL3, True, bytes.fromhex(GET_ETH_BALANCE_SELECTOR) + _pad_addr(addr)))
        for _symbol, token, _hint, _decimals in MAJOR_TOKENS:
            mc_calls.append((token, True, bytes.fromhex(BALANCE_OF_SELECTOR) + _pad_addr(addr)))

    raw = _rpc_call(
        rpc,
        "eth_call",
        [{"to": MULTICALL3, "data": "0x" + _encode_aggregate3(mc_calls).hex()}, "latest"],
        timeout_s,
    )
    decoded = _decode_aggregate3(raw)
    per = 1 + len(MAJOR_TOKENS)
    if len(decoded) != len(addresses) * per:
        raise RuntimeError("batch multicall length mismatch")

    out: dict[str, FundsSnapshot] = {}
    for i, addr in enumerate(addresses):
        base = i * per
        assets: list[FundsAsset] = []
        ok, ret = decoded[base]
        if ok and ret:
            wei = int.from_bytes(ret[-32:] if len(ret) >= 32 else ret, "big")
            eth_amt = wei / 1e18
            if eth_amt > 0 and eth_price > 0:
                assets.append(FundsAsset("ETH", None, wei, 18, eth_amt, eth_price, eth_amt * eth_price, "native"))
        for j, (symbol, token_addr, _hint, known_dec) in enumerate(MAJOR_TOKENS):
            ok, ret = decoded[base + 1 + j]
            if not ok or not ret:
                continue
            raw_bal = int.from_bytes(ret[-32:] if len(ret) >= 32 else ret, "big")
            if raw_bal <= 0:
                continue
            dec = known_dec if known_dec is not None else 18
            amt = raw_bal / (10 ** dec)
            price = float(token_prices.get(token_addr) or (1.0 if symbol in STABLE_SYMBOLS else 0.0))
            if price <= 0:
                continue
            assets.append(FundsAsset(symbol, token_addr, raw_bal, dec, amt, price, amt * price, "erc20"))
        total = sum(a.usd for a in assets) if assets else 0.0
        out[addr] = FundsSnapshot(
            status="ok",
            total_usd=float(total),
            breakdown=assets,
            checked_at=checked_at,
            rpc_url=rpc,
            notes=["cheap batch floor (ETH+majors)"],
        )
    return out


def _probe_via_rpc(address: str, rpc: str, *, timeout_s: float) -> FundsSnapshot:
    # One Multicall3 aggregate3: native via getEthBalance + balanceOf for majors
    # + asset()/totalAssets()/token()/underlying() on the target itself.
    mc_calls: list[tuple[str, bool, bytes]] = [
        (MULTICALL3, True, bytes.fromhex(GET_ETH_BALANCE_SELECTOR) + _pad_addr(address)),
    ]
    for _symbol, token, _hint, _decimals in MAJOR_TOKENS:
        mc_calls.append((token, True, bytes.fromhex(BALANCE_OF_SELECTOR) + _pad_addr(address)))
    mc_calls.append((address, True, bytes.fromhex(ASSET_SELECTOR)))
    mc_calls.append((address, True, bytes.fromhex(TOTAL_ASSETS_SELECTOR)))
    mc_calls.append((address, True, bytes.fromhex(TOKEN_SELECTOR)))
    mc_calls.append((address, True, bytes.fromhex(UNDERLYING_SELECTOR)))

    raw = _rpc_call(
        rpc,
        "eth_call",
        [{"to": MULTICALL3, "data": "0x" + _encode_aggregate3(mc_calls).hex()}, "latest"],
        timeout_s,
    )
    decoded = _decode_aggregate3(raw)
    if len(decoded) != len(mc_calls):
        raise RuntimeError("multicall length mismatch (%d vs %d)" % (len(decoded), len(mc_calls)))

    notes: list[str] = []
    assets: list[FundsAsset] = []

    ok, ret = decoded[0]
    if ok and ret:
        wei = int.from_bytes(ret[-32:] if len(ret) >= 32 else ret, "big")
        eth_amt = wei / 1e18
        price = _eth_price()
        if eth_amt > 0:
            assets.append(FundsAsset("ETH", None, wei, 18, eth_amt, price, eth_amt * price, "native"))

    for i, (symbol, token_addr, _hint, known_dec) in enumerate(MAJOR_TOKENS, start=1):
        ok, ret = decoded[i]
        if not ok or not ret:
            continue
        raw_bal = int.from_bytes(ret[-32:] if len(ret) >= 32 else ret, "big")
        if raw_bal <= 0:
            continue
        decimals = known_dec if known_dec is not None else 18
        amount = raw_bal / (10 ** decimals)
        price = 1.0 if symbol in STABLE_SYMBOLS else _token_price(token_addr, symbol)
        assets.append(FundsAsset(symbol, token_addr, raw_bal, decimals, amount, price, amount * price, "erc20"))

    base = 1 + len(MAJOR_TOKENS)
    asset_ok, asset_ret = decoded[base]
    total_ok, total_ret = decoded[base + 1]
    token_ok, token_ret = decoded[base + 2]
    under_ok, under_ret = decoded[base + 3]

    underlying_addr: Optional[str] = None
    if asset_ok and asset_ret and len(asset_ret) >= 32:
        underlying_addr = _addr_from_word(asset_ret[-32:])
        notes.append("erc4626 asset()=%s" % underlying_addr)
    elif token_ok and token_ret and len(token_ret) >= 32:
        underlying_addr = _addr_from_word(token_ret[-32:])
        notes.append("token()=%s" % underlying_addr)
    elif under_ok and under_ret and len(under_ret) >= 32:
        underlying_addr = _addr_from_word(under_ret[-32:])
        notes.append("underlying()=%s" % underlying_addr)

    if underlying_addr and total_ok and total_ret and len(total_ret) >= 32:
        total_raw = int.from_bytes(total_ret[-32:], "big")
        if total_raw > 0:
            dec = _lookup_decimals(rpc, underlying_addr, timeout_s) or 18
            amount = total_raw / (10 ** dec)
            sym = _symbol_for(underlying_addr) or "UNDERLYING"
            price = 1.0 if sym in STABLE_SYMBOLS else _token_price(underlying_addr, sym)
            # Prefer vault AUM over the raw ERC-20 balance of the same underlying.
            assets = [
                a
                for a in assets
                if not (a.kind == "erc20" and a.address and a.address.lower() == underlying_addr)
            ]
            assets.append(
                FundsAsset(sym, underlying_addr, total_raw, dec, amount, price, amount * price, "vault-asset")
            )
    elif underlying_addr:
        if not any(a.address and a.address.lower() == underlying_addr for a in assets):
            bal = _balance_of(rpc, underlying_addr, address, timeout_s)
            if bal > 0:
                dec = _lookup_decimals(rpc, underlying_addr, timeout_s) or 18
                amount = bal / (10 ** dec)
                sym = _symbol_for(underlying_addr) or "UNDERLYING"
                price = 1.0 if sym in STABLE_SYMBOLS else _token_price(underlying_addr, sym)
                assets.append(
                    FundsAsset(sym, underlying_addr, bal, dec, amount, price, amount * price, "underlying")
                )

    total = sum(a.usd for a in assets)
    return FundsSnapshot(
        status="ok",
        total_usd=round(total, 6),
        breakdown=assets,
        notes=notes,
    )


def _eth_price() -> float:
    return _cached_price(
        "eth-usd",
        lambda: _fetch_llama_price("ethereum:0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2")
        or _fetch_coingecko("ethereum")
        or 0.0,
    )


def _token_price(token_addr: str, symbol: str) -> float:
    key = "llama:ethereum:%s" % token_addr.lower()

    def load() -> float:
        p = _fetch_llama_price("ethereum:%s" % token_addr.lower())
        if p and p > 0:
            return p
        # coarse fallbacks for majors if llama is down
        if symbol == "WETH":
            return _eth_price()
        if symbol == "WBTC":
            return _fetch_coingecko("bitcoin") or 0.0
        if symbol in {"stETH", "wstETH"}:
            return _eth_price()
        return 0.0

    return _cached_price(key, load)


def _cached_price(key: str, loader) -> float:
    now = time.monotonic()
    hit = _price_cache.get(key)
    if hit and (now - hit[1]) < PRICE_TTL_S:
        return hit[0]
    try:
        price = float(loader() or 0.0)
    except Exception:  # noqa: BLE001
        price = hit[0] if hit else 0.0
    _price_cache[key] = (price, now)
    return price


def _fetch_llama_price(coin_key: str) -> Optional[float]:
    url = "https://coins.llama.fi/prices/current/" + urllib.parse.quote(coin_key, safe=":")
    req = urllib.request.Request(url, headers={"User-Agent": "eth-scanner/0.3 (defensive; read-only)"})
    with urllib.request.urlopen(req, timeout=6.0) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    coins = body.get("coins") or {}
    row = coins.get(coin_key) or {}
    price = row.get("price")
    return float(price) if price is not None else None


def _fetch_coingecko(coin_id: str) -> Optional[float]:
    url = "https://api.coingecko.com/api/v3/simple/price?ids=%s&vs_currencies=usd" % urllib.parse.quote(coin_id)
    req = urllib.request.Request(url, headers={"User-Agent": "eth-scanner/0.3 (defensive; read-only)"})
    with urllib.request.urlopen(req, timeout=6.0) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    row = body.get(coin_id) or {}
    price = row.get("usd")
    return float(price) if price is not None else None


def _rpc_call(rpc: str, method: str, params: list[Any], timeout_s: float) -> str:
    from eth_scanner.ingest.rpc_client import rpc_call
    result = rpc_call(rpc, method, params, timeout_s=timeout_s)
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RuntimeError("bad eth_call result")
    return result


def _balance_of(rpc: str, token: str, holder: str, timeout_s: float) -> int:
    data = "0x" + BALANCE_OF_SELECTOR + _pad_addr(holder).hex()
    raw = _rpc_call(rpc, "eth_call", [{"to": token, "data": data}, "latest"], timeout_s)
    b = bytes.fromhex(raw[2:])
    if not b:
        return 0
    return int.from_bytes(b[-32:] if len(b) >= 32 else b, "big")


def _lookup_decimals(rpc: str, token: str, timeout_s: float) -> Optional[int]:
    for sym, addr, _h, dec in MAJOR_TOKENS:
        if addr.lower() == token.lower() and dec is not None:
            return dec
    try:
        raw = _rpc_call(rpc, "eth_call", [{"to": token, "data": "0x" + DECIMALS_SELECTOR}, "latest"], timeout_s)
        b = bytes.fromhex(raw[2:])
        if not b:
            return None
        return int.from_bytes(b[-32:] if len(b) >= 32 else b, "big")
    except Exception:  # noqa: BLE001
        return None


def _symbol_for(addr: str) -> Optional[str]:
    for sym, a, _h, _d in MAJOR_TOKENS:
        if a.lower() == addr.lower():
            return sym
    return None


def _encode_aggregate3(calls: list[tuple[str, bool, bytes]]) -> bytes:
    """ABI-encode aggregate3((address,bool,bytes)[])."""
    head = bytes.fromhex(AGGREGATE3_SELECTOR)
    # offset to array = 32
    enc = bytearray()
    enc += (32).to_bytes(32, "big")
    enc += len(calls).to_bytes(32, "big")
    # offsets for each tuple relative to start of array contents (after length)
    # each dynamic tuple: static head 3*32 then dynamic bytes
    # We encode as: offsets[], then each tuple blob
    offset = 32 * len(calls)
    heads = bytearray()
    tails = bytearray()
    for target, allow_failure, data in calls:
        heads += offset.to_bytes(32, "big")
        tup = bytearray()
        tup += _pad_addr_word(target)
        tup += (1 if allow_failure else 0).to_bytes(32, "big")
        tup += (96).to_bytes(32, "big")  # offset to bytes = 3*32
        tup += len(data).to_bytes(32, "big")
        tup += data
        if len(data) % 32:
            tup += b"\x00" * (32 - (len(data) % 32))
        tails += tup
        offset += len(tup)
    enc += heads
    enc += tails
    return head + enc


def _decode_aggregate3(result_hex: str) -> list[tuple[bool, bytes]]:
    raw = bytes.fromhex(result_hex[2:] if result_hex.startswith("0x") else result_hex)
    if len(raw) < 64:
        return []
    # offset to array
    arr_off = int.from_bytes(raw[0:32], "big")
    base = arr_off
    n = int.from_bytes(raw[base : base + 32], "big")
    out: list[tuple[bool, bytes]] = []
    for i in range(n):
        tup_rel = int.from_bytes(raw[base + 32 + 32 * i : base + 64 + 32 * i], "big")
        tup = base + 32 + tup_rel
        success = int.from_bytes(raw[tup : tup + 32], "big") == 1
        data_off = int.from_bytes(raw[tup + 32 : tup + 64], "big")
        data_pos = tup + data_off
        data_len = int.from_bytes(raw[data_pos : data_pos + 32], "big")
        data = raw[data_pos + 32 : data_pos + 32 + data_len]
        out.append((success, data))
    return out


def _pad_addr(addr: str) -> bytes:
    a = addr.lower().removeprefix("0x")
    return bytes.fromhex(a.rjust(64, "0"))


def _pad_addr_word(addr: str) -> bytes:
    return _pad_addr(addr)


def _addr_from_word(word: bytes) -> str:
    return "0x" + word[-20:].hex()


def _norm_addr(addr: str) -> str:
    a = (addr or "").strip().lower()
    if not a.startswith("0x"):
        a = "0x" + a
    return a


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host_only(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        return urllib.parse.urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def _fmt_usd(value: float, *, commas: bool = False, force_int_if_whole: bool = False) -> str:
    if force_int_if_whole and abs(value - round(value)) < 1e-9:
        n = int(round(value))
        return f"{n:,}" if commas else str(n)
    if value >= 100:
        return f"{value:,.2f}" if commas else f"{value:.2f}"
    if value >= 1:
        return f"{value:,.2f}" if commas else f"{value:.2f}"
    return f"{value:.4f}".rstrip("0").rstrip(".") if value else "0"
