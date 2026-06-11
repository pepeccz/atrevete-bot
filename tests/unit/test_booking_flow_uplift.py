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
        assert (
            "Mapeo longitud → variante" in content
        ), "glossary.md must contain 'Mapeo longitud → variante' section header"

    def test_glossary_contains_peinado_largo_entry(self):
        content = _read("glossary.md")
        assert (
            "Peinado Largo" in content
        ), "glossary.md must contain 'Peinado Largo' in the length-map section"


class TestGlossaryLooseDatePhrases:
    """glossary.md must contain loose-date trigger phrases section."""

    def test_glossary_contains_frases_de_fecha_vaga_section(self):
        content = _read("glossary.md")
        assert (
            "Frases de fecha vaga" in content
        ), "glossary.md must contain 'Frases de fecha vaga' section"


class TestBookingFlowPasos:
    """booking_flow.md must have Paso 1 and key stylist/slot phrases.

    NOTE: Paso 0 was deliberately removed in commit 3a46daf (feat(prompts):
    service disambiguation UX cleanup — PR-3). The 7-step flow now starts at Paso 1.
    """

    def test_booking_flow_contains_paso_1(self):
        content = _read("booking_flow.md")
        assert "Paso 1" in content, "booking_flow.md must contain 'Paso 1'"

    def test_booking_flow_contains_paso_4(self):
        """Paso 4 (stylist step) must be present."""
        content = _read("booking_flow.md")
        assert "Paso 4" in content, "booking_flow.md must contain 'Paso 4'"

    def test_booking_flow_contains_payload_first_available_label(self):
        """Paso 4 must reference payload.first_available_label as option 0 (R24)."""
        content = _read("booking_flow.md")
        assert (
            "first_available_label" in content
        ), "booking_flow.md must contain 'first_available_label' — the no-preference stylist slot"


class TestCriticalRulesTwentyTwo:
    """critical_rules.md rule [R22] must reference get_next_available_options.

    NOTE: rules now use [R22] bracket format instead of old '22.' prefix (commit 8bf72b4).
    """

    def test_rule_22_references_get_next_available_options(self):
        content = _read("critical_rules.md")
        # Rule [R22] must exist and reference the sanctioned tool
        assert (
            "get_next_available_options" in content
        ), "critical_rules.md must reference 'get_next_available_options' in rule [R22]"
        # Locate rule [R22] text specifically
        lines = content.splitlines()
        rule_22_lines = [ln for ln in lines if "[R22]" in ln]
        assert rule_22_lines, "critical_rules.md must contain a rule marked '[R22]'"
        rule_22_block = " ".join(rule_22_lines)
        assert (
            "get_next_available_options" in rule_22_block
        ), "[R22] specifically must reference 'get_next_available_options'"


class TestToolsContractRouting:
    """tools_contract.md must contain routing sub-bullets referencing glossary loose-date section."""

    def test_tools_contract_references_glossary_loose_date(self):
        content = _read("tools_contract.md")
        assert "Frases de fecha vaga" in content, (
            "tools_contract.md must reference 'glossary.md § Frases de fecha vaga' "
            "in get_next_available_options routing sub-bullets"
        )


class TestExamplesFile:
    """examples.md must contain a safety gate example (Ejemplo 6 — R-37).

    NOTE: [booking_flow Paso 0] citation was removed when Paso 0 was dropped (commit 3a46daf).
    Ejemplo 6 is the closest structural equivalent — it shows the safety gate logic.
    """

    def test_examples_contains_safety_gate_example(self):
        content = _read("examples.md")
        assert (
            "Ejemplo 6" in content
        ), "examples.md must contain 'Ejemplo 6' — safety gate (R-37) example"


class TestUpdateBookingDocstring:
    """update_booking.py docstring must enumerate variant_required and reference glossary."""

    def test_update_booking_docstring_contains_variant_required(self):
        content = _read_tool("update_booking.py")
        assert (
            "variant_required" in content
        ), "update_booking.py docstring must list 'variant_required' in next_step enumeration"

    def test_update_booking_docstring_references_glossary_length_map(self):
        content = _read_tool("update_booking.py")
        assert "glossary.md § Mapeo longitud → variante" in content, (
            "update_booking.py docstring must reference "
            "'glossary.md § Mapeo longitud → variante' for length-to-variant translation"
        )


class TestAudienceQualifierMapping:
    """Change N (N5) — Paso 2 must map client audience qualifiers directly.

    V6 audit W3: "Corte dama" / "corte de mujer" / "para mi marido" already
    encode audience, yet the bot re-asked the 5-option enumeration.
    """

    def test_paso2_contains_qualifier_mapping(self):
        content = _read("booking_flow.md")
        lowered = content.lower()
        for qualifier in ("dama", "mujer", "señora", "caballero", "marido"):
            assert (
                qualifier in lowered
            ), f"booking_flow.md Paso 2 must map the qualifier '{qualifier}'"
        for audience in ("adult_female", "adult_male"):
            assert (
                audience in content
            ), f"booking_flow.md Paso 2 mapping must reference audience '{audience}'"

    def test_paso2_maps_children_and_baby(self):
        content = _read("booking_flow.md")
        lowered = content.lower()
        assert "niña" in lowered and "niño" in lowered and "bebé" in lowered
        assert "child_female" in content and "child_male" in content and "baby" in content

    def test_paso2_forbids_reasking_encoded_audience(self):
        content = _read("booking_flow.md")
        lowered = content.lower()
        assert "nunca" in lowered and (
            "vuelvas a preguntar" in lowered or "re-pregunt" in lowered
        ), "Paso 2 must forbid re-asking audience when the client's phrase already encodes it"

    def test_paso2_requires_open_question_not_enumeration(self):
        content = _read("booking_flow.md")
        assert "¿Es para ti o para otra persona?" in content, (
            "When asking IS needed, Paso 2 must use the open question "
            "'¿Es para ti o para otra persona?' instead of the 5-option enumeration"
        )
