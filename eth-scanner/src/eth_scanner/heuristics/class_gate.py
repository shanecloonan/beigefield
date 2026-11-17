"""Class gate for advanced engines / research follow-up.

The historical policy was a tight allowlist of funds-at-risk families
(lending, vault, staking, pool, bridge, maker, plus custody). That skipped
a large set of otherwise-analyzable contracts (utility, unknown, routers,
and tokens with a real risky surface).

Modes (``ETH_SCANNER_CLASS_GATE_MODE``, default ``permissive``):

- ``allowlist`` — original money-at-risk allowlist only.
- ``permissive`` — analyze anything that is not a clearly inert plain
  ERC-20 / ERC-721 / wrap-token / NFT with no custody, withdraw-from-others,
  delegatecall, or upgradeability surface.
- ``off`` — class never blocks analysis. The $100 funds floor is separate
  and still applies in the engine pipeline.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# Keep in sync with heuristics.scope.FUNDS_AT_RISK_CLASSES plus custody.
ALLOWLIST_CLASSES = frozenset({
    "lending", "vault", "staking", "pool", "bridge", "maker", "custody",
})
# Only these can be denied in permissive mode, and only when the source has
# no risky surface. Routers, utility, unknown, proxies, etc. are analyzed.
INERT_CLASSES = frozenset({
    "token", "wrap-token", "nft", "nft-market",
})
CLASS_GATE_MODES = frozenset({"allowlist", "permissive", "off"})
DEFAULT_CLASS_GATE_MODE = "permissive"

# Upgrade / delegatecall: not a plain static token.
_DELEGATE_RE = re.compile(r"\bdelegatecall\b", re.I)
_UPGRADE_RE = re.compile(
    r"\b(upgradeTo|upgradeToAndCall|proxiableUUID|_upgradeTo|_upgradeToAndCall|"
    r"updateImplementation|upgradeabilityOwner|ERC1967Upgrade|"
    r"TransparentUpgradeableProxy|UUPSUpgradeable)\b",
    re.I,
)
# Custody / value-out verbs, including bare withdraw. A plain ERC-20 has
# transfer/approve only; a WETH-like wrap or a bank-style deposit/withdraw
# contract has a withdraw surface and is analyzed.
_CUSTODY_RE = re.compile(
    r"\bfunction\s+("
    r"withdraw\w*|claim(?:Funds|ETH|Ether|Token)?s?|refund|"
    r"liquidate|liquidationCall|borrow|repay|repayBorrow|seize|"
    r"flashLoan|flashloan|flashBorrow|"
    r"queueWithdrawal|completeQueuedWithdrawal|completeQueuedWithdrawals|"
    r"finalizeWithdrawal|finalizeWithdrawalTransaction|"
    r"proveWithdrawal|proveWithdrawalTransaction|"
    r"executeTransaction|execTransaction|"
    r"removeLiquidity|addLiquidity|joinPool|exitPool"
    r")\s*\(",
    re.I,
)


def class_gate_mode(explicit: Optional[str] = None) -> str:
    raw = (explicit if explicit is not None else os.environ.get("ETH_SCANNER_CLASS_GATE_MODE") or "").strip().lower()
    if raw in CLASS_GATE_MODES:
        return raw
    return DEFAULT_CLASS_GATE_MODE


# Low-level ETH sends (classic reentrancy banks). Not an ERC-20 transfer().
_ETH_SEND_RE = re.compile(
    r"\.call\s*\.value\s*\(|\.call\s*\{[^}]*value|\.send\s*\(",
    re.I,
)


def has_risky_surface(source: str) -> bool:
    """True when source shows upgradeability, delegatecall, or custody."""
    text = source or ""
    if not text.strip():
        return False
    return bool(
        _DELEGATE_RE.search(text) or _UPGRADE_RE.search(text)
        or _CUSTODY_RE.search(text) or _ETH_SEND_RE.search(text)
    )


def class_gate_allows(
    contract_class: str,
    *,
    source: str = "",
    mode: Optional[str] = None,
) -> tuple[bool, str]:
    """Whether the class gate lets advanced analysis run.

    Returns (allowed, reason). Does not consider the funds floor.
    """
    klass = (contract_class or "unknown").strip().lower() or "unknown"
    policy = class_gate_mode(mode)
    if policy == "off":
        return True, "class gate off"
    if policy == "allowlist":
        if klass in ALLOWLIST_CLASSES:
            return True, "allowlist class %s" % klass
        return False, "class %s not money-at-risk" % klass
    # permissive
    if klass in ALLOWLIST_CLASSES:
        return True, "funds-at-risk class %s" % klass
    if klass in INERT_CLASSES:
        if has_risky_surface(source):
            return True, "inert class %s has risky surface" % klass
        return False, "plain %s with no risky surface" % klass
    return True, "permissive class %s" % klass
