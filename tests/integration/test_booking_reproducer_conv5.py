"""Focused reproducer: conv_id=5 availability fetch bug.

R2 — The exact schema mismatch (date vs date_iso, missing audience) from the
2026-04-22 production crash must be provably fixed by this test.

These tests drive fetch_availability_node directly with a realistic ConversationState
fixture — no full graph needed.  All external I/O (DB, GCal, OpenRouter) is patched.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conv5_state(stylist_id: str, service_id: str) -> dict:
    """ConversationState fixture representing post-step-5 state from conv_id=5.

    booking.date = "2026-04-29" (Wednesday "el miércoles que viene") — this is the
    key that fetch_availability_node reads; the fix renames it to date_iso when building
    the tool args dict.
    """
    return {
        "booking": {
            "step": "slot",
            "service_ids": [service_id],
            "audience": "adult_female",
            "stylist_id": stylist_id,
            "date": "2026-04-29",
            "offered_slots": None,
            "selected_slot": None,
            "customer_full_name": None,
            "notes": None,
        },
        "messages": [],
        "conversation_id": "conv-5-reproducer",
        "customer_phone": "+5491155555555",
        "current_mode": "BOOKING",
        "pending_whatsapp_name": None,
        "customer_id": None,
        "customer_name": None,
        "user_message": "",
    }


# ---------------------------------------------------------------------------
# R2 — fetch_availability_node does not produce apology when schema is correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conv5_fetch_availability_does_not_produce_apology():
    """fetch_availability_node must NOT return a technical apology message.

    Pre-fix: ValidationError (KeyError 'date_iso') → exception branch → apology.
    Post-fix: correct args dict → tool returns ok/partial → advance to slot step.
    """
    from agent.booking.actions import fetch_availability_node
    from agent.tools.schemas import ToolResponse

    service_id = str(uuid4())
    stylist_id = str(uuid4())
    state = _make_conv5_state(stylist_id=stylist_id, service_id=service_id)

    ok_response = ToolResponse(
        status="ok",
        payload={
            "slots": [{"start_iso": "2026-04-29T10:00:00-03:00"}],
            "total_duration_minutes": 30,
        },
    )

    mock_tool = AsyncMock(return_value=ok_response.model_dump_json())

    with patch("agent.booking.actions.check_availability_tool", mock_tool):
        result = await fetch_availability_node(state)

    # Collect all message content strings from the returned Command
    messages = result.update.get("messages", [])
    apology_patterns = [
        "Lo siento, tuve un problema técnico",
        "Lo siento, no pude consultar disponibilidad",
        "Lo siento",
    ]
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else str(msg)
        for pattern in apology_patterns:
            assert pattern not in content, (
                f"fetch_availability_node returned apology: {content!r}\n"
                "This means the tool invocation failed — likely a schema mismatch."
            )

    # Also assert it advanced correctly (not returning to date step)
    returned_booking = result.update.get("booking", {})
    assert returned_booking.get("step") == "slot", (
        f"Expected step='slot', got '{returned_booking.get('step')}'. "
        "Node may have hit the error path."
    )


# ---------------------------------------------------------------------------
# R2 — date_iso format in captured args dict is valid YYYY-MM-DD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conv5_date_iso_format_is_valid():
    """The args dict passed to check_availability_tool must have 'date_iso' in YYYY-MM-DD format.

    Pre-fix: key was 'date', causing schema ValidationError.
    Post-fix: key is 'date_iso' with value '2026-04-29'.
    """
    import agent.booking.actions as actions_module
    from agent.tools.schemas import ToolResponse

    service_id = str(uuid4())
    stylist_id = str(uuid4())
    state = _make_conv5_state(stylist_id=stylist_id, service_id=service_id)

    captured: dict = {}

    async def _capture(args: dict) -> str:
        captured.update(args)
        ok = ToolResponse(
            status="ok",
            payload={"slots": [], "total_duration_minutes": 30},
        )
        return ok.model_dump_json()

    original = actions_module.check_availability_tool
    actions_module.check_availability_tool = _capture
    try:
        await actions_module.fetch_availability_node(state)
    finally:
        actions_module.check_availability_tool = original

    assert "date_iso" in captured, (
        f"args dict must have key 'date_iso'. Got keys: {list(captured.keys())}\n"
        "Pre-fix the node was sending 'date' which caused ValidationError."
    )
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}$", captured["date_iso"]
    ), f"date_iso must match YYYY-MM-DD, got: {captured['date_iso']!r}"
