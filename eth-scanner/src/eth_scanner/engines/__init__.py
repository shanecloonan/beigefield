"""Advanced defensive engines: Slither → Mythril → read-only corroboration.

Leads never add heat alone. Heat requires a confirming eth_call / fork check.
Never writes attack code or broadcasts transactions.
"""

from eth_scanner.engines.pipeline import AdvancedEngineReport, run_advanced_engines

__all__ = ["AdvancedEngineReport", "run_advanced_engines"]
