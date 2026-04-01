"""
Unit tests for booking-mode category-filtering bug fixes.

Covers fixes from the stylist-category-filtering-fix change:

Phase 2 — Context propagation:
  REQ-2: _maybe_prefetch_stylists skips when service_category is None
  REQ-3: _pre_tool_call injects service_category into list_stylists args

Phase 4 — Post-loop compliance:
  REQ-8: _detect_tool_skips Condition B fires when prefetched names absent
         from LLM response, suppressed when names present, and suppressed
         when stylist_id already set.

Phase 5 — conversation_flow context handoff:
  REQ-5: _service_to_booking_context returns None (not '') for absent/empty category

All tests mock DB/LLM — no live infrastructure required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
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


def make_agentic_loop_result(
    response_text: str = "",
    tool_results: dict | None = None,
) -> AgenticLoopResult:
    """Build a minimal AgenticLoopResult for _detect_tool_skips tests.

    AgenticLoopResult is a @dataclass with fields:
        response_text, tool_results, error, tool_events
    """
    return AgenticLoopResult(
        response_text=response_text,
        tool_results=tool_results or {},
    )


# ---------------------------------------------------------------------------
# REQ-2: _maybe_prefetch_stylists — skip when service_category is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMaybePrefetchStylistsNoneCategory:
    """REQ-2: _maybe_prefetch_stylists must skip prefetch when service_category is None."""

    async def test_skips_when_service_category_is_none(self):
        """When service_id is set but service_category is None, prefetch is skipped."""
        mode = make_booking_mode()
        ctx = BookingContext(
            service_id="some-uuid-service",
            service_category=None,  # ← the fix: was being passed as "" before
        )

        # Patch list_stylists at source module to detect if it was called.
        # _maybe_prefetch_stylists does a local import from agent.tools.info_tools,
        # so we patch the symbol there.
        list_stylists_mock = AsyncMock(return_value={"stylists": [], "count": 0})
        with patch("agent.tools.info_tools.list_stylists", list_stylists_mock):
            await mode._maybe_prefetch_stylists(ctx)

        # service_category is None → should not call list_stylists
        list_stylists_mock.assert_not_called()

    async def test_prefetched_stylists_remains_empty_when_skipped(self):
        """When skipped (None category), ctx.prefetched_stylists stays []."""
        mode = make_booking_mode()
        ctx = BookingContext(
            service_id="some-uuid-service",
            service_category=None,
        )

        list_stylists_mock = AsyncMock(
            return_value={"stylists": [{"id": "s1", "name": "Ana"}], "count": 1}
        )
        with patch("agent.tools.info_tools.list_stylists", list_stylists_mock):
            await mode._maybe_prefetch_stylists(ctx)

        assert ctx.prefetched_stylists == []

    async def test_skips_when_no_service_id(self):
        """When service_id is None, prefetch is also skipped (no service resolved yet)."""
        mode = make_booking_mode()
        ctx = BookingContext(
            service_id=None,
            service_category="HAIRDRESSING",
        )

        list_stylists_mock = AsyncMock(return_value={"stylists": [], "count": 0})
        with patch("agent.tools.info_tools.list_stylists", list_stylists_mock):
            await mode._maybe_prefetch_stylists(ctx)

        # No service_id → should not call list_stylists
        list_stylists_mock.assert_not_called()
        assert ctx.prefetched_stylists == []

    async def test_skips_when_stylist_already_selected(self):
        """When stylist_id is already set, prefetch is skipped (already resolved)."""
        mode = make_booking_mode()
        ctx = BookingContext(
            service_id="some-uuid-service",
            service_category="HAIRDRESSING",
            stylist_id="stylist-uuid-ana",
        )

        list_stylists_mock = AsyncMock(return_value={"stylists": [], "count": 0})
        with patch("agent.tools.info_tools.list_stylists", list_stylists_mock):
            await mode._maybe_prefetch_stylists(ctx)

        list_stylists_mock.assert_not_called()

    async def test_skips_when_already_prefetched(self):
        """When prefetched_stylists already populated, skip to avoid re-fetching."""
        mode = make_booking_mode()
        ctx = BookingContext(
            service_id="some-uuid-service",
            service_category="HAIRDRESSING",
            prefetched_stylists=[{"id": "s1", "name": "Ana"}],
        )

        list_stylists_mock = AsyncMock(return_value={"stylists": [], "count": 0})
        with patch("agent.tools.info_tools.list_stylists", list_stylists_mock):
            await mode._maybe_prefetch_stylists(ctx)

        list_stylists_mock.assert_not_called()


# ---------------------------------------------------------------------------
# REQ-3: _pre_tool_call — inject category into list_stylists args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPreToolCallCategoryInjection:
    """REQ-3: _pre_tool_call injects service_category into list_stylists args."""

    async def test_injects_category_when_not_present_in_args(self):
        """When ctx.service_category is set and args have no 'category', inject it."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            service_category="HAIRDRESSING",
        )
        tool_args = {}  # LLM did not provide category

        result = await mode._pre_tool_call("list_stylists", tool_args)

        assert result.get("category") == "HAIRDRESSING"

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
# REQ-8: _detect_tool_skips — Condition B (post-loop compliance)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDetectToolSkipsConditionB:
    """REQ-8: Condition B fires when prefetched stylists are absent from LLM response."""

    async def test_fires_when_no_name_in_response(self):
        """When prefetched names do not appear in response_text, reminder is set."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id=None,
        )
        result = make_agentic_loop_result(
            response_text=(
                "¿Con quién te gustaría la cita? 1. La estilista con disponibilidad más próxima"
            )
        )

        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is True

    async def test_fires_when_all_names_absent(self):
        """Even with multiple prefetched stylists, if none appear, reminder fires."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "uuid-ana"},
                {"name": "Marta", "id": "uuid-marta"},
            ],
            stylist_id=None,
        )
        result = make_agentic_loop_result(
            response_text="¿Con quién preferís trabajar? Elige según tu preferencia."
        )

        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is True

    async def test_suppressed_when_name_present_in_response(self):
        """When at least one prefetched name appears in response_text, reminder is NOT set."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id=None,
        )
        result = make_agentic_loop_result(
            response_text=(
                "¿Con quién te gustaría la cita?\n"
                "1. Ana\n"
                "2. La estilista con disponibilidad más próxima"
            )
        )

        await mode._detect_tool_skips(result, ctx)

        # "Ana" is in response → Condition B must NOT set force_list_stylists_reminder to True
        assert ctx.force_list_stylists_reminder is False

    async def test_suppressed_when_name_present_case_insensitive(self):
        """Name matching is case-insensitive (e.g. 'ANA' matches 'Ana')."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id=None,
        )
        result = make_agentic_loop_result(response_text="¿Con quién? Opciones: 1. ANA  2. Marta")

        await mode._detect_tool_skips(result, ctx)

        assert ctx.force_list_stylists_reminder is False

    async def test_suppressed_when_stylist_already_selected(self):
        """Condition B must NOT fire when stylist_id is already set (stylist resolved)."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id="uuid-ana",  # ← already selected
        )
        result = make_agentic_loop_result(
            response_text=(
                "¿Con quién te gustaría la cita? 1. La estilista con disponibilidad más próxima"
            )
        )

        await mode._detect_tool_skips(result, ctx)

        # stylist_id is set → Condition B guard MUST NOT fire
        assert ctx.force_list_stylists_reminder is not True

    async def test_suppressed_when_no_prefetched_stylists(self):
        """When ctx.prefetched_stylists is empty, Condition B cannot fire."""
        mode = make_booking_mode()
        ctx = BookingContext(
            service_id="some-service",  # service_id set so Condition A doesn't fire via a different path
            prefetched_stylists=[],
            stylist_id=None,
        )
        # Also simulate list_stylists was called (to suppress Condition A)
        result = make_agentic_loop_result(
            response_text="¿Con quién preferís trabajar?",
            tool_results={"list_stylists": {"stylists": [], "count": 0}},
        )

        await mode._detect_tool_skips(result, ctx)

        # No prefetched_stylists → Condition B cannot fire
        # force_list_stylists_reminder should be False here (Condition A suppressed by tool_results)
        assert ctx.force_list_stylists_reminder is False

    async def test_suppressed_when_empty_response_text(self):
        """When response_text is empty, Condition B cannot fire (no text to scan)."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id=None,
        )
        result = make_agentic_loop_result(response_text="")

        await mode._detect_tool_skips(result, ctx)

        # No response_text → Condition B guard cannot fire
        # (The `and result.response_text` guard in the condition prevents it)
        assert ctx.force_list_stylists_reminder is not True

    async def test_second_name_match_suppresses_reminder(self):
        """If only the second prefetched name appears in response, reminder is suppressed."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[
                {"name": "Ana", "id": "uuid-ana"},
                {"name": "Marta", "id": "uuid-marta"},
            ],
            stylist_id=None,
        )
        result = make_agentic_loop_result(
            response_text="Tenemos disponibilidad con Marta para esta semana."
        )

        await mode._detect_tool_skips(result, ctx)

        # "Marta" found in response → NOT all names absent → Condition B suppressed
        assert ctx.force_list_stylists_reminder is False

    async def test_mid_selection_guard_suppresses_flag_when_list_was_shown(self):
        """M-5 guard: when assistant already presented stylist list last turn,
        Condition B must NOT set force_list_stylists_reminder (user is mid-selection)."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id=None,
        )
        # Simulate: assistant showed stylist list last turn (both markers required by
        # _previous_assistant_presented_stylists: numbered capitalized name + stylist phrase)
        mode._current_state = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "¿Con quién querés tu turno?\n1. Ana\n2. Marta",
                }
            ]
        }
        # Response text does NOT contain the name → outer Condition B would fire
        result = make_agentic_loop_result(response_text="Perfecto, ¿cuál preferís?")

        await mode._detect_tool_skips(result, ctx)

        # Guard must suppress → flag stays False
        assert ctx.force_list_stylists_reminder is False

    async def test_genuine_skip_sets_flag_when_no_prior_presentation(self):
        """M-5 guard: when no prior stylist list presentation, Condition B still fires."""
        mode = make_booking_mode()
        ctx = BookingContext(
            prefetched_stylists=[{"name": "Ana", "id": "uuid-ana"}],
            stylist_id=None,
        )
        # Simulate: last assistant message was NOT a stylist list
        mode._current_state = {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Perfecto, ya tenés tu cita agendada.",
                }
            ]
        }
        # Response text does NOT contain the name → Condition B should fire
        result = make_agentic_loop_result(response_text="¿Querés agregar algo más?")

        await mode._detect_tool_skips(result, ctx)

        # No prior presentation → guard inactive → flag must be True
        assert ctx.force_list_stylists_reminder is True


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
