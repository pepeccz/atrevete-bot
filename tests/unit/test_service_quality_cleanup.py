from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.modes.greeting_mode import GreetingMode
from agent.prompts.loader import build_step_context
from agent.tools.info_tools import query_info


def test_build_step_context_excludes_all_customer_names() -> None:
    """Customer name must NEVER appear in prompt context (customer-name-handling refactor)."""
    state = {
        "customer_name": "Pepe",
        "customer_first_name": "Pepe",
        "pending_whatsapp_name": "Pepe",
    }

    context = build_step_context(state, {})

    assert "Nombre del cliente" not in context
    assert "Pepe" not in context


@pytest.mark.asyncio
async def test_query_info_services_includes_description() -> None:
    fake_service = SimpleNamespace(
        name="Corte",
        duration_minutes=45,
        category=SimpleNamespace(value="HAIRDRESSING"),
        description="Corte con asesoramiento.",
    )
    fake_session = AsyncMock()
    fake_session.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [fake_service])
    )
    fake_context_manager = AsyncMock()
    fake_context_manager.__aenter__.return_value = fake_session
    fake_context_manager.__aexit__.return_value = None

    with patch("agent.tools.info_tools.get_async_session", return_value=fake_context_manager):
        result = await query_info.ainvoke({"type": "services"})

    assert result["services"] == [
        {
            "name": "Corte",
            "duration_minutes": 45,
            "category": "HAIRDRESSING",
            "description": "Corte con asesoramiento.",
        }
    ]


def test_greeting_mode_dead_methods_removed() -> None:
    assert not hasattr(GreetingMode, "_get_post_name_transition")
    assert not hasattr(GreetingMode, "_sync_pending_booking_intent")
