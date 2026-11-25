"""Protocol-specific specs for a verified shortlist contract.

Generation is cached by source hash. An LLM is used only when a key is
already configured. Otherwise a deterministic template is written from the
ABI and NatSpec. The files are defensive properties. Nothing is broadcast.
"""
