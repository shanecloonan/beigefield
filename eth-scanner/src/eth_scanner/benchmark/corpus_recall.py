"""Offline recall over bug classes from three public corpora.

The labels are ours: a class and the detector that should name it. The
snippets are original shapes, not copied incidents. scabench and Web3Bugs
are MIT and are not vendored. DeFiVulnLabs has no license, so it is not
fetched. Nothing here adds heat.
"""

from __future__ import annotations

from typing import Any

BASELINE = 0.9

# Original shapes. Each one is a class label, not an incident reproduction.
_LABELS: tuple[dict[str, str], ...] = (
    {
        "id": "reentrancy-eth",
        "corpus": "scabench",
        "bug_class": "reentrancy",
        "expected": "reentrancy-eth",
        "source": (
            "contract Pool {\n"
            "  function withdraw() external {\n"
            "    msg.sender.call{value: address(this).balance}(\"\");\n"
            "    balances[msg.sender] = 0;\n"
            "  }\n"
            "}\n"
        ),
    },
    {
        "id": "unprotected-initializer",
        "corpus": "web3bugs",
        "bug_class": "initializer",
        "expected": "unprotected-initializer",
        "source": "contract Box { function initialize() public { owner = msg.sender; } }\n",
    },
    {
        "id": "tx-origin-auth",
        "corpus": "web3bugs",
        "bug_class": "tx-origin",
        "expected": "tx-origin-auth",
        "source": "contract Box { function withdraw() external { require(tx.origin == owner); } }\n",
    },
    {
        "id": "unprotected-upgrade",
        "corpus": "scabench",
        "bug_class": "upgrade",
        "expected": "unprotected-upgrade",
        "source": "contract Proxy { function upgradeTo(address next) external { impl = next; } }\n",
    },
    {
        "id": "public-selfdestruct",
        "corpus": "web3bugs",
        "bug_class": "selfdestruct",
        "expected": "public-selfdestruct",
        "source": "contract Box { function close() external { selfdestruct(payable(msg.sender)); } }\n",
    },
    {
        "id": "delegatecall-user-target",
        "corpus": "scabench",
        "bug_class": "delegatecall",
        "expected": "delegatecall-user-target",
        "source": "contract Box { function poke(address target) external { target.delegatecall(\"\"); } }\n",
    },
    {
        "id": "share-inflation-empty",
        "corpus": "scabench",
        "bug_class": "share-inflation",
        "expected": "share-inflation-empty",
        "source": "contract Vault { function deposit() external { if (totalSupply() == 0) { _mint(msg.sender, 1); } } }\n",
    },
    {
        "id": "spot-price-value",
        "corpus": "web3bugs",
        "bug_class": "spot-price",
        "expected": "spot-price-value",
        "source": "contract Pool { function swap() external { uint p = getReserves() / 2; token.transfer(msg.sender, p); } }\n",
    },
    {
        "id": "share-balance",
        "corpus": "web3bugs",
        "bug_class": "share-balance",
        "expected": "share-balance",
        "source": "contract Vault { function deposit() external { uint b = token.balanceOf(address(this)); _mint(msg.sender, b); } }\n",
    },
    {
        "id": "signature-replay",
        "corpus": "defivulnlabs",
        "bug_class": "signature-replay",
        "expected": "signature-replay",
        "source": "contract Box { function claim() external { } }\n",
    },
)


def detector_names(source: str) -> set[str]:
    """Corpus rules and the three shape leads. No other engine is required."""
    from eth_scanner.benchmark.leads import benchmark_lead_names
    from eth_scanner.logic.corpus import scan_source

    names = {str(row.get("rule") or "") for row in scan_source(source)}
    names.update(benchmark_lead_names(source))
    names.discard("")
    return names


def recall_report() -> dict[str, Any]:
    """Hits over labeled classes. The source text is not returned."""
    rows: list[dict[str, Any]] = []
    hits = 0
    for label in _LABELS:
        found = detector_names(label["source"])
        hit = label["expected"] in found
        hits += int(hit)
        rows.append({
            "id": label["id"],
            "corpus": label["corpus"],
            "bug_class": label["bug_class"],
            "expected": label["expected"],
            "hit": hit,
        })
    labeled = len(_LABELS)
    recall = (hits / labeled) if labeled else 0.0
    return {
        "labeled": labeled,
        "hits": hits,
        "misses": labeled - hits,
        "recall": recall,
        "baseline": BASELINE,
        "passes_baseline": recall + 1e-9 >= BASELINE,
        "heat_contribution": 0,
        "rows": rows,
        "note": (
            "scabench and Web3Bugs are not vendored. "
            "DeFiVulnLabs is not fetched. The snippets are original."
        ),
    }
