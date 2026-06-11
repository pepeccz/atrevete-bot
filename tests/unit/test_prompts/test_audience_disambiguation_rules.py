"""Tests for audience/variant disambiguation prompt rules.

Validates:
- critical_rules.md rule 9b uses catalog-keyed metadata tokens (no hardcoded service names)
- examples.md has Ejemplo 1 (variant disambiguation example)
- booking_flow.md has Paso 1 (services step) — Paso 0 was deliberately dropped (commit 3a46daf)
- tools_contract.md has _required routing clause in update_booking entry

Refs: spec R1-R4/E1-E3/F1-F3/T1-T2, design Decisions 1-4
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS = Path(__file__).parent.parent.parent.parent / "agent" / "prompts" / "shared"

_CRITICAL_RULES = _PROMPTS / "critical_rules.md"
_EXAMPLES = _PROMPTS / "examples.md"
_BOOKING_FLOW = _PROMPTS / "booking_flow.md"
_TOOLS_CONTRACT = _PROMPTS / "tools_contract.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# critical_rules.md — rule 9b catalog-keyed clause
# ---------------------------------------------------------------------------


def test_critical_rules_contains_dimension_token() -> None:
    """R1/R2: rule 9b must reference 'dimension' catalog token."""
    content = _read(_CRITICAL_RULES)
    assert "dimension" in content, "critical_rules.md must contain 'dimension'"


def test_critical_rules_contains_audience_token() -> None:
    """R1/R2: rule 9b must reference 'audience' catalog token."""
    content = _read(_CRITICAL_RULES)
    assert "audience" in content, "critical_rules.md must contain 'audience'"


def test_critical_rules_contains_parent_service_name_token() -> None:
    """R1/R2: rule 9b must reference 'parent_service_name' catalog token."""
    content = _read(_CRITICAL_RULES)
    assert "parent_service_name" in content, "critical_rules.md must contain 'parent_service_name'"


def test_critical_rules_no_hardcoded_service_names() -> None:
    """R2: rule 9b must NOT hardcode specific service names in the 9b block."""
    content = _read(_CRITICAL_RULES)
    # Find the 9b block: from "[R9b]" to the next rule header
    lines = content.splitlines()
    in_9b_block = False
    block_lines: list[str] = []
    for line in lines:
        if line.strip().startswith("[R9b]"):
            in_9b_block = True
        elif in_9b_block and line.strip().startswith("[R") and not line.strip().startswith("[R9b]"):
            break
        if in_9b_block:
            block_lines.append(line.lower())

    block = "\n".join(block_lines)
    # The rule must not hardcode specific service names outside of illustrative (ej.) parens
    forbidden_standalone = ["corte dama", "corte caballero", "corte niño", "corte niña"]
    for name in forbidden_standalone:
        assert (
            name not in block or "ej." in block
        ), f"9b block must not hardcode '{name}' (use catalog metadata tokens instead)"


# ---------------------------------------------------------------------------
# examples.md — has variant disambiguation example (Ejemplo 1)
# ---------------------------------------------------------------------------


def test_examples_contains_variant_disambiguation_example() -> None:
    """examples.md must contain Ejemplo 1 (variant/peinado disambiguation)."""
    content = _read(_EXAMPLES)
    assert (
        "Ejemplo 1" in content
    ), "examples.md must contain 'Ejemplo 1' — peinado variant disambiguation"


def test_examples_variant_example_contains_peinado_keyword() -> None:
    """Ejemplo 1 must contain peinado-related variant keywords."""
    content = _read(_EXAMPLES)
    lower = content.lower()
    # Ejemplo 1 is about peinado disambiguation
    idx = lower.find("ejemplo 1")
    assert idx != -1
    snippet = lower[idx : idx + 500]
    variant_keywords = ["peinado", "variante", "moldeado"]
    assert any(
        kw in snippet for kw in variant_keywords
    ), f"Ejemplo 1 must contain variant keywords; found: {snippet[:200]}"


# ---------------------------------------------------------------------------
# booking_flow.md — Paso 1 present (Paso 0 was deliberately removed in 3a46daf)
# ---------------------------------------------------------------------------


def test_booking_flow_paso1_present() -> None:
    """F1/F3: booking_flow.md must declare 'Paso 1' (services step)."""
    content = _read(_BOOKING_FLOW)
    assert "Paso 1" in content, "booking_flow.md must contain 'Paso 1'"


def test_booking_flow_paso1_contains_update_booking_call() -> None:
    """F1: Paso 1 must reference the update_booking call."""
    content = _read(_BOOKING_FLOW)
    idx1 = content.find("Paso 1")
    idx2 = content.find("Paso 2")
    assert idx1 != -1, "booking_flow.md must contain 'Paso 1'"
    assert idx2 != -1, "booking_flow.md must contain 'Paso 2'"
    paso1_block = content[idx1:idx2]
    assert "update_booking" in paso1_block, "Paso 1 block must contain 'update_booking'"


def test_booking_flow_paso1_before_paso2() -> None:
    """F3: Paso 1 must appear before Paso 2 in document order."""
    content = _read(_BOOKING_FLOW)
    idx1 = content.find("Paso 1")
    idx2 = content.find("Paso 2")
    assert idx1 != -1, "booking_flow.md must contain 'Paso 1'"
    assert idx2 != -1, "booking_flow.md must contain 'Paso 2'"
    assert idx1 < idx2, f"'Paso 1' (pos {idx1}) must appear before 'Paso 2' (pos {idx2})"


def test_booking_flow_paso2_references_required_suffix() -> None:
    """F2: Paso 2 must cover *_required routing (at minimum audience_required)."""
    content = _read(_BOOKING_FLOW)
    idx2 = content.find("Paso 2")
    idx3 = content.find("Paso 2.5")
    assert idx2 != -1, "booking_flow.md must contain 'Paso 2'"
    # Search from Paso 2 to end of file
    paso2_block = content[idx2 : idx3 if idx3 != -1 else idx2 + 1000]
    assert (
        "audience_required" in paso2_block or "_required" in paso2_block
    ), "Paso 2 must reference '*_required' routing (at minimum audience_required)"


# ---------------------------------------------------------------------------
# tools_contract.md — update_booking _required clause
# ---------------------------------------------------------------------------


def test_tools_contract_update_booking_mentions_required_suffix() -> None:
    """T1/T2: tools_contract.md update_booking entry must mention '_required' routing."""
    content = _read(_TOOLS_CONTRACT)
    assert (
        "_required" in content
    ), "tools_contract.md must contain a '_required' routing clause in update_booking entry"


def test_tools_contract_update_booking_first_action_clause() -> None:
    """T1: update_booking entry must state it should be called first on service-mention turn."""
    content = _read(_TOOLS_CONTRACT).lower()
    # Look for the "first" / "primer" instruction near update_booking
    idx = content.find("update_booking")
    assert idx != -1
    # Check within reasonable proximity (500 chars before/after) for first-call directive
    snippet = content[max(0, idx - 100) : idx + 600]
    first_keywords = ["primer", "primera", "primero", "first", "antes de"]
    assert any(
        kw in snippet for kw in first_keywords
    ), f"tools_contract.md update_booking entry must state 'call first' directive; found: {snippet[:300]}"
