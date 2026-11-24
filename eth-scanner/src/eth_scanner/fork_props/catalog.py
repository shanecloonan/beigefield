"""Per-class invariant catalog (defensive properties only)."""

from __future__ import annotations

from typing import Any


# Each entry is a human-facing property. Evaluation is eth_call / forge view.
CLASS_PROPERTIES: dict[str, list[dict[str, Any]]] = {
    "vault": [
        {
            "id": "erc4626-solvency",
            "name": "convertToAssets(totalSupply) <= totalAssets",
            "severity": "high",
            "summary": "Fails only when the asset balance is short of the claim. Async redeems, custodian supply, and a clean price ratio stay unknown.",
        },
        {
            "id": "erc4626-asset-balance",
            "name": "asset balance vs totalAssets",
            "severity": "medium",
            "summary": "Vault-held asset balance should cover or explain totalAssets.",
        },
        {
            "id": "erc4626-previewRedeem",
            "name": "previewRedeem consistency",
            "severity": "low",
            "summary": "previewRedeem may be lower (withdrawal fee). It fails only when it pays more than convertToAssets.",
        },
    ],
    "staking": [
        {
            "id": "staking-supply",
            "name": "totalSupply readable / conservation shape",
            "severity": "medium",
            "summary": "Total staked shares are readable; per-account stake cannot exceed total.",
        },
    ],
    "lending": [
        {
            "id": "lending-cash-borrows",
            "name": "cash + borrows covers supply shape",
            "severity": "high",
            "summary": "getCash + totalBorrows should cover totalSupply (implementation slack allowed).",
        },
    ],
    "pool": [
        {
            "id": "pool-reserves-readable",
            "name": "reserve / liquidity views readable",
            "severity": "medium",
            "summary": "AMM/LP reserve views respond without reverting.",
        },
    ],
    "bridge": [
        {
            "id": "bridge-roles",
            "name": "admin/owner identity",
            "severity": "high",
            "summary": "Bridge admin is identifiable (EOA vs contract/timelock).",
        },
    ],
    "governance": [
        {
            "id": "gov-timelock-or-multisig",
            "name": "privileged key is not a lone hot EOA when funds are large",
            "severity": "high",
            "summary": "Owner/admin kind classified; EOA on large TVL is evidence, not a verdict.",
        },
    ],
    "custody": [
        {
            "id": "roles-owner",
            "name": "owner/admin identity",
            "severity": "medium",
            "summary": "Custody admin key kind (EOA vs contract).",
        },
        {
            "id": "privileged-callable",
            "name": "privileged selectors revert for arbitrary EOA",
            "severity": "high",
            "summary": "Static eth_call of pause/upgrade/transferOwnership from a random EOA must revert.",
        },
    ],
}


def properties_for_class(contract_class: str) -> list[dict[str, Any]]:
    klass = (contract_class or "custody").lower()
    if klass in CLASS_PROPERTIES:
        return list(CLASS_PROPERTIES[klass])
    # Fallback: vault-like + custody roles for unknown funded venues.
    out = list(CLASS_PROPERTIES.get("custody") or [])
    if klass in {"vault", "unknown"}:
        out = list(CLASS_PROPERTIES["vault"]) + out
    return out
