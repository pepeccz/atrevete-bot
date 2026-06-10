"""TDD tests: B1 IDOR fix — manage_appointments tool must read customer_phone from InjectedState.

T4 (RED): Write failing tests that confirm:
  - manage_appointments reads customer_phone from state, not LLM arg
  - manage_appointments rejects when state['customer_phone'] is missing
"""

from __future__ import annotations

import pytest

STATE_PHONE = "+34611000010"


@pytest.mark.asyncio
async def test_manage_ignores_llm_supplied_customer_phone():
    """B1: manage_appointments reads customer_phone from InjectedState, not from LLM arg.

    When state['customer_phone'] = STATE_PHONE and action='list',
    the tool must forward STATE_PHONE to _list_appointments.
    """
    from unittest.mock import patch

    captured = {}

    async def fake_list(customer_phone: str, limit: int = 5):
        captured["phone"] = customer_phone
        return {
            "success": True,
            "appointments": [],
            "count": 0,
            "message": "No tienes citas.",
        }

    with patch(
        "agent.tools.manage_appointments_tool._list_appointments",
        side_effect=fake_list,
    ):
        from agent.tools.manage_appointments_tool import manage_appointments

        result = await manage_appointments.coroutine(
            action="list",
            state={"customer_phone": STATE_PHONE},
        )

    assert captured.get("phone") == STATE_PHONE, (
        f"Expected state phone {STATE_PHONE} forwarded to _list_appointments, "
        f"got: {captured.get('phone')}"
    )


@pytest.mark.asyncio
async def test_manage_rejects_when_state_customer_phone_missing():
    """B1: manage_appointments rejects when state has no customer_phone."""
    from agent.tools.manage_appointments_tool import manage_appointments

    result = await manage_appointments.coroutine(
        action="list",
        state={},  # no customer_phone
    )

    # Should return a string with rejection message, not raise
    assert isinstance(result, str)
    assert len(result) > 0
    # The tool must reject, not proceed with an empty phone
    assert "incompleto" in result.lower() or "rejected" in result.lower() or "error" in result.lower(), (
        f"Expected rejection response for missing state phone, got: {result!r}"
    )
