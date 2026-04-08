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


# (search_services-based _extract_booking_handoff tests removed — tool was deleted
# in catalog-in-prompt architecture. See design: AD-3 / Domain E.)


# =============================================================================
# T-38: Architecture guard — no search_services or query_info in GeneralMode
# =============================================================================


class TestGeneralModeNoDataTools:
    """T-38: GeneralMode must NOT reference search_services or query_info tools."""

    def test_no_search_services_in_general_mode(self):
        """search_services must not appear in general_mode source (tool removed)."""
        import inspect
        from agent.modes import general_mode as _gm

        src = inspect.getsource(_gm)
        assert "search_services" not in src, (
            "search_services found in general_mode source — this tool was removed from GENERAL mode"
        )

    def test_no_query_info_in_general_mode(self):
        """query_info must not appear in general_mode source (tool removed)."""
        import inspect
        from agent.modes import general_mode as _gm

        src = inspect.getsource(_gm)
        assert "query_info" not in src, (
            "query_info found in general_mode source — this tool was removed from GENERAL mode"
        )


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


# (test_general_mode_persists_booking_handoff_from_search_services removed —
# search_services tool no longer exists; catalog is in-prompt via catalog_builder.py)
