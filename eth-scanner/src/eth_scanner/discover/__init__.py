"""Recent-deployment and fresh-deploy discovery for the ETH scanner queue."""

from eth_scanner.discover.fresh import (
    FRESH_SOURCE,
    FreshDeployStats,
    enqueue_fresh_contracts,
    run_fresh_deploy_discovery,
)
from eth_scanner.discover.recent import (
    DiscoveredContract,
    DiscoveryStats,
    discover_recent_deployments,
)

__all__ = [
    "DiscoveredContract",
    "DiscoveryStats",
    "FRESH_SOURCE",
    "FreshDeployStats",
    "discover_recent_deployments",
    "enqueue_fresh_contracts",
    "run_fresh_deploy_discovery",
]
