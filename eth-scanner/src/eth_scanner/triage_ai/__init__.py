"""Phase E — optional LLM triage explanations (never adds heat alone)."""

from eth_scanner.triage_ai.explain import explain_finding, llm_configured

__all__ = ["explain_finding", "llm_configured"]
