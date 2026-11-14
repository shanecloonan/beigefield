"""Local sandbox fixtures. No chain, no broadcast, no calldata.

LeakyVault and the vault+strategy pair end with caller_profit_delta > 0.
SafeVault and the evidence-only solvency miss do not.
"""

from __future__ import annotations

from typing import Any

FIXTURES: dict[str, dict[str, Any]] = {
    "leaky": {
        "contract_name": "LeakyVault",
        "contracts": ["LeakyVault"],
        "address": "0x1111111111111111111111111111111111111111",
        "funds_usd": 1000.0,
        "delta": 1000,
        "rule": "no_third_party_balance_drop",
        "call_path": "poke",
        "mode": "profit",
    },
    "safe": {
        "contract_name": "SafeVault",
        "contracts": ["SafeVault"],
        "address": "0x2222222222222222222222222222222222222222",
        "funds_usd": 1000.0,
        "delta": 0,
        "rule": "no_third_party_balance_drop",
        "call_path": "withdraw",
        "mode": "pass",
    },
    "leaky-strategy": {
        "contract_name": "StrategyVault",
        "contracts": ["StrategyVault", "Strategy"],
        "address": "0x3333333333333333333333333333333333333333",
        "funds_usd": 1000.0,
        "delta": 1000,
        "rule": "no_caller_profit",
        "call_path": "skim",
        "mode": "profit",
    },
    "evidence-only": {
        "contract_name": "EvidenceVault",
        "contracts": ["EvidenceVault"],
        "address": "0x4444444444444444444444444444444444444444",
        "funds_usd": 50000.0,
        "delta": 0,
        "rule": "solvency_assets_cover_shares",
        "call_path": "convert",
        "mode": "fail",
    },
    "incentive": {
        "contract_name": "RewardVault",
        "contracts": ["RewardVault"],
        "address": "0x5555555555555555555555555555555555555555",
        "funds_usd": 800.0,
        "delta": 0,
        "rule": "first_caller_advantage",
        "call_path": "claim",
        "mode": "incentive",
        "who_benefits": "first caller",
        "what_breaks": "reward pays the first caller more than a later caller who deposited the same",
    },
}


def logs_for(spec: dict[str, Any]) -> dict[str, str]:
    """Native-looking logs for the four engines. Same invariant, same path."""
    mode = spec.get("mode") or "pass"
    rule = str(spec.get("rule") or "no_caller_profit")
    path = str(spec.get("call_path") or "")
    delta = int(spec.get("delta") or 0)
    extra = ""
    if spec.get("who_benefits"):
        extra += "who_benefits=%s\n" % spec["who_benefits"]
    if spec.get("what_breaks"):
        extra += "what_breaks=%s\n" % spec["what_breaks"]
    tail = "caller_profit_delta=%s\ncall_path=%s\n%s" % (delta, path, extra)
    if mode == "pass":
        return {
            "medusa": "[PASS] test_%s\ncaller_profit_delta=0\n" % rule,
            "echidna": "echidna_%s: passing\ncaller_profit_delta=0\n" % rule,
            "halmos": "[PASS] check_%s()\n" % rule,
            "ityfuzz": "no violation\ncaller_profit_delta=0\n",
        }
    if mode == "incentive":
        return {
            "medusa": "[FAIL] test_%s\n%s" % (rule, tail),
            "echidna": "echidna_%s: failed!\n%s" % (rule, tail),
            "halmos": "[FAIL] check_%s()\n%s" % (rule, tail),
            "ityfuzz": "Found a violation: %s\n%s" % (rule, tail),
        }
    return {
        "medusa": "[FAIL] test_%s\n%s" % (rule, tail),
        "echidna": "echidna_%s: failed!\n%s" % (rule, tail),
        "halmos": "[FAIL] check_%s()\n%s" % (rule, tail),
        "ityfuzz": "Found a violation: %s\n%s" % (rule, tail),
    }
