"""Advanced defensive engines: Slither → Mythril → corroboration → fuzz.

Leads never add heat alone. Heat requires confirming eth_call / fork check
or a failed Medusa/Foundry property on an anvil fork (proof, not an attack).
Never writes attack code or broadcasts transactions.
"""

from eth_scanner.engines.pipeline import AdvancedEngineReport, run_advanced_engines

__all__ = ["AdvancedEngineReport", "run_advanced_engines"]
