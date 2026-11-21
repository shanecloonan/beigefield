"""L2 custom Python detectors — defensive shape checks only.

1. External value/token movers gated by weak / missing auth.
2. Share / asset accounting surface on vault-like contracts.
3. Oracle freshness hooks when Chainlink-like interfaces are present.
4. Pre-0.8 arithmetic, weak entropy, bare low-level calls, a hash-preimage
   payout, and a parameter-bounded storage loop. These cover shapes Slither
   0.11.6 does not detect, or that never reach Slither when a file does not
   compile. They are leads. They do not add heat.

No path synthesis. No exploit sketches.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from eth_scanner.heuristics.invariant_pass import functions, solidity_modifiers, strip_comments
from eth_scanner.research.types import Finding
from eth_scanner.types import FunctionIR, IRDocument

_VALUE_MOVE = re.compile(
    r"\.transferFrom\s*\(|\.transfer\s*\(|safeTransfer(From)?\s*\(|"
    r"\.call\s*\{\s*value|\.send\s*\(|payable\s*\([^)]+\)\s*\.transfer",
    re.I,
)
_SHARE_TERMS = re.compile(
    r"\b(totalAssets|totalSupply|convertToShares|convertToAssets|"
    r"pricePerShare|previewDeposit|previewRedeem|balanceOf)\b",
)
_SHARE_BURN = re.compile(r"_burn\s*\(|balanceOf\s*\[|totalSupply\s*\-", re.I)
_ORACLE_IFACE = re.compile(
    r"\b(latestRoundData|latestAnswer|AggregatorV3Interface|aggregator)\b",
)
_ORACLE_FRESH = re.compile(
    r"\b(updatedAt|startedAt|stale|heartbeat|maxDelay|maxAge|answeredInRound)\b",
    re.I,
)
_WEAK = frozenset({"WEAK", "MISSING", "MISSING(internal — check callers)", "AMBIGUOUS"})


def _finding(
    *,
    n: int,
    detector: str,
    severity: str,
    title: str,
    evidence: str,
    address: str,
) -> Finding:
    return Finding(
        id="L2-%s-%d" % (detector, n),
        severity=severity,  # type: ignore[arg-type]
        layer="L2",
        title=title,
        evidence=evidence,
        address=address,
        detector="custom:%s" % detector,
    )


def detect_weak_auth_value_moves(
    *,
    address: str,
    source: str,
    lane_ir: Optional[IRDocument] = None,
) -> list[Finding]:
    findings: list[Finding] = []
    if lane_ir and lane_ir.functions:
        movers: Iterable[FunctionIR] = [
            fn for fn in lane_ir.functions
            if fn.is_value_mover and fn.exposed and fn.role not in {"erc20-standard", "wrap-unwrap"}
        ]
        n = 0
        for fn in movers:
            auth = fn.auth_heuristic or "AMBIGUOUS"
            if auth not in _WEAK and auth != "MISSING":
                continue
            n += 1
            sev = "high" if auth.startswith("MISSING") else "low"
            findings.append(_finding(
                n=n,
                detector="weak-auth-value-move",
                severity=sev,
                title="Value-moving function with %s auth heuristic" % auth,
                evidence="%s %s L%d role=%s auth=%s signals=%s"
                % (fn.visibility, fn.name, fn.line, fn.role, auth, ",".join(fn.fund_signals[:6]) or "—"),
                address=address,
            ))
        return findings

    clean = strip_comments(source or "", "solidity")
    mods = solidity_modifiers(clean)
    n = 0
    for fn in functions(source or "", clean, "solidity"):
        vis = fn.get("vis") or ""
        if "external" not in vis and "public" not in vis:
            continue
        if "view" in vis or "pure" in vis:
            continue
        body = fn.get("body") or ""
        if not _VALUE_MOVE.search(body):
            continue
        header = fn.get("header") or ""
        gated = bool(re.search(r"\bonly[A-Z]\w+", header)) or bool(
            re.search(r"\b(onlyOwner|onlyRole|requiresAuth|auth)\b", header)
        )
        if not gated:
            for mname in mods:
                if re.search(r"\b%s\b" % re.escape(mname), header):
                    gated = True
                    break
        if gated:
            continue
        n += 1
        findings.append(_finding(
            n=n,
            detector="weak-auth-value-move",
            severity="high",
            title="External value move without an auth modifier",
            evidence="%s %s L%d — transfer/call{value} with no only* modifier"
            % (vis, fn.get("name"), fn.get("line") or 0),
            address=address,
        ))
    return findings


def detect_share_asset_shape(
    *,
    address: str,
    source: str,
    role: str = "",
) -> list[Finding]:
    if role not in {"vault", "staking", "lending"}:
        return []
    src = source or ""
    findings: list[Finding] = []
    has_deposit = bool(re.search(r"\bfunction\s+(deposit|mint|stake|supply)\b", src))
    has_withdraw = bool(re.search(r"\bfunction\s+(withdraw|redeem|unstake)\b", src))
    terms = sorted(set(m.group(0) for m in _SHARE_TERMS.finditer(src)))
    if (has_deposit or has_withdraw) and not terms:
        findings.append(_finding(
            n=1,
            detector="share-asset-shape",
            severity="low",
            title="Deposit/withdraw without share/asset accounting terms",
            evidence="role=%s deposit=%s withdraw=%s — no totalAssets/totalSupply/convertTo* / pricePerShare"
            % (role, has_deposit, has_withdraw),
            address=address,
        ))
        return findings
    if has_withdraw and not _SHARE_BURN.search(src) and role == "vault":
        findings.append(_finding(
            n=1,
            detector="share-asset-shape",
            severity="low",
            title="Withdraw without an obvious share-burn / balance decrement",
            evidence="role=vault withdraw present; no `_burn` or `balanceOf[` decrement nearby (shape only)",
            address=address,
        ))
    if has_deposit and has_withdraw and terms:
        findings.append(_finding(
            n=len(findings) + 1,
            detector="share-asset-shape",
            severity="info",
            title="Share/asset accounting terms present",
            evidence="role=%s terms=%s" % (role, ",".join(terms[:12])),
            address=address,
        ))
    return findings


def detect_oracle_freshness(*, address: str, source: str) -> list[Finding]:
    src = source or ""
    if not _ORACLE_IFACE.search(src):
        return []
    if _ORACLE_FRESH.search(src):
        return [Finding(
            id="L2-oracle-freshness-1",
            severity="info",
            layer="L2",
            title="Chainlink-like feed with a freshness hook term",
            evidence="latestRoundData/latestAnswer present alongside updatedAt/stale/heartbeat (confirm by reading)",
            address=address,
            detector="custom:oracle-freshness",
        )]
    return [Finding(
        id="L2-oracle-freshness-1",
        severity="med",
        layer="L2",
        title="Chainlink-like feed without an obvious freshness check",
        evidence=(
            "Aggregator / latestRoundData / latestAnswer appears in source; "
            "no updatedAt / stale / heartbeat / answeredInRound term. Shape only — not a path."
        ),
        address=address,
        detector="custom:oracle-freshness",
    )]


_PRAGMA = re.compile(r"pragma\s+solidity\s+([^;]+);", re.I)
_ALLOWS_08 = re.compile(
    r"\^0\.(?:8|9)\b|>=\s*0\.(?:8|9)\b|>\s*0\.7\b|(?<![<>=])0\.(?:8|9)\.\d+",
)
_PRE_08 = re.compile(r"\^0\.[4-7]\b|<\s*0\.8\b|(?<![<>=\^])0\.[4-7]\.\d+")
_RAW_ARITH = re.compile(r"(?<![+\-*/%<>=!])(?:\+=|-=|\*=|[+\-*])(?!=)")
_SUM_ASSIGN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[^;+\n]*\+",
)
_MUL_GUARD = re.compile(r"(?:require|assert)\s*\([^;]{0,160}/\s*[A-Za-z_]")
_BLOCKHASH = re.compile(r"\bblockhash\s*\(|\bblock\s*\.\s*blockhash\s*\(", re.I)
_ENTROPY_SOURCE = re.compile(
    r"\bblock\s*\.\s*(?:difficulty|coinbase|prevrandao|timestamp|number)\b|\bnow\b|\bgasleft\s*\(",
    re.I,
)
_ENTROPY_SINK = re.compile(r"%|keccak256\s*\(|\bsha3\s*\(|\bsha256\s*\(", re.I)
_LOW_LEVEL = re.compile(r"\.(?:call|send|delegatecall)\b", re.I)
_DELEGATE = re.compile(r"\.delegatecall\b", re.I)
_CHECKED_WORD = re.compile(r"\b(?:require|assert|if)\b")
_PREIMAGE = re.compile(r"(?:sha3|keccak256)\s*\(\s*[A-Za-z_][A-Za-z0-9_]*\s*\)")
_PAYOUT = re.compile(
    r"\.transfer\s*\(|\.send\s*\(|\.call\s*\.value|\.call\s*\{[^}]*\bvalue\b",
    re.I,
)
_FOR_BOUND = re.compile(
    r"\bfor\s*\([^;]*;([^;]*);",
    re.I,
)
_PARAM = re.compile(
    r"\b(?:u?int\d*|address|bool|bytes\d*|string)\s*(?:\[\s*\])?\s+([A-Za-z_][A-Za-z0-9_]*)",
)
_STORED = re.compile(r"\.push\s*\(|\[[^\]]*\]\s*(?:\+\+|--|=)", re.I)


def _pragma_is_pre_08(source: str) -> bool:
    """True only when the pragma cannot select Solidity 0.8 or newer."""
    match = _PRAGMA.search(source or "")
    if not match:
        return False
    spec = match.group(1)
    if _ALLOWS_08.search(spec):
        return False
    if re.search(r"<\s*0\.(?:9|1\d)\b", spec) and not re.search(r"<\s*0\.8\b", spec):
        return False
    return bool(_PRE_08.search(spec))


def _exposed(vis: str) -> bool:
    return "public" in (vis or "") or "external" in (vis or "")


def _overflow_guarded(body: str) -> bool:
    """True when the function checks a sum it just computed, or checks a product.

    `require(balance >= amount)` is a balance check, not this guard.
    """
    for match in _SUM_ASSIGN.finditer(body or ""):
        name = match.group(1)
        if re.search(r"(?:require|assert)\s*\(\s*%s\s*>=" % re.escape(name), body):
            return True
    return bool(_MUL_GUARD.search(body or ""))


def _has_raw_arith(body: str) -> bool:
    scrub = re.sub(r"\.(?:add|sub|mul|div)\s*\(", "", body or "")
    scrub = re.sub(r"\+\+|--", "", scrub)
    return bool(_RAW_ARITH.search(scrub))


def _header_params(header: str) -> set[str]:
    match = re.search(r"\((.*)\)", header or "", re.S)
    if not match:
        return set()
    return {name for name in _PARAM.findall(match.group(1))}


def _bool_binding(stmt: str) -> str:
    match = re.search(r"\(\s*bool\s+([A-Za-z_][A-Za-z0-9_]*)", stmt)
    if match:
        return match.group(1)
    match = re.search(r"\bbool\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", stmt)
    return match.group(1) if match else ""


def _checked_later(name: str, later: str) -> bool:
    if not name:
        return False
    return bool(re.search(
        r"\b(?:require|assert|if|revert)\b[^;]{0,240}\b%s\b" % re.escape(name),
        later,
    ))


def detect_pre08_arithmetic(*, address: str, source: str) -> list[Finding]:
    """Public raw + - * on a pre-0.8 pragma, with no overflow guard in that function.

    Solidity 0.8 checks arithmetic. SafeMath-only bodies and internal library
    helpers are left alone. This is a shape lead, not a drain.
    """
    if not _pragma_is_pre_08(source or ""):
        return []
    clean = strip_comments(source or "", "solidity")
    findings: list[Finding] = []
    n = 0
    for fn in functions(source or "", clean, "solidity"):
        if not _exposed(str(fn.get("vis") or "")):
            continue
        body = str(fn.get("body") or "")
        if not _has_raw_arith(body) or _overflow_guarded(body):
            continue
        n += 1
        findings.append(_finding(
            n=n,
            detector="pre08-arithmetic",
            severity="low",
            title="Pre-0.8 arithmetic without an overflow guard",
            evidence="%s %s L%d — raw + - or * under pragma %s. Shape only, not a path."
            % (fn.get("vis") or "", fn.get("name"), fn.get("line") or 0, _PRAGMA.search(source).group(1).strip()),
            address=address,
        ))
    return findings


def detect_weak_entropy(*, address: str, source: str) -> list[Finding]:
    """Block entropy used as a number. Slither weak-prng only sees timestamp, now, and blockhash modulo.

    blockhash itself, plus difficulty / coinbase / prevrandao / gasleft, and
    timestamp or block.number mixed into a hash or a modulo, are leads.
    A timestamp compared with a deadline is not.
    """
    clean = strip_comments(source or "", "solidity")
    findings: list[Finding] = []
    n = 0
    for fn in functions(source or "", clean, "solidity"):
        body = str(fn.get("body") or "")
        blockhash = bool(_BLOCKHASH.search(body))
        sourced = bool(_ENTROPY_SOURCE.search(body))
        sink = bool(_ENTROPY_SINK.search(body))
        if not blockhash and not (sourced and sink):
            continue
        n += 1
        findings.append(_finding(
            n=n,
            detector="weak-entropy",
            severity="low",
            title="Block entropy used in a hash or modulo",
            evidence="%s %s L%d — blockhash, block field, or gasleft feeds a hash or modulo. Shape only."
            % (fn.get("vis") or "", fn.get("name"), fn.get("line") or 0),
            address=address,
        ))
    return findings


def detect_unchecked_low_level(*, address: str, source: str) -> list[Finding]:
    """A call, send, or delegatecall whose success is not checked in that statement or later.

    require/assert/if around the call, or a bool binding that a later
    require/if reads, stays quiet. Delegatecall is recorded as an
    access-control shape. call and send stay unchecked-call shapes.
    """
    clean = strip_comments(source or "", "solidity")
    findings: list[Finding] = []
    n_call = 0
    n_delegate = 0
    for fn in functions(source or "", clean, "solidity"):
        # Internal helpers are where the unchecked call often sits. A checked
        # call, public or not, still stays quiet.
        statements = [part.strip() for part in str(fn.get("body") or "").split(";") if part.strip()]
        for index, stmt in enumerate(statements):
            if not _LOW_LEVEL.search(stmt) or _CHECKED_WORD.search(stmt):
                continue
            name = _bool_binding(stmt)
            later = ";".join(statements[index + 1:])
            if name and _checked_later(name, later):
                continue
            delegate = bool(_DELEGATE.search(stmt))
            if delegate:
                n_delegate += 1
                n = n_delegate
                detector = "unchecked-delegatecall"
                title = "Delegatecall whose success is not checked"
            else:
                n_call += 1
                n = n_call
                detector = "unchecked-low-level"
                title = "Low-level call whose success is not checked"
            findings.append(_finding(
                n=n,
                detector=detector,
                severity="low",
                title=title,
                evidence="%s %s L%d — %s. Shape only, not a path."
                % (fn.get("vis") or "", fn.get("name"), fn.get("line") or 0, " ".join(stmt.split())[:180]),
                address=address,
            ))
    return findings


def detect_hash_preimage_payout(*, address: str, source: str) -> list[Finding]:
    """A public payout gated on sha3/keccak256 of a single argument.

    That is the transaction-ordering shape (anyone can see the preimage and
    pay themselves first). A hash of an encoded tuple is not this shape.
    """
    clean = strip_comments(source or "", "solidity")
    findings: list[Finding] = []
    n = 0
    for fn in functions(source or "", clean, "solidity"):
        if not _exposed(str(fn.get("vis") or "")):
            continue
        body = str(fn.get("body") or "")
        if not (_PREIMAGE.search(body) and _PAYOUT.search(body)):
            continue
        n += 1
        findings.append(_finding(
            n=n,
            detector="hash-preimage-payout",
            severity="low",
            title="Payout gated on a hash preimage",
            evidence="%s %s L%d — sha3/keccak256 of one argument, then a value transfer. Shape only."
            % (fn.get("vis") or "", fn.get("name"), fn.get("line") or 0),
            address=address,
        ))
    return findings


def detect_unbounded_storage_loop(*, address: str, source: str) -> list[Finding]:
    """A loop bounded by a caller-supplied integer that writes storage.

    Fixed bounds such as `i < 350` are not this shape. The lead is the
    caller-chosen iteration count, which can exhaust gas.
    """
    clean = strip_comments(source or "", "solidity")
    findings: list[Finding] = []
    n = 0
    for fn in functions(source or "", clean, "solidity"):
        if not _exposed(str(fn.get("vis") or "")):
            continue
        header = str(fn.get("header") or "")
        body = str(fn.get("body") or "")
        params = _header_params(header)
        if not params or not _STORED.search(body):
            continue
        bounded = False
        for match in _FOR_BOUND.finditer(body):
            names = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", match.group(1))
            if params.intersection(names):
                bounded = True
                break
        if not bounded:
            continue
        n += 1
        findings.append(_finding(
            n=n,
            detector="unbounded-storage-loop",
            severity="low",
            title="Storage loop bounded by a caller-supplied count",
            evidence="%s %s L%d — for-loop condition uses a parameter and the body writes storage. Shape only."
            % (fn.get("vis") or "", fn.get("name"), fn.get("line") or 0),
            address=address,
        ))
    return findings


def run_custom_detectors(
    *,
    address: str,
    source: str,
    role: str = "",
    lane_ir: Optional[IRDocument] = None,
) -> list[Finding]:
    out: list[Finding] = []
    out.extend(detect_weak_auth_value_moves(address=address, source=source, lane_ir=lane_ir))
    out.extend(detect_share_asset_shape(address=address, source=source, role=role))
    out.extend(detect_oracle_freshness(address=address, source=source))
    out.extend(detect_pre08_arithmetic(address=address, source=source))
    out.extend(detect_weak_entropy(address=address, source=source))
    out.extend(detect_unchecked_low_level(address=address, source=source))
    out.extend(detect_hash_preimage_payout(address=address, source=source))
    out.extend(detect_unbounded_storage_loop(address=address, source=source))
    return out
