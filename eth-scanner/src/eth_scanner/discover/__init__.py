"""Recent-deployment discovery for the ETH scanner queue."""

from eth_scanner.discover.recent import (
    DiscoveredContract,
    DiscoveryStats,
    discover_recent_deployments,
)

__all__ = ["DiscoveredContract", "DiscoveryStats", "discover_recent_deployments"]
