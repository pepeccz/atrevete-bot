"""
RED tests for USE_CAPABILITY_BOOKING feature flag — Phase 1, tasks 1.30–1.35.

Expected fail modes:
  - task 1.30: AttributeError: 'Settings' object has no attribute 'USE_CAPABILITY_BOOKING'
  - tasks 1.31–1.35: ModuleNotFoundError: No module named 'agent.booking.feature_flags'
    or AttributeError from missing flag on Settings.

Do NOT add @pytest.mark.xfail — the failure IS the TDD RED signal.

REQs covered: REQ-30, REQ-31, REQ-32, REQ-33, REQ-34
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# TestFlagDefaults — REQ-30, REQ-34 (task 1.30)
# ---------------------------------------------------------------------------


class TestFlagDefaults:
    """
    Given USE_CAPABILITY_BOOKING is not set in the environment
    When Settings() is instantiated
    Then USE_CAPABILITY_BOOKING defaults to False (REQ-34: safe merge default)
    """

    def test_flag_defaults_to_false_when_not_set(self) -> None:
        """
        Given: no USE_CAPABILITY_BOOKING env var
        When: Settings() is instantiated with env patched to exclude the key
        Then: settings.USE_CAPABILITY_BOOKING is False
        """
        from shared.config import Settings

        with patch.dict("os.environ", {}, clear=False):
            # Remove the key if present
            env_patch = {k: v for k, v in __import__("os").environ.items() if k != "USE_CAPABILITY_BOOKING"}
            with patch("os.environ", env_patch):
                settings = Settings()
                assert settings.USE_CAPABILITY_BOOKING is False, (
                    f"Expected USE_CAPABILITY_BOOKING=False (default), got {settings.USE_CAPABILITY_BOOKING!r}"
                )

    def test_flag_true_when_env_set(self) -> None:
        """
        Given: USE_CAPABILITY_BOOKING=true in environment
        When: Settings() is instantiated
        Then: settings.USE_CAPABILITY_BOOKING is True
        """
        from shared.config import Settings

        with patch.dict("os.environ", {"USE_CAPABILITY_BOOKING": "true"}):
            settings = Settings()
            assert settings.USE_CAPABILITY_BOOKING is True, (
                f"Expected USE_CAPABILITY_BOOKING=True when env set to 'true', "
                f"got {settings.USE_CAPABILITY_BOOKING!r}"
            )

    def test_flag_attribute_exists_on_settings(self) -> None:
        """
        Given: Settings class
        When: USE_CAPABILITY_BOOKING is accessed
        Then: no AttributeError — the field exists on the class
        """
        from shared.config import Settings

        settings = Settings()
        # AttributeError is the expected RED fail mode — once field is added, this passes
        _ = settings.USE_CAPABILITY_BOOKING


# ---------------------------------------------------------------------------
# TestFlagResolver — REQ-31, REQ-32 (tasks 1.31–1.32)
# ---------------------------------------------------------------------------


class TestFlagResolver:
    """
    Tests for resolve_booking_capability_flag:
      - global True path
      - Redis override "on" path
    REQ-31: Per-conversation Redis override.
    """

    def test_global_true(self) -> None:
        """
        Given: settings.USE_CAPABILITY_BOOKING=True AND Redis returns None
        When: resolve_booking_capability_flag("conv_1") is called
        Then: returns (True, "global")
        """
        from agent.booking.feature_flags import resolve_booking_capability_flag

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        with patch("agent.booking.feature_flags.settings") as mock_settings, \
             patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis):
            mock_settings.USE_CAPABILITY_BOOKING = True

            result = resolve_booking_capability_flag("conv_1")
            assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
            use_new_path, source = result
            assert use_new_path is True, f"Expected True, got {use_new_path!r}"
            assert source == "global", f"Expected source='global', got {source!r}"

    def test_global_false_no_override(self) -> None:
        """
        Given: settings.USE_CAPABILITY_BOOKING=False AND Redis returns None (no override)
        When: resolve_booking_capability_flag("conv_1") is called
        Then: returns (False, "global")
        """
        from agent.booking.feature_flags import resolve_booking_capability_flag

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        with patch("agent.booking.feature_flags.settings") as mock_settings, \
             patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis):
            mock_settings.USE_CAPABILITY_BOOKING = False

            result = resolve_booking_capability_flag("conv_1")
            use_new_path, source = result
            assert use_new_path is False, f"Expected False, got {use_new_path!r}"

    def test_redis_override_on(self) -> None:
        """
        Given: settings.USE_CAPABILITY_BOOKING=False
        AND Redis key "booking:capability:conv_42" = "on"
        When: resolve_booking_capability_flag("conv_42") is called
        Then: returns (True, "redis-override")
        """
        from agent.booking.feature_flags import resolve_booking_capability_flag

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value="on")

        with patch("agent.booking.feature_flags.settings") as mock_settings, \
             patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis):
            mock_settings.USE_CAPABILITY_BOOKING = False

            result = resolve_booking_capability_flag("conv_42")
            use_new_path, source = result
            assert use_new_path is True, (
                f"Expected True with Redis override 'on', got {use_new_path!r}"
            )
            assert source == "redis-override", (
                f"Expected source='redis-override', got {source!r}"
            )

    def test_redis_override_on_various_values(self) -> None:
        """
        Given: Redis returns various "on" variants ("1", "true", "yes", "on")
        When: resolve_booking_capability_flag is called
        Then: all return (True, "redis-override")
        """
        from agent.booking.feature_flags import resolve_booking_capability_flag

        on_values = ["1", "on", "true", "yes", "ON", "True"]

        for val in on_values:
            mock_redis = MagicMock()
            mock_redis.get = MagicMock(return_value=val)

            with patch("agent.booking.feature_flags.settings") as mock_settings, \
                 patch("agent.booking.feature_flags.get_redis_client", return_value=mock_redis):
                mock_settings.USE_CAPABILITY_BOOKING = False

                result = resolve_booking_capability_flag("conv_test")
                use_new_path, _ = result
                assert use_new_path is True, (
                    f"Redis value {val!r} should enable override but returned {use_new_path!r}"
                )


# ---------------------------------------------------------------------------
# TestMiddlewareAbsence — REQ-10, REQ-32 (tasks 1.33–1.34)
# ---------------------------------------------------------------------------


class TestMiddlewareAbsence:
    """
    Tests that middleware is NOT in the stack when flag=False,
    and IS in the stack (in the correct order) when flag=True.
    REQ-10: Middleware absent when flag OFF.
    REQ-32: Middleware conditional on effective flag.
    """

    def _capture_middleware_list(
        self,
        use_capability: bool,
    ) -> list:
        """
        Helper: Mock booking_mode to capture the middleware list built when
        _invoke_create_agent is called with a given flag value.
        """
        from agent.modes.booking_mode import BookingModeNode
        from agent.booking.feature_flags import resolve_booking_capability_flag
        from agent.booking.middleware.grounding import BookingGroundingMiddleware
        from agent.booking.middleware.invariants import BookingInvariantMiddleware

        captured = []

        def _fake_create_agent(model, tools, system_prompt, middleware=None, **kwargs):
            captured.extend(middleware or [])
            result = MagicMock()
            result.ainvoke = AsyncMock(return_value=MagicMock(content="ok"))
            return result

        with patch(
            "agent.booking.feature_flags.resolve_booking_capability_flag",
            return_value=(use_capability, "global" if not use_capability else "redis-override"),
        ), patch(
            "agent.modes.booking_mode.create_agent",
            side_effect=_fake_create_agent,
        ):
            node = BookingModeNode.__new__(BookingModeNode)
            node._invoke_create_agent(
                messages=[],
                tools=[],
                tool_choice="auto",
                state={"conversation_id": "conv-test"},
            )

        return captured

    def test_middleware_absent_when_flag_false(self) -> None:
        """
        Given: effective flag = False
        When: BOOKING mode creates the agent
        Then: BookingGroundingMiddleware and BookingInvariantMiddleware are NOT in the list
        """
        from agent.booking.middleware.grounding import BookingGroundingMiddleware
        from agent.booking.middleware.invariants import BookingInvariantMiddleware

        middleware_list = self._capture_middleware_list(use_capability=False)
        class_names = [type(m).__name__ for m in middleware_list]

        assert "BookingGroundingMiddleware" not in class_names, (
            f"BookingGroundingMiddleware should NOT be present when flag=False. "
            f"Middleware: {class_names}"
        )
        assert "BookingInvariantMiddleware" not in class_names, (
            f"BookingInvariantMiddleware should NOT be present when flag=False. "
            f"Middleware: {class_names}"
        )

    def test_middleware_present_flag_true(self) -> None:
        """
        Given: effective flag = True
        When: BOOKING mode creates the agent
        Then: both Grounding and Invariant middlewares ARE in the list
        And: Grounding appears before Invariant
        """
        from agent.booking.middleware.grounding import BookingGroundingMiddleware
        from agent.booking.middleware.invariants import BookingInvariantMiddleware

        middleware_list = self._capture_middleware_list(use_capability=True)
        class_names = [type(m).__name__ for m in middleware_list]

        assert "BookingGroundingMiddleware" in class_names, (
            f"BookingGroundingMiddleware MUST be present when flag=True. "
            f"Middleware: {class_names}"
        )
        assert "BookingInvariantMiddleware" in class_names, (
            f"BookingInvariantMiddleware MUST be present when flag=True. "
            f"Middleware: {class_names}"
        )

        grounding_idx = class_names.index("BookingGroundingMiddleware")
        invariant_idx = class_names.index("BookingInvariantMiddleware")
        assert grounding_idx < invariant_idx, (
            f"BookingGroundingMiddleware must come BEFORE BookingInvariantMiddleware. "
            f"Order: {class_names}"
        )


# ---------------------------------------------------------------------------
# TestOtherModesUnaffected — REQ-33 (task 1.35)
# ---------------------------------------------------------------------------


class TestOtherModesUnaffected:
    """
    Given USE_CAPABILITY_BOOKING=True
    When GREETING or GENERAL mode processes a turn
    Then neither BookingGroundingMiddleware nor BookingInvariantMiddleware appear
    in those modes' middleware lists (REQ-33).
    """

    def _capture_greeting_middleware(self) -> list:
        """Capture middleware list for GREETING mode."""
        captured = []

        def _fake_create_agent(model, tools, system_prompt, middleware=None, **kwargs):
            captured.extend(middleware or [])
            result = MagicMock()
            result.ainvoke = AsyncMock(return_value=MagicMock(content="hola"))
            return result

        with patch("agent.modes.greeting_mode.create_agent", side_effect=_fake_create_agent):
            from agent.modes.greeting_mode import GreetingModeNode
            node = GreetingModeNode.__new__(GreetingModeNode)
            try:
                node._invoke_create_agent(messages=[], tools=[], tool_choice="auto", state={})
            except Exception:
                pass  # May fail for other reasons (missing state) — we only need the capture

        return captured

    def _capture_general_middleware(self) -> list:
        """Capture middleware list for GENERAL mode."""
        captured = []

        def _fake_create_agent(model, tools, system_prompt, middleware=None, **kwargs):
            captured.extend(middleware or [])
            result = MagicMock()
            result.ainvoke = AsyncMock(return_value=MagicMock(content="info"))
            return result

        with patch("agent.modes.general_mode.create_agent", side_effect=_fake_create_agent):
            from agent.modes.general_mode import GeneralModeNode
            node = GeneralModeNode.__new__(GeneralModeNode)
            try:
                node._invoke_create_agent(messages=[], tools=[], tool_choice="auto", state={})
            except Exception:
                pass

        return captured

    def test_greeting_mode_unaffected_by_flag(self) -> None:
        """
        Given: USE_CAPABILITY_BOOKING=True
        When: GREETING mode builds its middleware list
        Then: neither booking middleware appears
        """
        with patch.dict("os.environ", {"USE_CAPABILITY_BOOKING": "true"}):
            middleware_list = self._capture_greeting_middleware()
            class_names = [type(m).__name__ for m in middleware_list]

            assert "BookingGroundingMiddleware" not in class_names, (
                f"BookingGroundingMiddleware must NOT appear in GREETING mode. "
                f"Middleware: {class_names}"
            )
            assert "BookingInvariantMiddleware" not in class_names, (
                f"BookingInvariantMiddleware must NOT appear in GREETING mode. "
                f"Middleware: {class_names}"
            )

    def test_general_mode_unaffected_by_flag(self) -> None:
        """
        Given: USE_CAPABILITY_BOOKING=True
        When: GENERAL mode builds its middleware list
        Then: neither booking middleware appears
        """
        with patch.dict("os.environ", {"USE_CAPABILITY_BOOKING": "true"}):
            middleware_list = self._capture_general_middleware()
            class_names = [type(m).__name__ for m in middleware_list]

            assert "BookingGroundingMiddleware" not in class_names, (
                f"BookingGroundingMiddleware must NOT appear in GENERAL mode. "
                f"Middleware: {class_names}"
            )
            assert "BookingInvariantMiddleware" not in class_names, (
                f"BookingInvariantMiddleware must NOT appear in GENERAL mode. "
                f"Middleware: {class_names}"
            )
