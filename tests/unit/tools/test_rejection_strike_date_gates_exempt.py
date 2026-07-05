"""RED tests — date-validation gates are strike-exempt (qa-loop-conversation-quality C-1).

FINAL-1 batch finding: two consecutive date rejections (customer corrects
"el lunes 13" to "el lunes 6" — a normal disambiguation flow) tripped the
2-strike counter and rewrote the enriched closed_day rejection into
escalation_required, so the dual-fact message (closed day + first_valid_date)
never reached the customer.

closed_day_required and advance_policy_violated are recoverable normal-flow
gates: the customer supplies a new date on the next turn and R26/R27 give the
LLM deterministic recovery instructions. They belong in
_STRIKE_EXEMPT_NEXT_STEPS alongside reoffer_slots.

These tests FAIL until both values are added to the exempt set.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent.tools._rejection_strikes import _STRIKE_EXEMPT_NEXT_STEPS, apply_rejection_strike
from agent.tools.schemas import ToolResponse


def _make_tool_message(tool_name: str, next_step: str, status: str = "rejected") -> MagicMock:
    msg = MagicMock()
    msg.name = tool_name
    msg.content = json.dumps({"status": status, "next_step": next_step})
    return msg


def _date_rejection(next_step: str, payload: dict | None = None) -> ToolResponse:
    return ToolResponse(
        status="rejected",
        next_step=next_step,
        payload=payload or {},
        errors=["El salón está cerrado el lunes 6 de julio."],
    )


@pytest.mark.parametrize("next_step", ["closed_day_required", "advance_policy_violated"])
class TestDateGatesExempt:
    def test_in_exempt_set(self, next_step: str) -> None:
        assert next_step in _STRIKE_EXEMPT_NEXT_STEPS

    def test_two_consecutive_date_rejections_do_not_escalate(self, next_step: str) -> None:
        messages = [_make_tool_message("update_booking", next_step)]
        response = _date_rejection(next_step, payload={"first_valid_date": "2026-07-08"})

        result = apply_rejection_strike(response, messages, "update_booking")

        assert result is response
        assert result.next_step == next_step
        assert result.payload.get("first_valid_date") == "2026-07-08"


def test_mixed_date_corrections_do_not_escalate() -> None:
    """Reproduces the FINAL-1 failure: lunes 13 (closed) -> lunes 6 (closed + enriched)."""
    messages = [
        _make_tool_message("update_booking", "closed_day_required"),
        _make_tool_message("update_booking", "closed_day_required"),
    ]
    response = _date_rejection("closed_day_required", payload={"first_valid_date": "2026-07-08"})

    result = apply_rejection_strike(response, messages, "update_booking")

    assert result.next_step == "closed_day_required"


def test_non_exempt_next_steps_still_escalate() -> None:
    """The strike layer must keep firing for true validator refusals."""
    messages = [_make_tool_message("update_booking", "invalid_service_ids")]
    response = ToolResponse(
        status="rejected",
        next_step="invalid_service_ids",
        payload={},
        errors=["Uno o más service_ids no tienen formato UUID válido."],
    )

    result = apply_rejection_strike(response, messages, "update_booking")

    assert result.next_step == "escalation_required"
