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


class TestGeneralModeNoEscalateTool:
    """GeneralMode.get_tools() no longer includes escalate_to_human (removed in escalation-lifecycle-completion)."""

    def test_no_escalate_to_human_in_tools(self):
        """GeneralMode.get_tools() returns empty list — escalation is router-driven."""
        mode = GeneralMode(tools=[], llm_client=_make_mock_llm())
        tools = mode.get_tools()
        tool_names = [t.name for t in tools]
        assert "escalate_to_human" not in tool_names
        assert tools == []


# (test_general_mode_persists_booking_handoff_from_search_services removed —
# search_services tool no longer exists; catalog is in-prompt via catalog_builder.py)
