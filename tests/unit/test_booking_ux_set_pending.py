"""
Tests for BookingModeNode._set_pending_options().

Spec: Task 5.3 — booking-ux-fixes
Scenarios:
  (a) Numbered list in response, last_services empty → pending_service_options set
  (b) last_services set, last_stylist empty → pending_stylist_options set
  (c) Both already set → no-op
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def booking_node():
    """Create a bare BookingModeNode (no LLM needed for these unit tests)."""
    from agent.modes.booking_mode import BookingModeNode

    return BookingModeNode(tools=[])


# ──────────────────────────────────────────────────────────────────────────────
# (a) Service options: last_services empty → pending_service_options set
# ──────────────────────────────────────────────────────────────────────────────

_SERVICE_LIST_RESPONSE = """\
¿Qué tipo de mechas quieres?
1. Mechas completas
2. Mechas balayage
3. Mechas babylights
"""

_SERVICE_LIST_RESPONSE_WITH_EMOJIS = """\
¿Qué tipo de mechas quieres?
1. Mechas completas ✨
2. Mechas balayage 💇‍♀️
3. Mechas babylights 🌸
"""


def test_service_pending_options_set_when_services_empty(booking_node) -> None:
    """Spec scenario (a): numbered list + empty last_services → pending_service_options."""
    mode_context: dict = {}

    booking_node._set_pending_options(mode_context, _SERVICE_LIST_RESPONSE)

    assert "pending_service_options" in mode_context
    assert mode_context["pending_service_options"] == [
        "Mechas completas",
        "Mechas balayage",
        "Mechas babylights",
    ]
    assert "pending_stylist_options" not in mode_context


def test_service_pending_options_strips_emojis(booking_node) -> None:
    """Emoji tails are stripped from extracted option names."""
    mode_context: dict = {}

    booking_node._set_pending_options(mode_context, _SERVICE_LIST_RESPONSE_WITH_EMOJIS)

    assert "pending_service_options" in mode_context
    names = mode_context["pending_service_options"]
    for name in names:
        # No emoji should remain
        assert "✨" not in name
        assert "🌸" not in name


def test_no_numbered_list_no_op(booking_node) -> None:
    """Plain text without numbered list → no pending options set."""
    mode_context: dict = {}
    response_text = "¿Tienes alguna preferencia de estilista?"

    booking_node._set_pending_options(mode_context, response_text)

    assert "pending_service_options" not in mode_context
    assert "pending_stylist_options" not in mode_context


# ──────────────────────────────────────────────────────────────────────────────
# (b) Stylist options: last_services set, last_stylist empty → pending_stylist_options
# ──────────────────────────────────────────────────────────────────────────────

_STYLIST_LIST_RESPONSE = """\
¿Tienes preferencia de estilista?
1. Ana
2. Victor
3. Marta
4. Pilar
5. Sin preferencia 👌
"""


def test_stylist_pending_options_set_when_service_known(booking_node) -> None:
    """Spec scenario (b): service known, stylist missing → pending_stylist_options."""
    mode_context: dict = {"last_services": ["Cortar"]}

    booking_node._set_pending_options(mode_context, _STYLIST_LIST_RESPONSE)

    assert "pending_stylist_options" in mode_context
    assert "pending_service_options" not in mode_context
    names = mode_context["pending_stylist_options"]
    assert "Sin preferencia" in names
    # All four stylists + no preferencia
    assert len(names) == 5


# ──────────────────────────────────────────────────────────────────────────────
# (c) Both already set → no-op
# ──────────────────────────────────────────────────────────────────────────────


def test_both_set_is_noop(booking_node) -> None:
    """Spec scenario (c): last_services + last_stylist both set → no pending options."""
    mode_context: dict = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
    }

    booking_node._set_pending_options(mode_context, _SERVICE_LIST_RESPONSE)

    assert "pending_service_options" not in mode_context
    assert "pending_stylist_options" not in mode_context


def test_existing_pending_not_overwritten_when_both_set(booking_node) -> None:
    """If both are set, even existing pending keys are unmodified (function is a no-op)."""
    mode_context: dict = {
        "last_services": ["Cortar"],
        "last_stylist": "Ana",
        "pending_service_options": ["should stay"],
    }

    booking_node._set_pending_options(mode_context, _SERVICE_LIST_RESPONSE)

    # The function returns early; the pre-existing key must still be there.
    assert mode_context["pending_service_options"] == ["should stay"]
