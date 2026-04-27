"""T5 — RED tests: prompt-content assertions for booking-flow-natural-language-uplift.

These tests read the actual prompt/code files and assert that required content
is present. They fail before T6–T11 edit those files, and pass after.
"""

from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).parent.parent.parent / "agent" / "prompts" / "shared"
TOOLS_DIR = Path(__file__).parent.parent.parent / "agent" / "tools"


def _read(relative: str) -> str:
    return (BASE / relative).read_text(encoding="utf-8")


def _read_tool(relative: str) -> str:
    return (TOOLS_DIR / relative).read_text(encoding="utf-8")


class TestGlossaryLengthMap:
    """glossary.md must contain hair-length → variant mapping section."""

    def test_glossary_contains_length_map_header(self):
        content = _read("glossary.md")
        assert "Mapeo longitud → variante" in content, (
            "glossary.md must contain 'Mapeo longitud → variante' section header"
        )

    def test_glossary_contains_peinado_largo_entry(self):
        content = _read("glossary.md")
        assert "Peinado Largo" in content, (
            "glossary.md must contain 'Peinado Largo' in the length-map section"
        )


class TestGlossaryLooseDatePhrases:
    """glossary.md must contain loose-date trigger phrases section."""

    def test_glossary_contains_frases_de_fecha_vaga_section(self):
        content = _read("glossary.md")
        assert "Frases de fecha vaga" in content, (
            "glossary.md must contain 'Frases de fecha vaga' section"
        )


class TestBookingFlowPasos:
    """booking_flow.md must have Paso 0, Paso 1, and 'primera con disponibilidad'."""

    def test_booking_flow_contains_paso_0(self):
        content = _read("booking_flow.md")
        assert "Paso 0" in content, "booking_flow.md must contain 'Paso 0'"

    def test_booking_flow_contains_paso_1(self):
        content = _read("booking_flow.md")
        assert "Paso 1" in content, "booking_flow.md must contain 'Paso 1'"

    def test_booking_flow_contains_primera_con_disponibilidad(self):
        content = _read("booking_flow.md")
        assert "primera con disponibilidad" in content, (
            "booking_flow.md must contain 'primera con disponibilidad' stylist option"
        )


class TestCriticalRulesTwentyTwo:
    """critical_rules.md rule 22 must reference get_next_available_options."""

    def test_rule_22_references_get_next_available_options(self):
        content = _read("critical_rules.md")
        # Rule 22 must exist and reference the sanctioned tool
        assert "get_next_available_options" in content, (
            "critical_rules.md must reference 'get_next_available_options' in rule 22"
        )
        # Locate rule 22 text specifically
        lines = content.splitlines()
        rule_22_lines = [ln for ln in lines if ln.strip().startswith("22.")]
        assert rule_22_lines, "critical_rules.md must contain a rule starting with '22.'"
        rule_22_block = " ".join(rule_22_lines)
        assert "get_next_available_options" in rule_22_block, (
            "Rule 22 specifically must reference 'get_next_available_options'"
        )


class TestToolsContractRouting:
    """tools_contract.md must contain routing sub-bullets referencing glossary loose-date section."""

    def test_tools_contract_references_glossary_loose_date(self):
        content = _read("tools_contract.md")
        assert "Frases de fecha vaga" in content, (
            "tools_contract.md must reference 'glossary.md § Frases de fecha vaga' "
            "in get_next_available_options routing sub-bullets"
        )


class TestExamplesFile:
    """examples.md must contain booking_flow Paso 0 citation."""

    def test_examples_contains_booking_flow_paso_0_citation(self):
        content = _read("examples.md")
        assert "[booking_flow Paso 0]" in content, (
            "examples.md must cite '[booking_flow Paso 0]' in the example conversation"
        )


class TestUpdateBookingDocstring:
    """update_booking.py docstring must enumerate variant_required and reference glossary."""

    def test_update_booking_docstring_contains_variant_required(self):
        content = _read_tool("update_booking.py")
        assert "variant_required" in content, (
            "update_booking.py docstring must list 'variant_required' in next_step enumeration"
        )

    def test_update_booking_docstring_references_glossary_length_map(self):
        content = _read_tool("update_booking.py")
        assert "glossary.md § Mapeo longitud → variante" in content, (
            "update_booking.py docstring must reference "
            "'glossary.md § Mapeo longitud → variante' for length-to-variant translation"
        )
