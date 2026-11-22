"""Staged score. A missing or empty stage does not dilute confirmed evidence."""

from eth_scanner.stages.fusion import annotate_stages, complete_stage, fuse

__all__ = ["annotate_stages", "complete_stage", "fuse"]
