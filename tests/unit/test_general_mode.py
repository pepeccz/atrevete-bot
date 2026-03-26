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


# =============================================================================
# T-11: _extract_booking_handoff shape normalization (F-1 + F-3)
# =============================================================================


class TestExtractBookingHandoffShape:
    """T-11: _extract_booking_handoff handles dict and list envelopes."""

    def _mode(self) -> GeneralMode:
        return GeneralMode(tools=[], llm_client=_make_mock_llm())

    def test_dict_shape_still_works(self):
        """_extract_booking_handoff with dict envelope returns correctly (legacy shape)."""
        mode = self._mode()
        tool_results = {
            "search_services": {
                "resolved_service": {
                    "id": "svc-001",
                    "name": "Corte de Dama",
                }
            }
        }
        result = mode._extract_booking_handoff(tool_results)
        assert result is not None
        assert result["resolved_service"]["id"] == "svc-001"

    def test_list_shape_normalized(self):
        """_extract_booking_handoff with list envelope takes the last item."""
        mode = self._mode()
        tool_results = {
            "search_services": [
                # First call — old result
                {"resolved_service": {"id": "svc-old", "name": "Old Service"}},
                # Second call — most recent, should be taken
                {"resolved_service": {"id": "svc-new", "name": "Corte de Dama"}},
            ]
        }
        result = mode._extract_booking_handoff(tool_results)
        assert result is not None
        assert result["resolved_service"]["id"] == "svc-new"

    def test_empty_list_returns_none(self):
        """_extract_booking_handoff with [] (empty list) returns None."""
        mode = self._mode()
        tool_results = {"search_services": []}
        result = mode._extract_booking_handoff(tool_results)
        assert result is None

    def test_none_returns_none(self):
        """_extract_booking_handoff with missing key returns None."""
        mode = self._mode()
        tool_results = {}  # no 'search_services' key
        result = mode._extract_booking_handoff(tool_results)
        assert result is None

    def test_list_with_clarification_needed(self):
        """List envelope with clarification_needed is normalized correctly."""
        mode = self._mode()
        tool_results = {
            "search_services": [
                {
                    "clarification_needed": {
                        "axis": "audience",
                        "question_hint": "¿Para quién?",
                        "options": [{"value": "adult_female", "label": "Dama"}],
                    }
                }
            ]
        }
        result = mode._extract_booking_handoff(tool_results)
        assert result is not None
        assert "pending_clarifications" in result
        assert result["pending_clarifications"][0]["axis"] == "audience"

    def test_list_with_services_shape(self):
        """List envelope with services list is normalized correctly."""
        mode = self._mode()
        tool_results = {
            "search_services": [
                {
                    "services": [
                        {"id": "svc-001", "name": "Corte de Dama"},
                        {"id": "svc-002", "name": "Tinte Raíz"},
                    ]
                }
            ]
        }
        result = mode._extract_booking_handoff(tool_results)
        assert result is not None
        assert "candidate_services" in result
        assert len(result["candidate_services"]) == 2


class TestGeneralModeEscalateTool:
    """T-11: GeneralMode.get_tools() includes escalate_to_human."""

    def test_escalate_to_human_in_tools(self):
        """GeneralMode.handle() runs the loop with escalate_to_human in tools."""
        # We test this by verifying that GeneralMode always passes escalate_to_human
        # to _run_agentic_loop. We capture the tools argument via a mock.
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        mode = GeneralMode(tools=[], llm_client=_make_mock_llm())
        state = create_initial_state("conv-esc", "+34610000001")
        state["current_mode"] = "GENERAL"
        state["messages"] = [{"role": "user", "content": "necesito ayuda"}]
        state["mode_context"] = {}

        captured_tools = []

        async def _capture_loop(messages, tools=None):
            captured_tools.extend(tools or [])
            return AgenticLoopResult(
                response_text="Te paso con alguien.",
                tool_results={},
                tool_events=[],
            )

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=False),
            patch.object(mode, "_run_agentic_loop", side_effect=_capture_loop),
        ):
            asyncio.get_event_loop().run_until_complete(mode.handle(state, intent=None))

        tool_names = [t.name for t in captured_tools]
        assert "escalate_to_human" in tool_names


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
