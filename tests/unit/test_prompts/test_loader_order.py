"""Tests that load_system_prompt() assembles sections in required order."""
from __future__ import annotations

import importlib


def _reload_loader():
    """Force fresh load of loader (bypasses lru_cache)."""
    import agent.prompts.loader as m
    importlib.reload(m)
    return m


def test_examples_appears_after_critical_rules() -> None:
    m = _reload_loader()
    prompt = m.load_system_prompt()
    idx_rules = prompt.find("[R9b]")  # unique string in critical_rules
    idx_examples = prompt.find("### Ejemplo 1")  # unique string in examples
    assert idx_rules != -1, "critical_rules content not found in assembled prompt"
    assert idx_examples != -1, "examples.md content not found in assembled prompt"
    assert idx_rules < idx_examples, (
        "examples.md must appear AFTER critical_rules.md in assembled prompt"
    )


def test_tools_contract_appears_after_booking_flow() -> None:
    m = _reload_loader()
    prompt = m.load_system_prompt()
    # Anchor: "Paso 1 — Servicios" is a reliable unique string in booking_flow.md
    idx_flow = prompt.find("Paso 1 — Servicios")  # unique string in booking_flow
    # Use a more unique string from tools_contract
    idx_tools = prompt.find("Nunca llamar")  # unique to tools_contract
    assert idx_flow != -1, "booking_flow content not found in assembled prompt"
    assert idx_tools != -1, "tools_contract content not found in assembled prompt"
    assert idx_flow < idx_tools, (
        "tools_contract.md must appear AFTER booking_flow.md in assembled prompt"
    )
