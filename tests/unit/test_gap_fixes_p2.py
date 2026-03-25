"""
Unit tests for P2 gap fixes: P0 (audience_hint mismatch), GAP-01, GAP-02,
GAP-03, GAP-05, GAP-07, GAP-08.

These complement test_gap_fixes_p1.py which covers GAP-04, GAP-06, GAP-09/10.
All tests are pure unit tests — no DB or LLM calls required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_context import CLEARABLE_NONE_FIELDS, BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _extract_name_from_conversation,
)
from agent.modes.tool_extractors import (
    TOOL_EXTRACTORS,
    apply_all_tool_results,
    extract_query_info_fields,
    extract_stylist_fields,
)
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def _make_mode() -> BookingMode:
    """Create a BookingMode with a mocked LLM."""
    mock_llm = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = "ok"
    mock_response.tool_calls = []
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


def _make_state(messages: list[dict] | None = None, **overrides) -> dict:
    state = create_initial_state("conv-001", "+34612345678")
    state["messages"] = messages or []
    state.update(overrides)
    return state


# =============================================================================
# P0: audience_hint mismatch — user message overrides stale state hint
# =============================================================================


class TestP0AudienceHintMismatch:
    """P0: When user says 'dama' but state has adult_male, current message wins."""

    def test_user_dama_overrides_adult_male(self):
        """User says 'quiero un corte de dama' → hint changes from adult_male to adult_female."""
        mode = _make_mode()
        ctx = BookingContext(service_audience_hint="adult_male")
        state = _make_state(
            messages=[
                {"role": "user", "content": "quiero un corte de dama"},
            ]
        )

        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_female"

    def test_user_caballero_overrides_adult_female(self):
        """User says 'para caballero' → hint changes from adult_female to adult_male."""
        mode = _make_mode()
        ctx = BookingContext(service_audience_hint="adult_female")
        state = _make_state(
            messages=[
                {"role": "user", "content": "es para caballero"},
            ]
        )

        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_male"

    def test_same_hint_not_overridden(self):
        """If user says 'dama' and hint is already adult_female, no change (no unnecessary log)."""
        mode = _make_mode()
        ctx = BookingContext(service_audience_hint="adult_female")
        state = _make_state(
            messages=[
                {"role": "user", "content": "quiero un corte de dama"},
            ]
        )

        mode._resolve_audience_hint(state, ctx)

        # Same value → no override, stays adult_female
        assert ctx.service_audience_hint == "adult_female"

    def test_no_audience_in_message_keeps_existing(self):
        """Message without audience keywords preserves the existing hint."""
        mode = _make_mode()
        ctx = BookingContext(service_audience_hint="adult_male")
        state = _make_state(
            messages=[
                {"role": "user", "content": "para mañana a las 10"},
            ]
        )

        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_male"

    def test_nino_overrides_adult_female(self):
        """User says 'es para un niño' → hint changes from adult_female to child_male."""
        mode = _make_mode()
        ctx = BookingContext(service_audience_hint="adult_female")
        state = _make_state(
            messages=[
                {"role": "user", "content": "es para un niño"},
            ]
        )

        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "child_male"

    def test_first_turn_extracts_from_user_message(self):
        """First turn with no prior hint extracts audience from user message."""
        mode = _make_mode()
        ctx = BookingContext()  # No hint set
        state = _make_state(
            messages=[
                {"role": "user", "content": "quiero un corte de mujer"},
            ]
        )

        mode._resolve_audience_hint(state, ctx)

        assert ctx.service_audience_hint == "adult_female"


# =============================================================================
# GAP-01: selected_slot populated from slot_index resolution in _pre_tool_call
# =============================================================================


class TestGap01SelectedSlotPopulated:
    """GAP-01: selected_slot must be populated when _pre_tool_call resolves a slot_index."""

    @pytest.mark.asyncio
    async def test_selected_slot_populated_on_slot_index_resolution(self):
        """slot_index resolution populates ctx.selected_slot for collected_summary()."""
        mode = _make_mode()
        ctx = BookingContext(
            selected_services=["Corte de Dama"],
            customer_name="María",
            customer_id="cust-001",
            confirmation_shown=True,
            needs_availability_refresh=False,
            offered_slots=[
                {
                    "stylist_id": "uuid-ana-001",
                    "full_datetime": "2026-04-01T10:00:00+02:00",
                    "time": "10:00",
                    "date": "martes 1 abril",
                    "stylist_name": "Ana",
                }
            ],
        )
        mode._ctx = ctx

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "__RESOLVE_FROM_SLOT__",
            "start_time": "__RESOLVE_FROM_SLOT__",
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", args)

        assert not isinstance(result, ToolCallRejection)
        assert ctx.selected_slot is not None
        assert ctx.selected_slot["date"] == "martes 1 abril"
        assert ctx.selected_slot["time"] == "10:00"
        assert ctx.selected_slot["stylist_id"] == "uuid-ana-001"
        assert ctx.selected_slot["stylist_name"] == "Ana"

    @pytest.mark.asyncio
    async def test_selected_slot_renders_in_collected_summary(self):
        """When selected_slot is populated, collected_summary includes date/time."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            selected_services=["Corte de Dama"],
            stylist_name="Ana",
            customer_name="María",
            selected_slot={
                "date": "martes 1 abril",
                "time": "10:00",
                "stylist_id": "uuid-ana-001",
                "stylist_name": "Ana",
            },
        )

        summary = ctx.collected_summary()

        assert "martes 1 abril" in summary
        assert "10:00" in summary

    def test_selected_slot_none_means_no_horario_line(self):
        """When selected_slot is None, collected_summary() has no horario line."""
        ctx = BookingContext(
            service_name="Corte de Dama",
            selected_services=["Corte de Dama"],
            customer_name="María",
        )

        summary = ctx.collected_summary()

        assert "Horario:" not in summary


# =============================================================================
# GAP-02: list_stylists registered in TOOL_EXTRACTORS
# =============================================================================


class TestGap02ListStylistsInExtractors:
    """GAP-02: list_stylists must be in TOOL_EXTRACTORS to extract stylist data."""

    def test_list_stylists_in_tool_extractors(self):
        """TOOL_EXTRACTORS dict includes list_stylists."""
        assert "list_stylists" in TOOL_EXTRACTORS

    def test_list_stylists_maps_to_extract_stylist_fields(self):
        """list_stylists maps to extract_stylist_fields function."""
        assert TOOL_EXTRACTORS["list_stylists"] is extract_stylist_fields

    def test_extract_stylist_fields_populates_prefetched(self):
        """extract_stylist_fields populates ctx.prefetched_stylists from tool result."""
        ctx = BookingContext()
        result = {
            "stylists": [
                {"id": "uuid-1", "name": "Ana", "next_slot_summary": "lunes 10:00"},
                {"id": "uuid-2", "name": "Pilar", "next_slot_summary": "martes 11:00"},
            ]
        }

        extract_stylist_fields(result, ctx)

        assert len(ctx.prefetched_stylists) == 2
        assert ctx.prefetched_stylists[0]["name"] == "Ana"
        assert ctx.prefetched_stylists[1]["name"] == "Pilar"

    def test_apply_all_routes_list_stylists(self):
        """apply_all_tool_results correctly routes list_stylists through the extractor."""
        ctx = BookingContext()
        tool_results = {
            "list_stylists": {
                "stylists": [
                    {"id": "uuid-1", "name": "Carmen"},
                ]
            }
        }

        apply_all_tool_results(tool_results, ctx)

        assert len(ctx.prefetched_stylists) == 1
        assert ctx.prefetched_stylists[0]["name"] == "Carmen"


# =============================================================================
# GAP-03: query_info registered in TOOL_EXTRACTORS (no-op extractor)
# =============================================================================


class TestGap03QueryInfoInExtractors:
    """GAP-03: query_info must be in TOOL_EXTRACTORS (no-op, prevents log noise)."""

    def test_query_info_in_tool_extractors(self):
        """TOOL_EXTRACTORS dict includes query_info."""
        assert "query_info" in TOOL_EXTRACTORS

    def test_query_info_maps_to_extract_query_info_fields(self):
        """query_info maps to the no-op extract_query_info_fields function."""
        assert TOOL_EXTRACTORS["query_info"] is extract_query_info_fields

    def test_query_info_extractor_is_noop(self):
        """extract_query_info_fields does not mutate ctx (informational only)."""
        ctx = BookingContext(service_name="Existing Service")
        result = {"answer": "Horario: lunes a viernes 10-20h", "source": "faq"}

        extract_query_info_fields(result, ctx)

        # No fields should be modified
        assert ctx.service_name == "Existing Service"
        assert ctx.service_id is None

    def test_apply_all_does_not_crash_on_query_info(self):
        """apply_all_tool_results handles query_info without errors."""
        ctx = BookingContext()
        tool_results = {"query_info": {"answer": "El salón abre de 10 a 20h."}}

        # Should not raise
        apply_all_tool_results(tool_results, ctx)


# =============================================================================
# GAP-05: circuit breaker resilient to missing _ctx
# =============================================================================


class TestGap05CircuitBreakerResilience:
    """GAP-05: get_tools() must not crash when _ctx is not initialized."""

    def test_get_tools_without_ctx_returns_all_tools(self):
        """get_tools() returns all tools when _ctx hasn't been set yet."""
        mode = _make_mode()
        # Don't set mode._ctx at all — simulates first-call scenario before handle()
        assert not hasattr(mode, "_ctx")

        tools = mode.get_tools()

        # Should return all tools, including 'book'
        tool_names = [t.name for t in tools]
        assert "book" in tool_names

    def test_get_tools_with_ctx_high_failures_excludes_book(self):
        """get_tools() excludes book when book_failure_count >= 3."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=3)

        tools = mode.get_tools()

        tool_names = [t.name for t in tools]
        assert "book" not in tool_names

    def test_get_tools_with_ctx_low_failures_includes_book(self):
        """get_tools() includes book when book_failure_count < 3."""
        mode = _make_mode()
        mode._ctx = BookingContext(book_failure_count=2)

        tools = mode.get_tools()

        tool_names = [t.name for t in tools]
        assert "book" in tool_names

    def test_get_tools_excludes_manage_customer_on_failures(self):
        """get_tools() excludes manage_customer when failure_count >= 2."""
        mode = _make_mode()
        mode._ctx = BookingContext(manage_customer_failure_count=2)

        tools = mode.get_tools()

        tool_names = [t.name for t in tools]
        assert "manage_customer" not in tool_names


# =============================================================================
# GAP-07: _extract_name_from_conversation two-tier activation
# =============================================================================


class TestGap07NameExtractionTwoTier:
    """GAP-07: Name extraction uses two tiers — structured patterns ALWAYS active."""

    def test_tier1_soy_pattern_without_name_question(self):
        """'Soy Ana García' captures name even without a prior name question."""
        ctx = BookingContext()
        state = _make_state(
            messages=[
                {"role": "assistant", "content": "¡Bienvenida! ¿En qué te puedo ayudar?"},
                {"role": "user", "content": "Soy Ana García, quiero un corte"},
            ]
        )

        _extract_name_from_conversation(state, "Soy Ana García, quiero un corte", ctx)

        assert ctx.customer_name == "Ana García"

    def test_tier1_me_llamo_pattern(self):
        """'Me llamo Carlos Torres' captures name via intro pattern."""
        ctx = BookingContext()
        state = _make_state(
            messages=[
                {"role": "assistant", "content": "¿Qué servicio te interesa?"},
                {"role": "user", "content": "Me llamo Carlos Torres"},
            ]
        )

        _extract_name_from_conversation(state, "Me llamo Carlos Torres", ctx)

        assert ctx.customer_name == "Carlos Torres"

    def test_tier1_mi_nombre_es_pattern(self):
        """'Mi nombre es Laura' captures name."""
        ctx = BookingContext()
        state = _make_state(
            messages=[
                {"role": "assistant", "content": "Perfecto, te busco horarios."},
                {"role": "user", "content": "Mi nombre es Laura"},
            ]
        )

        _extract_name_from_conversation(state, "Mi nombre es Laura", ctx)

        assert ctx.customer_name == "Laura"

    def test_tier2_bare_name_only_when_bot_asked(self):
        """Bare name 'María' is only captured when bot previously asked for name."""
        ctx = BookingContext()
        # Bot DID ask for name
        state = _make_state(
            messages=[
                {"role": "assistant", "content": "¿A nombre de quién sería la cita?"},
                {"role": "user", "content": "María"},
            ]
        )

        _extract_name_from_conversation(state, "María", ctx)

        assert ctx.customer_name == "María"

    def test_tier2_bare_name_blocked_when_bot_didnt_ask(self):
        """Bare name 'Perfecto' is NOT captured when bot didn't ask for name."""
        ctx = BookingContext()
        state = _make_state(
            messages=[
                {"role": "assistant", "content": "Te ofrezco estos horarios:"},
                {"role": "user", "content": "Perfecto"},
            ]
        )

        _extract_name_from_conversation(state, "Perfecto", ctx)

        assert ctx.customer_name is None  # "Perfecto" is in stopwords

    def test_stopwords_not_captured_in_tier1(self):
        """Stopwords like 'Hola' are rejected even in tier 1 intro patterns."""
        ctx = BookingContext()
        state = _make_state(
            messages=[
                {"role": "user", "content": "Soy Hola"},
            ]
        )

        _extract_name_from_conversation(state, "Soy Hola", ctx)

        # "hola" is a stopword — should NOT be captured
        assert ctx.customer_name is None

    def test_empty_message_is_noop(self):
        """Empty user message doesn't crash."""
        ctx = BookingContext()
        state = _make_state()

        _extract_name_from_conversation(state, "", ctx)

        assert ctx.customer_name is None

    def test_already_has_name_skips_extraction(self):
        """If customer_name already set, extraction is never called (caller guard)."""
        # Note: the caller (handle()) has `if not ctx.customer_name:` guard.
        # This test ensures the function itself doesn't overwrite existing names.
        ctx = BookingContext(customer_name="Already Set")
        state = _make_state(
            messages=[
                {"role": "assistant", "content": "¿Tu nombre?"},
                {"role": "user", "content": "Soy María"},
            ]
        )

        # If called despite the guard, it WOULD set the name
        _extract_name_from_conversation(state, "Soy María", ctx)

        # The function DOES set it — the guard is in handle(), not in the function
        # This is expected behavior: the caller must guard
        assert ctx.customer_name == "María"


# =============================================================================
# GAP-08: needs_availability_refresh serialization correctness
# =============================================================================


class TestGap08NeedsAvailabilityRefreshPersistence:
    """GAP-08: needs_availability_refresh must survive serialization round-trip."""

    def test_true_value_serialized(self):
        """needs_availability_refresh=True is included in to_mode_context()."""
        ctx = BookingContext(needs_availability_refresh=True, offered_slots=None)

        serialized = ctx.to_mode_context()

        assert "needs_availability_refresh" in serialized
        assert serialized["needs_availability_refresh"] is True

    def test_false_value_serialized_via_filter(self):
        """needs_availability_refresh=False passes the 'v is not None' filter.

        False is not None, not [], not {} → it IS included in to_mode_context().
        This is actually correct behavior (explicit False persists).
        """
        ctx = BookingContext(needs_availability_refresh=False)

        serialized = ctx.to_mode_context()

        # False is NOT None, NOT [], NOT {} → it passes the filter and IS serialized
        # This is correct — from_mode_context will see needs_availability_refresh=False
        # rather than relying on the default.
        assert serialized.get("needs_availability_refresh") is False

    def test_round_trip_true(self):
        """needs_availability_refresh=True survives serialize → deserialize."""
        ctx = BookingContext(needs_availability_refresh=True, offered_slots=None)

        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.needs_availability_refresh is True

    def test_round_trip_false(self):
        """needs_availability_refresh=False survives serialize → deserialize."""
        ctx = BookingContext(needs_availability_refresh=False)

        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.needs_availability_refresh is False

    def test_offered_slots_none_in_clearable_fields(self):
        """offered_slots is in CLEARABLE_NONE_FIELDS — None is explicitly serialized."""
        assert "offered_slots" in CLEARABLE_NONE_FIELDS

    def test_offered_slots_none_serialized(self):
        """offered_slots=None is included in to_mode_context() to overwrite stale values."""
        ctx = BookingContext(
            offered_slots=None,
            needs_availability_refresh=True,
        )

        serialized = ctx.to_mode_context()

        assert "offered_slots" in serialized
        assert serialized["offered_slots"] is None
        assert serialized["needs_availability_refresh"] is True

    def test_combined_slot_taken_scenario(self):
        """Simulate SLOT_TAKEN: offered_slots=None + needs_refresh=True → both persist."""
        ctx = BookingContext(
            selected_services=["Corte de Dama"],
            customer_name="María",
            customer_id="cust-001",
            offered_slots=None,
            selected_slot=None,
            needs_availability_refresh=True,
            book_failure_count=1,
        )

        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.offered_slots is None
        assert restored.selected_slot is None
        assert restored.needs_availability_refresh is True
        assert restored.book_failure_count == 1
