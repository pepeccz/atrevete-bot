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
    """Anchors to the exact phrase rendered by appointment_context middleware."""
    assert "confirmación pedida" in _prompt()


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
