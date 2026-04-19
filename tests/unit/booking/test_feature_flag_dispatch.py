"""
Tests for BookingModeNode._build_middleware_stack() feature flag dispatch.

TDD RED: Tests reference _build_middleware_stack() which does NOT exist yet on BookingModeNode.
Design refs: design §7, §5, §6 Q6
Requirements: R28, R29
Scenarios: S25, S26

Acceptance:
- Flag OFF → legacy middleware stack (no BookingGroundingMiddleware, no BookingInvariantMiddleware)
- Flag ON → new stack in correct order: [BookingGroundingMiddleware, DynamicTools, BookingInvariantMiddleware]
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.booking.middleware.grounding import BookingGroundingMiddleware
from agent.booking.middleware.invariants import BookingInvariantMiddleware
from agent.middleware.dynamic_tools import DynamicToolsMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node() -> "BookingModeNode":
    """Create a BookingModeNode with minimal mocks needed to call _build_middleware_stack."""
    from agent.modes.booking_mode import BookingModeNode

    node = BookingModeNode.__new__(BookingModeNode)
    # Minimal attributes that middleware constructors or the method may need
    node._booking_context = {}
    node._current_state = {}
    node._cached_service_names = []
    # Mock the LLM so no real model is loaded
    node.llm = MagicMock()
    return node


# ---------------------------------------------------------------------------
# T4.2 — Flag OFF: legacy stack
# ---------------------------------------------------------------------------


class TestFlagOff:
    """When USE_CAPABILITY_BOOKING=False, the stack must NOT contain new middleware."""

    def test_flag_off_excludes_grounding_middleware(self, monkeypatch):
        """BookingGroundingMiddleware must be absent from the legacy stack."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        # Invalidate lru_cache so the env var is picked up
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert BookingGroundingMiddleware not in types_in_stack, (
            "BookingGroundingMiddleware must NOT be in the legacy stack when flag=False, "
            f"but got: {types_in_stack}"
        )

    def test_flag_off_excludes_invariant_middleware(self, monkeypatch):
        """BookingInvariantMiddleware must be absent from the legacy stack."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert BookingInvariantMiddleware not in types_in_stack, (
            "BookingInvariantMiddleware must NOT be in the legacy stack when flag=False, "
            f"but got: {types_in_stack}"
        )

    def test_flag_off_includes_dynamic_tools(self, monkeypatch):
        """DynamicToolsMiddleware must be present in both legacy and new stacks."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "false")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert DynamicToolsMiddleware in types_in_stack, (
            "DynamicToolsMiddleware must be present in the legacy stack, "
            f"but got: {types_in_stack}"
        )

    def test_flag_default_is_legacy_path(self, monkeypatch):
        """Default (no env var) must use the legacy stack."""
        monkeypatch.delenv("USE_CAPABILITY_BOOKING", raising=False)
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert BookingGroundingMiddleware not in types_in_stack, (
            "Default stack (flag not set) must be the legacy path"
        )


# ---------------------------------------------------------------------------
# T4.2 — Flag ON: new capability stack
# ---------------------------------------------------------------------------


class TestFlagOn:
    """When USE_CAPABILITY_BOOKING=True, the stack must contain new middleware in design order."""

    def test_flag_on_includes_grounding_middleware(self, monkeypatch):
        """BookingGroundingMiddleware must be present in the new stack."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert BookingGroundingMiddleware in types_in_stack, (
            "BookingGroundingMiddleware must be in the new stack when flag=True, "
            f"but got: {types_in_stack}"
        )

    def test_flag_on_includes_invariant_middleware(self, monkeypatch):
        """BookingInvariantMiddleware must be present in the new stack."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert BookingInvariantMiddleware in types_in_stack, (
            "BookingInvariantMiddleware must be in the new stack when flag=True, "
            f"but got: {types_in_stack}"
        )

    def test_flag_on_includes_dynamic_tools(self, monkeypatch):
        """DynamicToolsMiddleware must be present in the new stack."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        assert DynamicToolsMiddleware in types_in_stack, (
            "DynamicToolsMiddleware must be present in the new capability stack, "
            f"but got: {types_in_stack}"
        )

    def test_flag_on_grounding_before_dynamic_tools(self, monkeypatch):
        """Design §5 + §6 Q6: BookingGroundingMiddleware must precede DynamicToolsMiddleware."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        grounding_idx = next(
            (i for i, t in enumerate(types_in_stack) if t is BookingGroundingMiddleware), None
        )
        dynamic_idx = next(
            (i for i, t in enumerate(types_in_stack) if t is DynamicToolsMiddleware), None
        )
        assert grounding_idx is not None, "BookingGroundingMiddleware not found in stack"
        assert dynamic_idx is not None, "DynamicToolsMiddleware not found in stack"
        assert grounding_idx < dynamic_idx, (
            f"BookingGroundingMiddleware (idx={grounding_idx}) must come BEFORE "
            f"DynamicToolsMiddleware (idx={dynamic_idx}) per design §5"
        )

    def test_flag_on_dynamic_tools_before_invariant(self, monkeypatch):
        """Design §5 + §6 Q6: DynamicToolsMiddleware must precede BookingInvariantMiddleware."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]
        dynamic_idx = next(
            (i for i, t in enumerate(types_in_stack) if t is DynamicToolsMiddleware), None
        )
        invariant_idx = next(
            (i for i, t in enumerate(types_in_stack) if t is BookingInvariantMiddleware), None
        )
        assert dynamic_idx is not None, "DynamicToolsMiddleware not found in stack"
        assert invariant_idx is not None, "BookingInvariantMiddleware not found in stack"
        assert dynamic_idx < invariant_idx, (
            f"DynamicToolsMiddleware (idx={dynamic_idx}) must come BEFORE "
            f"BookingInvariantMiddleware (idx={invariant_idx}) per design §5"
        )

    def test_flag_on_full_ordering_ground_dynamic_invariant(self, monkeypatch):
        """Design §6 Q6 full ordering: Grounding → DynamicTools → Invariants (→ Model)."""
        monkeypatch.setenv("USE_CAPABILITY_BOOKING", "true")
        from shared.config import get_settings
        get_settings.cache_clear()

        node = _make_node()
        stack = node._build_middleware_stack()

        types_in_stack = [type(m) for m in stack]

        def idx(cls):
            return next(
                (i for i, t in enumerate(types_in_stack) if t is cls), None
            )

        g = idx(BookingGroundingMiddleware)
        d = idx(DynamicToolsMiddleware)
        v = idx(BookingInvariantMiddleware)

        assert g is not None, "BookingGroundingMiddleware missing"
        assert d is not None, "DynamicToolsMiddleware missing"
        assert v is not None, "BookingInvariantMiddleware missing"
        assert g < d < v, (
            f"Expected order Ground({g}) < DynamicTools({d}) < Invariants({v}) "
            f"per design §6 Q6, but got: {types_in_stack}"
        )
