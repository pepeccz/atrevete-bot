"""Scenario E — Light confirmation for explicitly enumerated services (HARD FAIL + xfail).

Tests that booking_flow.md Paso 3 encodes the dual phrasing rule:
  - LIGHT form for ≥2 explicitly enumerated services ("Entonces te anoto X e Y, ¿correcto?")
  - OPEN form for single/vague service ("¿Quieres añadir algún otro servicio...?")

These are STRUCTURAL tests — they read the prompt file directly and assert
that the dual phrasing is present. No LLM in the loop.

HARD FAIL: structural presence checks (does the section exist in the prompt?).
SOFT (xfail): wording-pattern sub-assertions about exact phrasing, since
  specific wording may evolve as the prompt is refined.

Refs: spec Scenario E, R3.2, tasks 4.6/4.9, design §2 Slice 4
"""

from __future__ import annotations

from pathlib import Path

import pytest

BOOKING_FLOW_PATH = (
    Path(__file__).parent.parent.parent.parent  # project root
    / "agent"
    / "prompts"
    / "shared"
    / "booking_flow.md"
)


def _load_booking_flow() -> str:
    """Load booking_flow.md content. Fail test if file not found."""
    if not BOOKING_FLOW_PATH.exists():
        pytest.fail(
            f"booking_flow.md not found at {BOOKING_FLOW_PATH}. "
            "Verify PR-3 is merged and the file path is correct."
        )
    return BOOKING_FLOW_PATH.read_text(encoding="utf-8")


def _extract_paso3_section(content: str) -> str:
    """Extract Paso 3 text from booking_flow.md.

    Returns the text from the Paso 3 header to the next Paso header.
    """
    lines = content.splitlines()
    paso3_lines: list[str] = []
    in_paso3 = False

    for line in lines:
        if "Paso 3" in line:
            in_paso3 = True
            paso3_lines.append(line)
            continue
        if in_paso3:
            # Stop at the next Paso header (Paso 4 onwards)
            if line.startswith("**Paso") and "Paso 3" not in line:
                break
            paso3_lines.append(line)

    return "\n".join(paso3_lines)


# ---------------------------------------------------------------------------
# HARD FAIL: structural presence checks
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_paso3_section_exists_in_booking_flow():
    """HARD FAIL: booking_flow.md must contain a Paso 3 section."""
    content = _load_booking_flow()
    assert "Paso 3" in content, (
        "'Paso 3' not found in booking_flow.md. "
        "Verify PR-3 Task 3.1 rewrote the booking_flow.md with 7-step structure."
    )


@pytest.mark.integration
def test_paso3_has_light_form_indicator():
    """HARD FAIL: Paso 3 must contain the LIGHT confirmation form indicator."""
    content = _load_booking_flow()
    paso3 = _extract_paso3_section(content)

    # The LIGHT form should reference "LIGERA" or "Entonces te anoto" or similar
    has_light_indicator = any(
        keyword in paso3
        for keyword in ["LIGERA", "LIGHT", "Entonces te anoto", "Entonces", "correcto"]
    )
    assert has_light_indicator, (
        f"Paso 3 must contain the LIGHT confirmation form for ≥2 enumerated services. "
        f"Paso 3 content:\n{paso3}\n"
        "Verify PR-3 Task 3.1 includes dual phrasing in Paso 3."
    )


@pytest.mark.integration
def test_paso3_has_open_form_indicator():
    """HARD FAIL: Paso 3 must contain the OPEN upsell form indicator."""
    content = _load_booking_flow()
    paso3 = _extract_paso3_section(content)

    # The OPEN form should reference "ABIERTA" or "añadir" or "otro servicio"
    has_open_indicator = any(
        keyword in paso3
        for keyword in ["ABIERTA", "OPEN", "añadir", "otro servicio", "Quieres añadir"]
    )
    assert has_open_indicator, (
        f"Paso 3 must contain the OPEN form for single/vague service requests. "
        f"Paso 3 content:\n{paso3}\n"
        "Verify PR-3 Task 3.1 includes dual phrasing in Paso 3."
    )


@pytest.mark.integration
def test_paso3_extras_asked_mentioned():
    """HARD FAIL: Paso 3 must reference extras_asked=true flag."""
    content = _load_booking_flow()
    paso3 = _extract_paso3_section(content)

    assert "extras_asked" in paso3, (
        f"Paso 3 must reference 'extras_asked=true' (round-trip flag). " f"Paso 3 content:\n{paso3}"
    )


@pytest.mark.integration
def test_booking_flow_has_both_dual_phrasing_lines():
    """HARD FAIL: both phrasing branches are present somewhere in booking_flow.md."""
    content = _load_booking_flow()

    # LIGHT branch — at least one of these phrases must appear
    has_light = "LIGERA" in content or "Entonces te anoto" in content
    # OPEN branch — at least one of these phrases must appear
    has_open = "ABIERTA" in content or "Quieres añadir" in content or "añadir algún" in content

    assert has_light, (
        "LIGHT confirmation phrasing ('LIGERA' or 'Entonces te anoto') not found "
        "in booking_flow.md. Verify PR-3 Task 3.1."
    )
    assert has_open, (
        "OPEN upsell phrasing ('ABIERTA' or 'Quieres añadir') not found "
        "in booking_flow.md. Verify PR-3 Task 3.1."
    )


# ---------------------------------------------------------------------------
# SOFT (xfail): exact wording assertions depend on LLM behavior
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.xfail(
    strict=False,
    reason=(
        "LLM wording assertion — soft check until stable replay fixtures available. "
        "The exact phrasing 'Entonces te anoto {a} y {b}, ¿correcto?' may vary "
        "as the prompt is refined."
    ),
)
def test_paso3_light_form_exact_phrasing():
    """SOFT: Paso 3 LIGHT form contains the template placeholder pattern."""
    content = _load_booking_flow()
    paso3 = _extract_paso3_section(content)

    # The template placeholder style should be visible in the LIGHT branch
    assert "{a}" in paso3 or "{lista}" in paso3 or "{servicio" in paso3, (
        f"Expected template placeholder (e.g., '{{a}}', '{{lista}}') in Paso 3 LIGHT form. "
        f"Paso 3:\n{paso3}"
    )


@pytest.mark.integration
@pytest.mark.xfail(
    strict=False,
    reason=(
        "LLM wording assertion — the 'una sola pregunta, un solo turno' constraint "
        "is an LLM behavioral property, not a static file assertion."
    ),
)
def test_paso3_single_question_constraint_mentioned():
    """SOFT: Paso 3 explicitly states the one-turn constraint."""
    content = _load_booking_flow()
    paso3 = _extract_paso3_section(content)

    has_one_turn = any(
        phrase in paso3
        for phrase in ["Una sola pregunta", "un solo turno", "una sola vez", "no repitas"]
    )
    assert has_one_turn, f"Paso 3 should mention the single-question constraint. Paso 3:\n{paso3}"
