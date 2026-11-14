"""Curated master-list feed for the defensive ETH invariant scanner.

Read-only. The committed list is the primary address source. Discovery of
new creates stays behind an explicit flag.
"""

from eth_scanner.feed.master_list import (
    MasterCandidate,
    default_master_list_path,
    load_master_candidates,
)
from eth_scanner.feed.runner import CURSOR_ID, MasterListProgress, run_master_list

__all__ = [
    "CURSOR_ID",
    "MasterCandidate",
    "MasterListProgress",
    "default_master_list_path",
    "load_master_candidates",
    "run_master_list",
]
