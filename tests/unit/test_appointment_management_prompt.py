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
