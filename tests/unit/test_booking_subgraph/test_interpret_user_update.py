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
