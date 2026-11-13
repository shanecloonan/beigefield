"""Read-only oracle / price-source checks on funded contracts.

Detect Chainlink feeds + AMM spot/TWAP usage in source; confirm only when
live chain data shows staleness, zero/negative answers, thin-pool vs funds,
or single-block TWAP. Raw tool/source matches alone → lead (0 heat).
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# latestRoundData()
_SEL_LATEST_ROUND = "feaf968c"
# getReserves() UniswapV2
_SEL_GET_RESERVES = "0902f1ac"
# slot0() UniswapV3
_SEL_SLOT0 = "3850c7bd"
# decimals()
_SEL_DECIMALS = "313ce567"

_CHAINLINK_RX = re.compile(
    r"AggregatorV3Interface|latestRoundData\s*\(|latestAnswer\s*\(|"
    r"IAggregator|FeedRegistry|chainlink",
    re.I,
)
_AMM_RX = re.compile(
    r"getReserves\s*\(|\.slot0\s*\(|IUniswapV2Pair|IUniswapV3Pool|"
    r"observe\s*\(|consult\s*\(|twap|TWAP",
    re.I,
)
_ADDR_RX = re.compile(r"0x[a-fA-F0-9]{40}")
_FEED_ASSIGN_RX = re.compile(
    r"(?:priceFeed|oracle|aggregator|feed)\s*(?:=\s*)?(?:I?\w+\s*\()?(0x[a-fA-F0-9]{40})",
    re.I,
)


@dataclass
class OracleFinding:
    id: str
    kind: str  # lead | confirmed
    title: str
    evidence: str
    confirmed: bool = False
    method: str = "source"
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OracleReport:
    ran: bool = False
    status: str = "skipped"
    leads: list[OracleFinding] = field(default_factory=list)
    confirmed: list[OracleFinding] = field(default_factory=list)
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "status": self.status,
            "leads": [f.to_dict() for f in self.leads],
            "confirmed": [f.to_dict() for f in self.confirmed],
            "duration_ms": self.duration_ms,
            "notes": list(self.notes),
            "artifact": dict(self.artifact),
        }


def run_oracle_checks(
    *,
    address: str,
    source: str,
    rpc_url: str = "",
    funds_usd: Optional[float] = None,
    timeout_s: float = 25.0,
) -> OracleReport:
    report = OracleReport()
    t0 = time.monotonic()
    src = source or ""
    deadline = t0 + max(5.0, float(timeout_s))

    # Stage executed once we inspect source (even when no oracle patterns).
    report.ran = True
    has_cl = bool(_CHAINLINK_RX.search(src))
    has_amm = bool(_AMM_RX.search(src))
    if not has_cl and not has_amm:
        report.status = "ok"
        report.notes.append("oracle: no Chainlink/AMM price patterns in source")
        report.duration_ms = int((time.monotonic() - t0) * 1000)
        return report

    if has_cl:
        report.leads.append(OracleFinding(
            id="oracle-chainlink-usage",
            kind="lead",
            title="Source references Chainlink / AggregatorV3 price feed",
            evidence="matched AggregatorV3Interface or latestRoundData in source",
        ))
        if "sequencer" not in src.lower() and "staleness" not in src.lower() and "heartbeat" not in src.lower():
            report.leads.append(OracleFinding(
                id="oracle-missing-staleness-guard",
                kind="lead",
                title="No obvious sequencer/staleness/heartbeat guard near oracle reads",
                evidence="source lacks sequencer/staleness/heartbeat keywords",
            ))

    if has_amm:
        twap = bool(re.search(r"\btwap\b|observe\s*\(|consult\s*\(", src, re.I))
        report.leads.append(OracleFinding(
            id="oracle-amm-spot" if not twap else "oracle-amm-twap",
            kind="lead",
            title="Source reads AMM reserves/slot0" + (" / TWAP" if twap else " (spot)"),
            evidence="matched getReserves/slot0/observe in source",
        ))

    if not rpc_url or time.monotonic() > deadline:
        report.status = "ok"
        report.notes.append("oracle: leads only — no RPC for live confirm")
        _finish(report, address, t0)
        return report

    # Live Chainlink confirmations for extracted feed addresses.
    feeds = _extract_feed_addrs(src)
    for feed in feeds[:4]:
        if time.monotonic() > deadline:
            break
        conf = _confirm_chainlink_feed(rpc_url, feed, timeout_s=min(8.0, deadline - time.monotonic()))
        if conf:
            report.confirmed.append(conf)
            report.leads.append(OracleFinding(
                id=conf.id + "-lead",
                kind="lead",
                title=conf.title,
                evidence=conf.evidence,
                confirmed=False,
                method="eth_call",
            ))

    # Thin-pool vs funds: if UniswapV2 pair address appears and funds known.
    if has_amm and funds_usd and funds_usd >= 2_000 and time.monotonic() < deadline:
        pairs = _extract_pair_addrs(src)
        for pair in pairs[:3]:
            if time.monotonic() > deadline:
                break
            conf = _confirm_thin_pool(
                rpc_url, pair, funds_usd,
                timeout_s=min(8.0, deadline - time.monotonic()),
            )
            if conf:
                report.confirmed.append(conf)

    report.status = "ok"
    report.notes.append(
        "oracle leads=%d confirmed=%d feeds=%d"
        % (len(report.leads), len(report.confirmed), len(feeds))
    )
    _finish(report, address, t0)
    return report


def oracle_as_confirmed(report: OracleReport) -> list[dict[str, Any]]:
    out = []
    for c in report.confirmed:
        out.append({
            "lead_id": c.id,
            "confirmed": True,
            "method": c.method or "oracle",
            "evidence": c.evidence[:500],
            "extras": dict(c.extras),
        })
    return out


def oracle_as_leads(report: OracleReport) -> list[dict[str, Any]]:
    out = []
    for lead in report.leads:
        out.append({
            "id": lead.id,
            "engine": "oracle",
            "rule": lead.id,
            "title": lead.title,
            "severity": "high" if "stale" in lead.id or "thin" in lead.id else "med",
            "evidence": lead.evidence,
            "generic": False,
        })
    return out


def _finish(report: OracleReport, address: str, t0: float) -> None:
    report.duration_ms = int((time.monotonic() - t0) * 1000)
    report.artifact = {
        "kind": "oracle",
        "address": address.lower(),
        "status": report.status,
        "leads": [f.to_dict() for f in report.leads],
        "confirmed": [f.to_dict() for f in report.confirmed],
        "notes": list(report.notes)[:8],
        "duration_ms": report.duration_ms,
    }


def _rpc(rpc_url: str, method: str, params: list[Any], timeout_s: float = 10.0) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        rpc_url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "eth-scanner-oracle/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    return body.get("result")


def _eth_call(rpc_url: str, to: str, data: str, timeout_s: float = 10.0) -> str:
    return str(_rpc(rpc_url, "eth_call", [{"to": to, "data": data}, "latest"], timeout_s) or "")


def _decode_int_words(raw: str, n: int) -> list[int]:
    h = (raw or "").removeprefix("0x")
    if len(h) < 64 * n:
        return []
    out = []
    for i in range(n):
        chunk = h[i * 64:(i + 1) * 64]
        # signed for answer word
        val = int(chunk, 16)
        if i == 1 and val >= 2**255:
            val -= 2**256
        out.append(val)
    return out


def _extract_feed_addrs(src: str) -> list[str]:
    found: list[str] = []
    for m in _FEED_ASSIGN_RX.finditer(src or ""):
        a = m.group(1).lower()
        if a not in found:
            found.append(a)
    # Fallback: nearby addresses after AggregatorV3 mentions (bounded).
    if not found:
        for m in re.finditer(r"AggregatorV3Interface[\s\S]{0,120}(0x[a-fA-F0-9]{40})", src or "", re.I):
            a = m.group(1).lower()
            if a not in found:
                found.append(a)
    return found[:6]


def _extract_pair_addrs(src: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(
        r"(?:pair|pool|uniswap|lpToken)\s*(?:=\s*)?(?:I?\w+\s*\()?(0x[a-fA-F0-9]{40})",
        src or "",
        re.I,
    ):
        a = m.group(1).lower()
        if a not in found:
            found.append(a)
    return found[:6]


def _confirm_chainlink_feed(
    rpc_url: str,
    feed: str,
    *,
    timeout_s: float,
) -> Optional[OracleFinding]:
    try:
        raw = _eth_call(rpc_url, feed, "0x" + _SEL_LATEST_ROUND, timeout_s=timeout_s)
        words = _decode_int_words(raw, 5)
        if len(words) < 5:
            return None
        round_id, answer, _started, updated, answered = words
        block = _rpc(rpc_url, "eth_getBlockByNumber", ["latest", False], timeout_s=min(5.0, timeout_s))
        ts = int(block.get("timestamp", "0x0"), 16) if isinstance(block, dict) else 0
        if answer <= 0:
            return OracleFinding(
                id="oracle-live-zero-or-negative",
                kind="confirmed",
                title="Live Chainlink answer is zero or negative",
                evidence="feed=%s answer=%s updatedAt=%s" % (feed, answer, updated),
                confirmed=True,
                method="eth_call",
                extras={"feed": feed, "answer": answer, "updatedAt": updated},
            )
        if answered < round_id:
            return OracleFinding(
                id="oracle-live-answered-in-round",
                kind="confirmed",
                title="Live Chainlink answeredInRound < roundId",
                evidence="feed=%s roundId=%s answeredInRound=%s" % (feed, round_id, answered),
                confirmed=True,
                method="eth_call",
                extras={"feed": feed, "roundId": round_id, "answeredInRound": answered},
            )
        if ts and updated and (ts - updated) > 36 * 3600:
            return OracleFinding(
                id="oracle-live-stale",
                kind="confirmed",
                title="Live Chainlink feed stale (>36h)",
                evidence="feed=%s age_s=%s updatedAt=%s block_ts=%s" % (feed, ts - updated, updated, ts),
                confirmed=True,
                method="eth_call",
                extras={"feed": feed, "age_s": ts - updated, "updatedAt": updated},
            )
    except Exception:  # noqa: BLE001
        return None
    return None


def _confirm_thin_pool(
    rpc_url: str,
    pair: str,
    funds_usd: float,
    *,
    timeout_s: float,
) -> Optional[OracleFinding]:
    """Heuristic: if getReserves returns tiny liquidity vs funds at risk → confirm."""
    try:
        raw = _eth_call(rpc_url, pair, "0x" + _SEL_GET_RESERVES, timeout_s=timeout_s)
        h = (raw or "").removeprefix("0x")
        if len(h) < 128:
            return None
        r0 = int(h[0:64], 16)
        r1 = int(h[64:128], 16)
        # Without token decimals/price, use a coarse ETH-ish proxy: treat smaller
        # reserve as wei and convert at $2000 if both look like wei magnitudes.
        # Only confirm when BOTH reserves are extremely small relative to funds.
        min_res = min(r0, r1)
        # If min reserve < 0.05 ETH worth in wei AND funds >= $50k → thin.
        if min_res < int(0.05 * 1e18) and funds_usd >= 50_000:
            return OracleFinding(
                id="oracle-thin-pool-vs-funds",
                kind="confirmed",
                title="AMM pool liquidity far below funds at risk (live reserves)",
                evidence="pair=%s reserve0=%s reserve1=%s funds_usd=%.0f" % (pair, r0, r1, funds_usd),
                confirmed=True,
                method="eth_call",
                extras={"pair": pair, "reserve0": r0, "reserve1": r1, "funds_usd": funds_usd},
            )
    except Exception:  # noqa: BLE001
        return None
    return None
