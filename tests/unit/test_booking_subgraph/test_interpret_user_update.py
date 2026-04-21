"""
Phase 7 prep — test interpret_user_update integration with resolver registry.
Also tests CHANGE_DATE routing.
"""

from __future__ import annotations

import pytest


def _state(message: str, bc: dict | None = None) -> dict:
    return {"user_message": message, "booking_context": bc or {}}


@pytest.mark.asyncio
async def test_interpret_returns_patch_and_user_action():
    from agent.booking.nodes.interpret_user_update import interpret_user_update

    state = _state("señora")
    result = await interpret_user_update(state)
    assert "booking_context_patch" in result
    assert "user_action" in result


@pytest.mark.asyncio
async def test_interpret_audience_resolver_fires():
    from agent.booking.nodes.interpret_user_update import interpret_user_update

    state = _state("señora")
    result = await interpret_user_update(state)
    patch = result["booking_context_patch"]["patch"]
    assert patch.get("service_audience_hint") == "FEMALE"


@pytest.mark.asyncio
async def test_interpret_unknown_text_gives_unknown_action():
    from agent.booking.nodes.interpret_user_update import interpret_user_update

    state = _state("hola")
    result = await interpret_user_update(state)
    assert result["user_action"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_interpret_falls_back_to_last_user_message_when_user_message_cleared():
    """BUG-AUDIENCE: preprocess clears user_message=None after persisting it to
    messages. interpret_user_update must fall back to the last user message in
    state["messages"] so resolvers keep firing on every booking turn.
    """
    from agent.booking.nodes.interpret_user_update import interpret_user_update

    state = {
        "user_message": None,
        "booking_context": {},
        "messages": [
            {"role": "assistant", "content": "¿Es para ti? ¿Señora, caballero o niño/a?"},
            {"role": "user", "content": "señora"},
        ],
    }
    result = await interpret_user_update(state)
    assert result["booking_context_patch"]["patch"].get("service_audience_hint") == "FEMALE"
    assert result["user_action"] == "PROVIDE_FIELD"
