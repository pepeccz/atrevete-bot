from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.general_mode import GeneralMode
from agent.state.schemas import create_initial_state


def _make_mock_llm(response_text: str = "Te recomiendo Corte Caballero") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


@pytest.mark.asyncio
async def test_general_mode_persists_booking_handoff_from_search_services() -> None:
    state = create_initial_state("conv-general-handoff", "+34610000001")
    state["current_mode"] = "GENERAL"
    state["customer_name"] = "Luis"
    state["messages"] = [{"role": "user", "content": "qué me recomendás para caballero"}]
    state["mode_context"] = {"last_intent": "ask_info", "last_intent_confidence": 0.9}

    mode = GeneralMode(tools=[], llm_client=_make_mock_llm())

    with (
        patch.object(mode, "_use_optimized_prompts", return_value=False),
        patch.object(mode, "_run_agentic_loop", new_callable=AsyncMock) as mock_loop,
    ):
        mock_loop.return_value = AgenticLoopResult(
            response_text="Te recomiendo Corte Caballero.",
            tool_results={
                "search_services": {
                    "resolved_service": {
                        "id": "svc-caballero",
                        "name": "Corte Caballero",
                        "category": "Peluquería",
                        "duration_minutes": 30,
                        "family": "haircut",
                    }
                }
            },
            tool_events=[],
        )

        result = await mode.handle(state, intent=None)

    handoff = result["mode_context"]["general_booking_handoff"]
    assert handoff["resolved_service"]["id"] == "svc-caballero"
    assert handoff["resolved_service"]["name"] == "Corte Caballero"
