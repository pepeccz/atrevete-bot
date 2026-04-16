"""Architecture guards for agent/modes/general_mode.py (M4 create_agent migration)."""

from __future__ import annotations

import inspect

from agent.modes import general_mode as _gm


# =============================================================================
# T-38: GeneralMode must NOT reference search_services or query_info tools.
# =============================================================================


class TestGeneralModeNoDataTools:
    def test_no_search_services_in_general_mode(self):
        src = inspect.getsource(_gm)
        assert "search_services" not in src, (
            "search_services found in general_mode source — this tool was removed from GENERAL mode"
        )

    def test_no_query_info_in_general_mode(self):
        src = inspect.getsource(_gm)
        assert "query_info" not in src, (
            "query_info found in general_mode source — this tool was removed from GENERAL mode"
        )


# =============================================================================
# Escalation tool must NOT be bound in GeneralMode (router-driven handoff).
# =============================================================================


class TestGeneralModeNoEscalateTool:
    def test_no_escalate_to_human_in_source(self):
        """GeneralMode binds NO tools — escalation is driven by the router."""
        src = inspect.getsource(_gm)
        assert "escalate_to_human" not in src, (
            "escalate_to_human found in general_mode — escalation must be router-driven"
        )

    def test_create_agent_call_passes_empty_tools(self):
        """The create_agent invocation must pass tools=[] — guards against regressions."""
        src = inspect.getsource(_gm)
        assert "tools=[]" in src, "GeneralMode must call create_agent with tools=[]"


# =============================================================================
# Public factory surface
# =============================================================================


class TestGeneralModePublicAPI:
    def test_build_general_node_is_exported(self):
        assert hasattr(_gm, "build_general_node")
        assert callable(_gm.build_general_node)

    def test_build_general_node_returns_callable(self):
        node = _gm.build_general_node(llm_factory=None)
        assert callable(node)
