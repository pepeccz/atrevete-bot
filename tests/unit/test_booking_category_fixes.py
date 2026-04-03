"""
Unit tests for booking-mode category-filtering bug fixes.

Covers fixes from the stylist-category-filtering-fix change:

Phase 3 — _pre_tool_call: category injection into list_stylists
  REQ-3: _pre_tool_call does NOT overwrite category when already provided by LLM
  REQ-3: _pre_tool_call passes through when service_category is None
  REQ-3: _pre_tool_call passes through when no ctx

Phase 5 — conversation_flow context handoff:
  REQ-5: _service_to_booking_context returns None (not '') for absent/empty category

Tests for REQ-2 (_maybe_prefetch_stylists), REQ-8 (_detect_tool_skips / Condition B),
and REQ-3 category injection were removed in booking-mode-simplification Phase 4 —
these functions and fields no longer exist in the simplified BookingMode/BookingContext.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import BookingMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_llm() -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "¿Qué servicio deseas?"
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode() -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm())


# ---------------------------------------------------------------------------
# REQ-3: _pre_tool_call — category injection into list_stylists args
# (only the passthrough / no-overwrite cases that still apply)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPreToolCallCategoryInjection:
    """REQ-3: _pre_tool_call category injection for list_stylists."""

    async def test_does_not_overwrite_category_when_already_present(self):
        """When LLM already provided category, _pre_tool_call must not overwrite it."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            service_category="HAIRDRESSING",
        )
        tool_args = {"category": "AESTHETICS"}  # LLM explicitly provided different category

        result = await mode._pre_tool_call("list_stylists", tool_args)

        # Must preserve what the LLM provided — no overwrite
        assert result.get("category") == "AESTHETICS"

    async def test_no_injection_when_service_category_is_none(self):
        """When ctx.service_category is None, do not inject (log warning, allow call)."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            service_category=None,
        )
        tool_args = {}

        result = await mode._pre_tool_call("list_stylists", tool_args)

        # category should not be injected (not present or None)
        assert "category" not in result or result.get("category") is None

    async def test_no_injection_when_no_ctx(self):
        """When _ctx is None (edge case), list_stylists args pass through unchanged."""
        mode = make_booking_mode()
        mode._ctx = None
        tool_args = {}

        result = await mode._pre_tool_call("list_stylists", tool_args)

        assert result == {}

    async def test_other_tools_not_affected(self):
        """Non-list_stylists tools are unaffected by the category injection guard."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(service_category="HAIRDRESSING")
        tool_args = {"query": "horarios apertura"}

        result = await mode._pre_tool_call("query_info", tool_args)

        # query_info args must be unchanged — no category injected
        assert "category" not in result
        assert result["query"] == "horarios apertura"


# ---------------------------------------------------------------------------
# REQ-5: _service_to_booking_context — None not empty string on handoff
# ---------------------------------------------------------------------------


class TestServiceToBookingContextNoneCategory:
    """REQ-5: conversation_flow must propagate None, not '' for missing category.

    _service_to_booking_context returns a plain dict (the mode_context update),
    not a BookingContext object. Tests must access keys directly.
    """

    def test_service_category_none_when_category_absent(self):
        """When service dict has no 'category' key, service_category in result must be None."""
        from agent.graphs.conversation_flow import _service_to_booking_context

        service = {
            "id": "svc-abc",
            "name": "Corte de Dama",
            "duration_minutes": 45,
            # no 'category' key at all
        }

        booking_ctx_dict = _service_to_booking_context(service)

        assert booking_ctx_dict["service_category"] is None, (
            f"Expected None but got {booking_ctx_dict['service_category']!r}. "
            "The fix must use `service.get('category') or None`, not `service.get('category', '')`."
        )

    def test_service_category_none_when_category_is_empty_string(self):
        """When service dict has category='', service_category in result must be None."""
        from agent.graphs.conversation_flow import _service_to_booking_context

        service = {
            "id": "svc-abc",
            "name": "Corte de Dama",
            "duration_minutes": 45,
            "category": "",  # explicit empty string
        }

        booking_ctx_dict = _service_to_booking_context(service)

        # `service.get("category") or None` coerces "" → None
        assert booking_ctx_dict["service_category"] is None, (
            f"Expected None but got {booking_ctx_dict['service_category']!r}. "
            "Empty string category must be normalised to None."
        )

    def test_service_category_preserved_when_valid(self):
        """When service dict has a valid category, it must be preserved."""
        from agent.graphs.conversation_flow import _service_to_booking_context

        service = {
            "id": "svc-abc",
            "name": "Corte de Dama",
            "duration_minutes": 45,
            "category": "HAIRDRESSING",
        }

        booking_ctx_dict = _service_to_booking_context(service)

        assert booking_ctx_dict["service_category"] == "HAIRDRESSING"

    def test_service_id_propagated(self):
        """service['id'] maps to service_id in the context dict."""
        from agent.graphs.conversation_flow import _service_to_booking_context

        service = {"id": "svc-xyz", "name": "Mechas", "duration_minutes": 90}
        booking_ctx_dict = _service_to_booking_context(service)

        assert booking_ctx_dict["service_id"] == "svc-xyz"
        assert booking_ctx_dict["service_name"] == "Mechas"
