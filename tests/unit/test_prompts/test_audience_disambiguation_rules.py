"""RED → GREEN tests for audience/variant disambiguation prompt rules.

Validates:
- critical_rules.md rule 9b uses catalog-keyed metadata tokens (no hardcoded service names)
- examples.md has examples 4 (audience) and 5 (variant)
- booking_flow.md has Paso 0 before Paso 1
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
    # Find the 9b block: from "9b" to the next rule header "9b-response" or "10."
    lines = content.splitlines()
    in_9b_block = False
    block_lines: list[str] = []
    for line in lines:
        if line.startswith("9b-trigger") or (line.startswith("9b.") and "desambiguación" in line.lower()):
            in_9b_block = True
        elif in_9b_block and (line.startswith("9b-response") or line.startswith("10.")):
            break
        if in_9b_block:
            block_lines.append(line.lower())

    block = "\n".join(block_lines)
    # The rule must not hardcode specific service names outside of illustrative (ej.) parens
    # We check the entire block does not have standalone hardcoded names outside parens
    forbidden_standalone = ["corte dama", "corte caballero", "corte niño", "corte niña"]
    for name in forbidden_standalone:
        assert name not in block or "ej." in block, (
            f"9b block must not hardcode '{name}' (use catalog metadata tokens instead)"
        )


# ---------------------------------------------------------------------------
# examples.md — examples 4 and 5
# ---------------------------------------------------------------------------


def test_examples_contains_audience_disambiguation_example() -> None:
    """E1/E3: examples.md must contain example 4 (audience/haircut disambiguation)."""
    content = _read(_EXAMPLES)
    assert "4-audience-disambiguation" in content, (
        "examples.md must contain example id '4-audience-disambiguation'"
    )


def test_examples_contains_variant_disambiguation_example() -> None:
    """E2/E3: examples.md must contain example 5 (variant/wax disambiguation)."""
    content = _read(_EXAMPLES)
    assert "5-variant-disambiguation" in content, (
        "examples.md must contain example id '5-variant-disambiguation'"
    )


def test_examples_audience_example_contains_audience_keywords() -> None:
    """E1: example 4 must contain audience keywords (señora/caballero or similar)."""
    content = _read(_EXAMPLES)
    lower = content.lower()
    # Check at least one audience-dimension keyword is present after the example id
    idx = lower.find("4-audience-disambiguation")
    assert idx != -1
    snippet = lower[idx : idx + 500]
    audience_keywords = ["señora", "caballero", "niña", "niño", "bebé", "dama"]
    assert any(kw in snippet for kw in audience_keywords), (
        f"Example 4 must contain audience keywords; found: {snippet[:200]}"
    )


def test_examples_variant_example_contains_zone_keyword() -> None:
    """E2: example 5 must contain a body-zone keyword."""
    content = _read(_EXAMPLES)
    lower = content.lower()
    idx = lower.find("5-variant-disambiguation")
    assert idx != -1
    snippet = lower[idx : idx + 500]
    zone_keywords = ["zona", "axilas", "piernas", "cera", "depila"]
    assert any(kw in snippet for kw in zone_keywords), (
        f"Example 5 must contain body-zone keywords; found: {snippet[:200]}"
    )


# ---------------------------------------------------------------------------
# booking_flow.md — Paso 0 before Paso 1
# ---------------------------------------------------------------------------


def test_booking_flow_paso0_present() -> None:
    """F1/F3: booking_flow.md must declare 'Paso 0' before 'Paso 1'."""
    content = _read(_BOOKING_FLOW)
    assert "Paso 0" in content, "booking_flow.md must contain 'Paso 0'"


def test_booking_flow_paso0_before_paso1() -> None:
    """F3: Paso 0 must appear before Paso 1 in document order."""
    content = _read(_BOOKING_FLOW)
    idx0 = content.find("Paso 0")
    idx1 = content.find("Paso 1")
    assert idx0 != -1, "booking_flow.md must contain 'Paso 0'"
    assert idx1 != -1, "booking_flow.md must contain 'Paso 1'"
    assert idx0 < idx1, f"'Paso 0' (pos {idx0}) must appear before 'Paso 1' (pos {idx1})"


def test_booking_flow_paso0_contains_update_booking_call() -> None:
    """F1: Paso 0 must reference the update_booking call."""
    content = _read(_BOOKING_FLOW)
    idx0 = content.find("Paso 0")
    idx1 = content.find("Paso 1")
    assert idx0 != -1 and idx1 != -1
    paso0_block = content[idx0:idx1]
    assert "update_booking" in paso0_block, (
        "Paso 0 block must contain 'update_booking'"
    )


def test_booking_flow_paso0_references_required_suffix() -> None:
    """F2: Paso 0 must cover *_required routing (at minimum audience_required)."""
    content = _read(_BOOKING_FLOW)
    idx0 = content.find("Paso 0")
    idx1 = content.find("Paso 1")
    assert idx0 != -1 and idx1 != -1
    paso0_block = content[idx0:idx1]
    assert "audience_required" in paso0_block or "_required" in paso0_block, (
        "Paso 0 must reference '*_required' routing (at minimum audience_required)"
    )


# ---------------------------------------------------------------------------
# tools_contract.md — update_booking _required clause
# ---------------------------------------------------------------------------


def test_tools_contract_update_booking_mentions_required_suffix() -> None:
    """T1/T2: tools_contract.md update_booking entry must mention '_required' routing."""
    content = _read(_TOOLS_CONTRACT)
    assert "_required" in content, (
        "tools_contract.md must contain a '_required' routing clause in update_booking entry"
    )


def test_tools_contract_update_booking_first_action_clause() -> None:
    """T1: update_booking entry must state it should be called first on service-mention turn."""
    content = _read(_TOOLS_CONTRACT).lower()
    # Look for the "first" / "primer" instruction near update_booking
    idx = content.find("update_booking")
    assert idx != -1
    # Check within reasonable proximity (500 chars before/after) for first-call directive
    snippet = content[max(0, idx - 100) : idx + 600]
    first_keywords = ["primer", "primera", "primero", "first", "antes de"]
    assert any(kw in snippet for kw in first_keywords), (
        f"tools_contract.md update_booking entry must state 'call first' directive; found: {snippet[:300]}"
    )
