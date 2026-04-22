"""Tests for agent/booking/prompt_builder.py — Task 2.1 (booking-prompts-audit-fix).

Spec:
- build_leaf_system_message(step, booking, state) -> SystemMessage
- Content MUST include: "Maite" (persona), catalog section, hours, booking snapshot,
  audience taxonomy block (señora, caballero, niño, bebé), step-specific instruction.
- When catalog is empty/unavailable: returns SystemMessage with other sections, logs WARNING.
- When booking is None (first turn): snapshot block is omitted.
- Different steps produce different instructions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import SystemMessage


@pytest.mark.asyncio
async def test_contains_persona():
    """SystemMessage content must contain 'Maite' (persona identifier)."""
    from agent.booking.prompt_builder import build_leaf_system_message

    booking = {"step": "service", "service_ids": []}
    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value="Corte de cabello — 30min"),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "09:00-18:00"}),
        ),
    ):
        msg = await build_leaf_system_message("ask_service", booking, state)

    assert isinstance(msg, SystemMessage)
    assert "Maite" in msg.content


@pytest.mark.asyncio
async def test_contains_catalog():
    """SystemMessage must include the catalog section when catalog is available."""
    from agent.booking.prompt_builder import build_leaf_system_message

    booking = {"step": "service"}
    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value="Corte de cabello — 30min"),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        msg = await build_leaf_system_message("ask_service", booking, state)

    assert "Corte de cabello" in msg.content


@pytest.mark.asyncio
async def test_contains_hours():
    """SystemMessage must include business hours when available."""
    from agent.booking.prompt_builder import build_leaf_system_message

    booking = {"step": "service"}
    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "09:00-18:00", "domingo": "cerrado"}),
        ),
    ):
        msg = await build_leaf_system_message("ask_service", booking, state)

    assert "09:00-18:00" in msg.content


@pytest.mark.asyncio
async def test_contains_booking_snapshot():
    """SystemMessage must include booking snapshot when booking is non-empty."""
    from agent.booking.prompt_builder import build_leaf_system_message

    booking = {"step": "audience", "service_ids": ["abc-123"], "audience": None}
    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        msg = await build_leaf_system_message("ask_audience", booking, state)

    # The booking snapshot must reference the current step
    assert "audience" in msg.content


@pytest.mark.asyncio
async def test_contains_audience_taxonomy_all_4_terms():
    """SystemMessage must include señora, caballero, niño, bebé in the taxonomy block."""
    from agent.booking.prompt_builder import build_leaf_system_message

    booking = {"step": "audience"}
    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        msg = await build_leaf_system_message("ask_audience", booking, state)

    content = msg.content
    assert "señora" in content
    assert "caballero" in content
    assert "niño" in content or "nino" in content.lower()
    assert "bebé" in content or "bebe" in content.lower()


@pytest.mark.asyncio
async def test_step_instruction_differs_per_step():
    """Each step must produce a different extraction instruction."""
    from agent.booking.prompt_builder import build_leaf_system_message

    state = {"messages": []}
    booking_service = {"step": "service"}
    booking_audience = {"step": "audience"}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
    ):
        msg_service = await build_leaf_system_message("ask_service", booking_service, state)
        msg_audience = await build_leaf_system_message("ask_audience", booking_audience, state)

    assert msg_service.content != msg_audience.content


@pytest.mark.asyncio
async def test_degrades_gracefully_when_catalog_empty(caplog):
    """When catalog is empty, must return SystemMessage with other sections and log WARNING."""
    import logging

    from agent.booking.prompt_builder import build_leaf_system_message

    booking = {"step": "service"}
    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={}),
        ),
        caplog.at_level(logging.WARNING, logger="agent.booking.prompt_builder"),
    ):
        msg = await build_leaf_system_message("ask_service", booking, state)

    # Must still return a valid SystemMessage (no exception raised)
    assert isinstance(msg, SystemMessage)
    assert "Maite" in msg.content
    # Must have logged a warning about empty catalog
    assert any("catalog" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_booking_none_omits_snapshot():
    """When booking is None, the snapshot block must be absent but other sections present."""
    from agent.booking.prompt_builder import build_leaf_system_message

    state = {"messages": []}

    with (
        patch(
            "agent.booking.prompt_builder.build_catalog_prompt_section",
            new=AsyncMock(return_value="Corte de cabello — 30min"),
        ),
        patch(
            "agent.booking.prompt_builder.load_business_hours_snapshot",
            new=AsyncMock(return_value={"lunes": "09:00-18:00"}),
        ),
    ):
        msg = await build_leaf_system_message("ask_service", None, state)

    assert isinstance(msg, SystemMessage)
    assert "Maite" in msg.content
    # booking snapshot section must not appear
    assert "RESERVA ACTUAL" not in msg.content
