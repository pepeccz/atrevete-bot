"""RED tests — service_suggestion_required is strike-exempt (multi-service-resolution PR 1).

Phase 3 tasks: 3.1 (RED), 3.2 (GREEN impl).

The anti-loop strike counter must NOT count consecutive service_suggestion_required
responses toward the escalation threshold. Without this exemption, two suggestion
turns would escalate the conversation to technical_error, which defeats the purpose
of the suggestion fallback (PR 2).

These tests FAIL until "service_suggestion_required" is added to
_STRIKE_EXEMPT_NEXT_STEPS in _rejection_strikes.py (task 3.2).

Refs: spec §anti-loop-escalation, design ADR-3.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from agent.tools.schemas import ToolResponse

# ---------------------------------------------------------------------------
# Helpers — fake message history
# ---------------------------------------------------------------------------


def _make_tool_message(tool_name: str, next_step: str, status: str = "rejected") -> MagicMock:
    """Create a fake LangChain ToolMessage as seen by count_consecutive_rejections."""
    msg = MagicMock()
    msg.name = tool_name
    msg.content = json.dumps({"status": status, "next_step": next_step})
    return msg


def _suggestion_response() -> ToolResponse:
    return ToolResponse(
        status="rejected",
        next_step="service_suggestion_required",
        payload={"unknown_terms": ["pelado"], "candidates": ["Corte de Hombre"]},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuggestionRequiredIsExempt:
    """apply_rejection_strike must pass through service_suggestion_required unchanged."""

    def test_single_suggestion_turn_not_escalated(self):
        """First service_suggestion_required: no prior history → never escalates."""
        from agent.tools._rejection_strikes import apply_rejection_strike

        response = _suggestion_response()
        result = apply_rejection_strike(response, messages=[], tool_name="update_booking")

        assert (
            result.next_step == "service_suggestion_required"
        ), f"Expected service_suggestion_required, got {result.next_step}"
        assert result.status == "rejected"

    def test_two_consecutive_suggestion_turns_do_not_escalate(self):
        """Two consecutive service_suggestion_required → strike count stays 0; no escalation.

        RED: without the exemption, strikes=2 >= threshold=2 → escalation_required fires.
        GREEN: the exemption returns the original response unchanged.
        """
        from agent.tools._rejection_strikes import apply_rejection_strike

        prior_message = _make_tool_message("update_booking", "service_suggestion_required")
        response = _suggestion_response()

        result = apply_rejection_strike(
            response,
            messages=[prior_message],
            tool_name="update_booking",
        )

        assert result.next_step == "service_suggestion_required", (
            f"Expected service_suggestion_required after 2 turns, got {result.next_step!r}. "
            "service_suggestion_required must be added to _STRIKE_EXEMPT_NEXT_STEPS."
        )
        assert (
            result.next_step != "escalation_required"
        ), "escalation_required must NOT fire for consecutive suggestion turns."
        assert result.status == "rejected"

    def test_no_escalation_required_directive_emitted(self):
        """No escalation_required directive with ANY number of suggestion turns."""
        from agent.tools._rejection_strikes import apply_rejection_strike

        # Simulate 3 prior suggestion turns (well above threshold=2)
        prior_messages = [
            _make_tool_message("update_booking", "service_suggestion_required"),
            _make_tool_message("update_booking", "service_suggestion_required"),
            _make_tool_message("update_booking", "service_suggestion_required"),
        ]
        response = _suggestion_response()

        result = apply_rejection_strike(
            response,
            messages=prior_messages,
            tool_name="update_booking",
        )

        assert result.next_step != "escalation_required"
        assert result.next_step == "service_suggestion_required"

    def test_suggestion_exempt_does_not_affect_other_next_steps(self):
        """Adding service_suggestion_required to the exempt set must not exempt other steps.

        Specifically, a plain service_required with 2 consecutive rejections should
        still escalate (regression guard for the original strike counter behavior).
        """
        from agent.tools._rejection_strikes import apply_rejection_strike

        prior_message = _make_tool_message("update_booking", "service_required")
        response = ToolResponse(
            status="rejected",
            next_step="service_required",
        )

        result = apply_rejection_strike(
            response,
            messages=[prior_message],
            tool_name="update_booking",
        )

        # service_required is NOT exempt → should escalate at threshold
        assert (
            result.next_step == "escalation_required"
        ), "service_required must still escalate at threshold (regression guard)."

    def test_service_suggestion_required_in_exempt_set(self):
        """_STRIKE_EXEMPT_NEXT_STEPS must contain 'service_suggestion_required'.

        RED: fails until task 3.2 adds the value.
        """
        from agent.tools._rejection_strikes import _STRIKE_EXEMPT_NEXT_STEPS

        assert "service_suggestion_required" in _STRIKE_EXEMPT_NEXT_STEPS, (
            "'service_suggestion_required' must be added to _STRIKE_EXEMPT_NEXT_STEPS "
            "in _rejection_strikes.py."
        )
