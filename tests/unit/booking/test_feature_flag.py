"""
Tests for booking middleware wiring — Phase 7 (flag removed).

Phase 7: USE_CAPABILITY_BOOKING flag removed. BookingGroundingMiddleware and
BookingInvariantMiddleware are unconditionally active. Tests verify:
  - Middleware stack always contains both grounding and invariant middleware (REQ-32).
  - Grounding appears before invariant (ordering contract).
  - Other modes (GREETING, GENERAL) are NOT affected (REQ-33).

Deleted classes:
  - TestFlagDefaults (flag no longer exists on Settings)
  - TestFlagResolver (resolve_booking_capability_flag removed)
  - TestMiddlewareAbsence (flag=False path removed — middleware always present)

REQs covered: REQ-32, REQ-33
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# TestMiddlewareAlwaysPresent — REQ-32 (replaces TestMiddlewareAbsence)
# ---------------------------------------------------------------------------


class TestMiddlewareAlwaysPresent:
    """
    Verify that BookingGroundingMiddleware and BookingInvariantMiddleware are
    ALWAYS in the middleware stack (no flag conditioning).
    REQ-32: Middleware always active after Phase 7 direct activation.
    """

    def _capture_middleware_list(self) -> list:
        """Capture the middleware list passed to create_agent."""
        from agent.modes.booking_mode import BookingModeNode

        captured = []

        def _fake_create_agent(model, tools, system_prompt, middleware=None, **kwargs):
            captured.extend(middleware or [])
            result = MagicMock()
            result.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
            return result

        import asyncio

        with patch(
            "agent.modes.booking_mode.create_agent",
            side_effect=_fake_create_agent,
        ):
            node = BookingModeNode.__new__(BookingModeNode)
            node.llm = MagicMock()
            node.llm.bind = MagicMock(return_value=MagicMock())
            try:
                asyncio.get_event_loop().run_until_complete(
                    node._invoke_create_agent(
                        messages=[],
                        tools=[],
                        tool_choice="auto",
                        state={"conversation_id": "conv-test"},
                    )
                )
            except Exception:
                pass

        return captured

    def test_grounding_middleware_always_present(self) -> None:
        """
        Given: no feature flag (removed)
        When: BOOKING mode creates the agent
        Then: BookingGroundingMiddleware IS always in the stack (REQ-32)
        """
        middleware_list = self._capture_middleware_list()
        class_names = [type(m).__name__ for m in middleware_list]

        assert "BookingGroundingMiddleware" in class_names, (
            f"BookingGroundingMiddleware MUST always be present (Phase 7 direct activation). "
            f"Middleware: {class_names}"
        )

    def test_invariant_middleware_always_present(self) -> None:
        """
        Given: no feature flag (removed)
        When: BOOKING mode creates the agent
        Then: BookingInvariantMiddleware IS always in the stack (REQ-32)
        """
        middleware_list = self._capture_middleware_list()
        class_names = [type(m).__name__ for m in middleware_list]

        assert "BookingInvariantMiddleware" in class_names, (
            f"BookingInvariantMiddleware MUST always be present (Phase 7 direct activation). "
            f"Middleware: {class_names}"
        )

    def test_grounding_before_invariant(self) -> None:
        """
        Given: Phase 7 unconditional stack
        When: BOOKING mode creates the agent
        Then: BookingGroundingMiddleware appears BEFORE BookingInvariantMiddleware
        """
        middleware_list = self._capture_middleware_list()
        class_names = [type(m).__name__ for m in middleware_list]

        assert "BookingGroundingMiddleware" in class_names, f"Middleware: {class_names}"
        assert "BookingInvariantMiddleware" in class_names, f"Middleware: {class_names}"

        grounding_idx = class_names.index("BookingGroundingMiddleware")
        invariant_idx = class_names.index("BookingInvariantMiddleware")
        assert grounding_idx < invariant_idx, (
            f"BookingGroundingMiddleware must come BEFORE BookingInvariantMiddleware. "
            f"Order: {class_names}"
        )


# ---------------------------------------------------------------------------
# TestOtherModesUnaffected — REQ-33 (unchanged)
# ---------------------------------------------------------------------------


class TestOtherModesUnaffected:
    """
    Given Phase 7 (flag removed, middleware always active)
    Then neither BookingGroundingMiddleware nor BookingInvariantMiddleware are
    imported or referenced in GREETING or GENERAL mode source (REQ-33).
    """

    def _module_source(self, module_path: str) -> str:
        import importlib.util
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Module {module_path} not found"
        assert spec.origin is not None, f"Module {module_path} has no origin"
        with open(spec.origin) as f:
            return f.read()

    def test_greeting_mode_unaffected(self) -> None:
        source = self._module_source("agent.modes.greeting_mode")
        assert "BookingGroundingMiddleware" not in source, (
            "BookingGroundingMiddleware MUST NOT appear in greeting_mode source (REQ-33)"
        )
        assert "BookingInvariantMiddleware" not in source, (
            "BookingInvariantMiddleware MUST NOT appear in greeting_mode source (REQ-33)"
        )

    def test_general_mode_unaffected(self) -> None:
        source = self._module_source("agent.modes.general_mode")
        assert "BookingGroundingMiddleware" not in source, (
            "BookingGroundingMiddleware MUST NOT appear in general_mode source (REQ-33)"
        )
        assert "BookingInvariantMiddleware" not in source, (
            "BookingInvariantMiddleware MUST NOT appear in general_mode source (REQ-33)"
        )
