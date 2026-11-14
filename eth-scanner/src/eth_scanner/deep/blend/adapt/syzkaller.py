"""Syzkaller-style resource descriptions for cross-contract calls.

Each ABI method is a syscall. Typed resources (shares, approvals, oracle
answers, debt) must be produced before a later call can consume them.
The result is a dependent chain such as deposit → harvest → redeem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class Method:
    contract: str
    name: str
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return "%s.%s" % (self.contract, self.name)


# Vault + strategy + oracle + keeper. Resources move between them.
PROTOCOL = (
    Method("Vault", "deposit", consumes=(), produces=("shares",)),
    Method("Oracle", "setAnswer", consumes=(), produces=("oracle_answer",)),
    Method("Strategy", "harvest", consumes=("shares", "oracle_answer"), produces=("reward",)),
    Method("Keeper", "poke", consumes=("oracle_answer", "shares"), produces=("debt",)),
    Method("Vault", "redeem", consumes=("shares",), produces=()),
)


def dependent_chains(methods: Iterable[Method] | None = None, *, limit: int = 12) -> list[list[str]]:
    """Every chain is resource-legal. A consumer never appears before its producer."""
    pool = list(PROTOCOL if methods is None else methods)
    chains: list[list[Method]] = [[]]
    finished: list[list[str]] = []
    while chains and len(finished) < limit:
        current = chains.pop(0)
        have = {produced for step in current for produced in step.produces}
        extended = False
        for method in pool:
            if method in current:
                continue
            if not set(method.consumes).issubset(have):
                continue
            nxt = current + [method]
            chains.append(nxt)
            finished.append([step.label for step in nxt])
            extended = True
            if len(finished) >= limit:
                break
        if not extended and current:
            labels = [step.label for step in current]
            if labels not in finished:
                finished.append(labels)
    # Prefer the longer chains; drop the empty start.
    finished = [chain for chain in finished if chain]
    finished.sort(key=lambda chain: (-len(chain), chain))
    unique: list[list[str]] = []
    for chain in finished:
        if chain not in unique:
            unique.append(chain)
    return unique[:limit]


def chain_is_legal(chain: list[str], methods: Optional[Iterable[Method]] = None) -> bool:
    by_label = {method.label: method for method in (methods or PROTOCOL)}
    have: set[str] = set()
    for label in chain:
        method = by_label.get(label)
        if method is None:
            return False
        if not set(method.consumes).issubset(have):
            return False
        have.update(method.produces)
    return True
