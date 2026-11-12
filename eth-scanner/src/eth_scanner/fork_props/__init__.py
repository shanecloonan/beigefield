"""Phase B — read-only fork property suites.

Output: invariant name, held/violated/unknown, minimized evidence (state
values only), severity. Never stores runnable attack sequences.
"""

from eth_scanner.fork_props.runner import ForkPropertyResult, run_fork_properties

__all__ = ["ForkPropertyResult", "run_fork_properties"]
