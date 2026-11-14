"""Lithium / C-Reduce style 1-minimization of a call script.

The interestingness test is "this shorter script is still a caller-profit
witness". The script is a list of call names. It is not a transaction and
it carries no calldata.
"""

from __future__ import annotations

from typing import Callable, Sequence


def still_profitable(sequence: Sequence[str], profit_calls: Sequence[str]) -> bool:
    """True when the script still contains a call that moved caller value."""
    wanted = set(profit_calls)
    return any(step in wanted for step in sequence)


def ddmin(sequence: Sequence[str], interesting: Callable[[list[str]], bool]) -> list[str]:
    """Return a 1-minimal subsequence. Empty when the input is not interesting."""
    data = list(sequence)
    if not data or not interesting(data):
        return []
    n = 2
    while len(data) >= 2:
        subset_len = max(1, len(data) // n)
        start = 0
        reduced = False
        while start < len(data):
            complement = data[:start] + data[start + subset_len:]
            if complement and interesting(complement):
                data = complement
                n = max(2, n - 1)
                reduced = True
                break
            start += subset_len
        if not reduced:
            if n >= len(data):
                break
            n = min(len(data), n * 2)
    return data
