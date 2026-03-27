"""
Unit tests for offered-slots-refresh-fix — slot state management and validation.

Tests cover:
- _clear_slot_state() helper
- Stylist UUID inclusion in _build_stylists_section()
- stylist_id validation in _pre_tool_call()
- Audience canonicalization in _pre_tool_call()
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _build_stylists_section,
    _clear_slot_state,
)


def make_mock_llm(response_text: str = "¿Qué servicio deseas?") -> AsyncMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "¿Qué servicio deseas?") -> BookingMode:
    mock_llm = make_mock_llm(llm_response)
    return BookingMode(tools=[], llm_client=mock_llm)


# =============================================================================
# Test _clear_slot_state()
# =============================================================================


class TestClearSlotState:
    """Tests for _clear_slot_state() helper."""

    def test_clear_slot_state_resets_all_fields(self):
        """_clear_slot_state should clear all 6 fields."""
        ctx = BookingContext(
            offered_slots=[{"time": "10:00"}],
            selected_slot={"time": "10:00"},
            stylist_id="s1-uuid",
            stylist_name="Ana",
            confirmation_shown=True,
            confirmation_summary_sent=True,
        )
        _clear_slot_state(ctx)

        assert ctx.offered_slots == []
        assert ctx.selected_slot is None
        assert ctx.stylist_id is None
        assert ctx.stylist_name is None
        assert ctx.confirmation_shown is False
        assert ctx.confirmation_summary_sent is False

    def test_clear_slot_state_preserves_needs_refresh(self):
        """_clear_slot_state should NOT clear needs_availability_refresh."""
        ctx = BookingContext(
            offered_slots=[{"time": "10:00"}],
            needs_availability_refresh=True,
        )
        _clear_slot_state(ctx)

        # Flag should remain unchanged
        assert ctx.needs_availability_refresh is True

    def test_clear_slot_state_idempotent(self):
        """Calling _clear_slot_state twice should be safe."""
        ctx = BookingContext(
            offered_slots=[{"time": "10:00"}],
            stylist_id="s1",
            confirmation_shown=True,
        )
        _clear_slot_state(ctx)
        _clear_slot_state(ctx)

        # All fields should still be cleared
        assert ctx.offered_slots == []
        assert ctx.stylist_id is None
        assert ctx.confirmation_shown is False


# =============================================================================
# Test _build_stylists_section() UUID inclusion
# =============================================================================


class TestStylistsSectionIncludesUuid:
    """Tests for _build_stylists_section() UUID inclusion."""

    def test_stylists_section_includes_uuid(self):
        """_build_stylists_section should include UUID for each stylist."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-1", "name": "Ana"},
                {"id": "uuid-2", "name": "María"},
            ]
        )
        output = _build_stylists_section(ctx)

        # Output should contain UUIDs
        assert "uuid-1" in output
        assert "uuid-2" in output
        assert "Ana | id:" in output
        assert "María | id:" in output

    def test_stylists_section_numbered_list(self):
        """_build_stylists_section should number stylists starting from 1."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-1", "name": "Ana"},
                {"id": "uuid-2", "name": "María"},
            ]
        )
        output = _build_stylists_section(ctx)

        lines = output.split("\n")
        # First two lines should be numbered options
        assert lines[0].startswith("1.")
        assert lines[1].startswith("2.")
        # Last option should be "any stylist" with next number
        assert "La estilista con disponibilidad más temprana" in output
        assert "3." in output

    def test_stylists_section_empty_list_returns_empty(self):
        """_build_stylists_section should return empty string when no stylists."""
        ctx = BookingContext(prefetched_stylists=[])
        output = _build_stylists_section(ctx)

        assert output == ""

    def test_stylists_section_with_recurrent_hint(self):
        """_build_stylists_section should include recurrent stylist hint if set."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-1", "name": "Ana"},
            ],
            recurrent_stylist_hint="Ana María",
        )
        output = _build_stylists_section(ctx)

        assert "Estilista habitual de la clienta: Ana María" in output


# =============================================================================
# Test Stylist ID Validation in _pre_tool_call()
# =============================================================================


class TestUuidValidation:
    """Tests for stylist_id validation in _pre_tool_call()."""

    @pytest.mark.asyncio
    async def test_uuid_validation_strips_invented(self):
        """Invalid stylist_id should be replaced with None."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=[
                {"id": "valid-uuid-1", "name": "Ana"},
                {"id": "valid-uuid-2", "name": "María"},
            ]
        )

        tool_args = {"stylist_id": "d56ep39a-invented", "date": "2026-04-02"}
        result = await mode._pre_tool_call("check_availability", tool_args)

        # Invalid UUID should be replaced with None
        assert result["stylist_id"] is None

    @pytest.mark.asyncio
    async def test_uuid_validation_preserves_valid_uuid(self):
        """Valid stylist_id should be preserved."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=[
                {"id": "valid-uuid-1", "name": "Ana"},
            ]
        )

        tool_args = {"stylist_id": "valid-uuid-1", "date": "2026-04-02"}
        result = await mode._pre_tool_call("check_availability", tool_args)

        # Valid UUID should be preserved
        assert result["stylist_id"] == "valid-uuid-1"

    @pytest.mark.asyncio
    async def test_uuid_validation_none_stylist_id_passthrough(self):
        """When stylist_id is already None, it should remain None."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=[
                {"id": "valid-uuid-1", "name": "Ana"},
            ]
        )

        tool_args = {"stylist_id": None, "date": "2026-04-02"}
        result = await mode._pre_tool_call("check_availability", tool_args)

        # None should be preserved
        assert result["stylist_id"] is None

    @pytest.mark.asyncio
    async def test_uuid_validation_with_find_next_available(self):
        """UUID validation should work for find_next_available tool too."""
        mode = make_booking_mode()
        mode._ctx = BookingContext(
            prefetched_stylists=[
                {"id": "valid-uuid-1", "name": "Ana"},
            ]
        )

        tool_args = {"stylist_id": "bad-uuid", "service_category": "HAIRDRESSING"}
        result = await mode._pre_tool_call("find_next_available", tool_args)

        assert result["stylist_id"] is None


# =============================================================================
# Test Audience Canonicalization in _pre_tool_call()
# =============================================================================


class TestAudienceCanonicalization:
    """Tests for audience canonicalization in _pre_tool_call()."""

    @pytest.mark.asyncio
    async def test_audience_canonicalization_dama(self):
        """Non-canonical 'dama' should be converted to 'adult_female'."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte", "audience": "dama"}
        result = await mode._pre_tool_call("search_services", tool_args)

        # dama should be canonicalized to adult_female
        assert result["audience"] == "adult_female"

    @pytest.mark.asyncio
    async def test_audience_canonicalization_already_canonical(self):
        """Canonical 'adult_female' should be unchanged."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte", "audience": "adult_female"}
        result = await mode._pre_tool_call("search_services", tool_args)

        # Already canonical — should remain unchanged
        assert result["audience"] == "adult_female"

    @pytest.mark.asyncio
    async def test_audience_canonicalization_case_insensitive(self):
        """Canonicalization should be case-insensitive."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte", "audience": "DAMA"}
        result = await mode._pre_tool_call("search_services", tool_args)

        # DAMA (uppercase) should be canonicalized to adult_female
        assert result["audience"] == "adult_female"

    @pytest.mark.asyncio
    async def test_audience_canonicalization_caballero(self):
        """Non-canonical 'caballero' should be converted to 'adult_male'."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte", "audience": "caballero"}
        result = await mode._pre_tool_call("search_services", tool_args)

        assert result["audience"] == "adult_male"

    @pytest.mark.asyncio
    async def test_audience_canonicalization_unknown_value(self):
        """Unknown audience value should be preserved as-is."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte", "audience": "unknown_value"}
        result = await mode._pre_tool_call("search_services", tool_args)

        # Unknown value should be preserved
        assert result["audience"] == "unknown_value"

    @pytest.mark.asyncio
    async def test_audience_canonicalization_no_audience_arg(self):
        """When audience arg is not present, tool_args should be unchanged."""
        mode = make_booking_mode()
        mode._ctx = BookingContext()

        tool_args = {"query": "corte"}
        result = await mode._pre_tool_call("search_services", tool_args)

        # No audience arg — should not be added
        assert "audience" not in result
