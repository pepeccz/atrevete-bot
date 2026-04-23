"""Tests for agent.routing.intent_types — ensures enum covers all values used by services."""

from __future__ import annotations

import pytest


def test_intent_type_enum_importable():
    from agent.routing.intent_types import IntentType  # noqa: F401


def test_intent_type_has_all_required_values():
    from agent.routing.intent_types import IntentType

    required = {
        "CONFIRM_APPOINTMENT",
        "DECLINE_APPOINTMENT",
        "CONFIRM_DECLINE",
        "ABORT_DECLINE",
        "INITIATE_CANCELLATION",
        "SELECT_CANCELLATION",
        "CONFIRM_CANCELLATION",
        "ABORT_CANCELLATION",
        "INSIST_CANCELLATION",
    }
    actual = {member.name for member in IntentType}
    missing = required - actual
    assert not missing, f"IntentType missing members: {missing}"


def test_intent_type_is_str_enum():
    from agent.routing.intent_types import IntentType

    # str mixin allows value comparison without `.value`
    assert IntentType.CONFIRM_APPOINTMENT == "CONFIRM_APPOINTMENT"
    assert IntentType.DECLINE_APPOINTMENT.value == "DECLINE_APPOINTMENT"


def test_confirmation_service_imports_without_error():
    # Import should succeed now that IntentType exists
    import importlib

    module = importlib.import_module("agent.services.confirmation_service")
    assert module is not None


def test_cancellation_service_imports_without_error():
    import importlib

    module = importlib.import_module("agent.services.cancellation_service")
    assert module is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
