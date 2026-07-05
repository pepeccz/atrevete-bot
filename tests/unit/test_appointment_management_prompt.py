"""Smoke tests anchoring the appointment_management_flow prompt to the
confirm/decline tool actions and middleware output strings.
"""

from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "agent"
    / "prompts"
    / "shared"
    / "appointment_management_flow.md"
)


def _prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_prompt_mentions_confirm_action():
    assert 'action="confirm"' in _prompt()


def test_prompt_mentions_decline_action():
    assert 'action="decline"' in _prompt()


def test_prompt_anchors_to_middleware_confirmation_line():
    """Anchors to the confirm action handling in the appointment management prompt."""
    assert "PENDIENTE" in _prompt()


# ---------------------------------------------------------------------------
# O6 — 48h cancellation policy guidance
# ---------------------------------------------------------------------------


def test_prompt_instructs_proactive_48h_policy_explanation():
    """O6: when cancellation is inside 48h window, prompt must require proactive
    explanation of the 48h policy (not just a reactive forward to human)."""
    text = _prompt()
    assert (
        "WINDOW" in text or "48 h" in text or "48h" in text
    ), "Prompt must reference the 48h window / WINDOW error code"


def test_prompt_48h_window_escalation_has_specific_reason():
    """O6: 48h window escalation must use a specific reason (not generic manual_request)."""
    text = _prompt()
    # Must mention cancellation_window_exception or similar
    assert (
        "cancellation_window" in text or "ventana" in text.lower()
    ), "Prompt must instruct using a specific escalation reason for 48h window cancellations"


def test_prompt_48h_window_explains_policy_to_customer():
    """O6: prompt must require explaining the policy empathetically before/while escalating."""
    text = _prompt().lower()
    assert (
        "empat" in text or "explica" in text or "política" in text
    ), "Prompt must require explaining the 48h cancellation policy to the customer"


def test_prompt_48h_window_never_phone_redirect():
    """O6: prompt must NEVER tell customer to call the salon (they're already on WhatsApp)."""
    text = _prompt().lower()
    assert (
        "canal oficial" in text or "whatsapp" in text or "nunca digas" in text or "nunca" in text
    ), "Prompt must prohibit phone redirect for 48h window escalation"


# ---------------------------------------------------------------------------
# sdd/context-coherence TASK-14/15 — imminent-appointment acknowledgment (D8b)
# ---------------------------------------------------------------------------


def _imminent_section() -> str:
    text = _prompt()
    start = text.find("Reconocer cita inminente")
    assert start >= 0, "appointment_management_flow.md missing the imminent-appointment section"
    return text[start:]


def test_imminent_appointment_section_present():
    """D8b: a dedicated section for imminent-appointment small-talk must exist."""
    assert "Reconocer cita inminente" in _prompt()


def test_imminent_appointment_section_references_upcoming_appointments_slot():
    """The rule must anchor on the <upcoming_appointments> slot, not invented state."""
    section = _imminent_section()
    assert "<upcoming_appointments>" in section


def test_imminent_appointment_section_is_day_relative_not_countdown():
    """Gatekeeper caveat 2: NEVER a countdown ('en X horas'); day-relative only."""
    section = _imminent_section().lower()
    assert "en x horas" not in section
    for forbidden in ("en 2 horas", "en 3 horas", "en 24 horas", "en unas horas"):
        assert forbidden not in section, f"Countdown phrasing {forbidden!r} must not appear"


def test_imminent_appointment_section_has_illustrative_examples():
    """Q1: rule + 2-3 illustrative example phrasings (not fixed copy)."""
    section = _imminent_section()
    example_count = section.count("Cliente:")
    assert example_count >= 2, f"Expected >=2 illustrative examples, found {example_count}"


def test_imminent_appointment_examples_use_day_relative_phrasing():
    """Examples must use day-relative phrasing (mañana / el <día de la semana>)."""
    section = _imminent_section().lower()
    assert "mañana" in section or "el miércoles" in section or "el jueves" in section


def test_imminent_appointment_section_forbids_generic_open_question():
    """Small-talk near an imminent appointment must not degrade to a generic open question."""
    section = _imminent_section().lower()
    assert "nunca" in section and "pregunta abierta" in section
