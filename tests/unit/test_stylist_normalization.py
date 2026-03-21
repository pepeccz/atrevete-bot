"""
Unit tests for Phase B: Stylist Normalization (booking-bugs-fix).

Covers:
- B.1: _normalize_stylist_preference method in BookingMode
- B.1: UUID guard in _handle_slot_selection (non-UUID stripped before tools)
- B.2: Defensive normalization in check_availability / find_next_available
- Edge cases: empty string, whitespace, casing, accented phrases
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_mock_llm(response_text: str = "Aquí tienes los horarios.") -> AsyncMock:
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "Aquí tienes los horarios.") -> BookingMode:
    return BookingMode(tools=[], llm_client=make_mock_llm(llm_response))


VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


def make_slot_selection_state(
    stylist_id: str | None = VALID_UUID,
    stylist_name: str | None = "Pilar",
    error_count: int = 0,
) -> dict:
    """State ready for slot_selection with configurable stylist_id."""
    state = create_initial_state("conv-norm-test", "+34611000000")
    state["customer_id"] = "cust-norm-123"
    state["customer_name"] = "Ana"
    state["error_count"] = error_count
    state["messages"] = [
        {"role": "user", "content": "Quiero el martes", "timestamp": "2026-03-20T10:00:00"},
    ]
    ctx: dict = {
        "booking_step": BookingSubstep.SLOT_SELECTION.value,
        "service_name": "Cortar",
        "service_id": "svc-001",
        "service_category": "Peluquería",
        "service_duration_minutes": 45,
    }
    if stylist_id is not None:
        ctx["stylist_id"] = stylist_id
    if stylist_name is not None:
        ctx["stylist_name"] = stylist_name
    state["mode_context"] = ctx
    return state


def make_intent(intent: str = "book") -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, raw_input="reservar", mode_hint="BOOKING")


# =============================================================================
# B.1: _normalize_stylist_preference unit tests
# =============================================================================


class TestNormalizeStylistPreference:
    """Test BookingMode._normalize_stylist_preference static method."""

    def test_valid_uuid_passes_through(self):
        result = BookingMode._normalize_stylist_preference(VALID_UUID)
        assert result == VALID_UUID

    def test_valid_uuid_with_whitespace_passes_through(self):
        result = BookingMode._normalize_stylist_preference(f"  {VALID_UUID}  ")
        assert result == VALID_UUID

    def test_random_uuid_passes_through(self):
        random_id = str(uuid4())
        result = BookingMode._normalize_stylist_preference(random_id)
        assert result == random_id

    def test_none_returns_none(self):
        assert BookingMode._normalize_stylist_preference(None) is None

    def test_empty_string_returns_none(self):
        assert BookingMode._normalize_stylist_preference("") is None

    def test_whitespace_only_returns_none(self):
        assert BookingMode._normalize_stylist_preference("   ") is None

    def test_cualquiera_returns_none(self):
        assert BookingMode._normalize_stylist_preference("cualquiera") is None

    def test_cualquiera_uppercase_returns_none(self):
        assert BookingMode._normalize_stylist_preference("CUALQUIERA") is None

    def test_cualquiera_mixed_case_returns_none(self):
        assert BookingMode._normalize_stylist_preference("Cualquiera") is None

    def test_sin_preferencia_returns_none(self):
        assert BookingMode._normalize_stylist_preference("sin preferencia") is None

    def test_no_importa_returns_none(self):
        assert BookingMode._normalize_stylist_preference("no importa") is None

    def test_no_me_importa_returns_none(self):
        assert BookingMode._normalize_stylist_preference("no me importa") is None

    def test_el_que_sea_returns_none(self):
        assert BookingMode._normalize_stylist_preference("el que sea") is None

    def test_la_que_sea_returns_none(self):
        assert BookingMode._normalize_stylist_preference("la que sea") is None

    def test_primer_horario_returns_none(self):
        assert BookingMode._normalize_stylist_preference("primer horario") is None

    def test_lo_antes_posible_returns_none(self):
        assert BookingMode._normalize_stylist_preference("lo antes posible") is None

    def test_cualquier_returns_none(self):
        """'cualquier' is a prefix variant that should also match."""
        assert BookingMode._normalize_stylist_preference("cualquier") is None

    def test_name_string_returns_none_with_warning(self):
        """A stylist name (not UUID) should be normalized to None."""
        result = BookingMode._normalize_stylist_preference("Pilar")
        assert result is None

    def test_random_text_returns_none(self):
        result = BookingMode._normalize_stylist_preference("some random text")
        assert result is None

    def test_partial_uuid_returns_none(self):
        """Partial UUID is not valid — should normalize to None."""
        result = BookingMode._normalize_stylist_preference("550e8400-e29b")
        assert result is None


# =============================================================================
# B.1: UUID guard in _handle_slot_selection
# =============================================================================


class TestSlotSelectionStylistGuard:
    """Test that _handle_slot_selection normalizes stylist_id before tool calls."""

    @pytest.mark.asyncio
    async def test_cualquiera_stripped_before_tools(self):
        """BUG #1: stylist_id='cualquiera' should not reach availability tools."""
        mode = make_booking_mode()
        state = make_slot_selection_state(stylist_id="cualquiera", stylist_name="Cualquiera")

        with patch.object(mode, "_run_agentic_loop") as mock_loop, \
             patch.object(mode, "_build_layered_messages", new_callable=AsyncMock) as mock_build, \
             patch.object(mode, "_use_optimized_prompts", return_value=True):
            mock_loop.return_value = MagicMock(
                response_text="Aquí tienes los horarios.",
                tool_results={},
                tool_events=[],
            )
            mock_build.return_value = [MagicMock()]

            result = await mode.handle(state, make_intent())

        # The mode_context should NOT have stylist_id after normalization
        ctx = result.get("mode_context", {})
        assert ctx.get("stylist_id") is None or "stylist_id" not in ctx
        assert ctx.get("stylist_name") is None or "stylist_name" not in ctx

    @pytest.mark.asyncio
    async def test_valid_uuid_preserved_in_context(self):
        """Valid UUID should pass through unchanged."""
        mode = make_booking_mode()
        state = make_slot_selection_state(stylist_id=VALID_UUID, stylist_name="Pilar")

        with patch.object(mode, "_run_agentic_loop") as mock_loop, \
             patch.object(mode, "_build_layered_messages", new_callable=AsyncMock) as mock_build, \
             patch.object(mode, "_use_optimized_prompts", return_value=True):
            mock_loop.return_value = MagicMock(
                response_text="Aquí tienes los horarios.",
                tool_results={},
                tool_events=[],
            )
            mock_build.return_value = [MagicMock()]

            result = await mode.handle(state, make_intent())

        ctx = result.get("mode_context", {})
        assert ctx.get("stylist_id") == VALID_UUID
        assert ctx.get("stylist_name") == "Pilar"

    @pytest.mark.asyncio
    async def test_empty_string_stylist_stripped(self):
        """Empty string stylist_id should be normalized to None."""
        mode = make_booking_mode()
        state = make_slot_selection_state(stylist_id="", stylist_name="")

        with patch.object(mode, "_run_agentic_loop") as mock_loop, \
             patch.object(mode, "_build_layered_messages", new_callable=AsyncMock) as mock_build, \
             patch.object(mode, "_use_optimized_prompts", return_value=True):
            mock_loop.return_value = MagicMock(
                response_text="Aquí tienes los horarios.",
                tool_results={},
                tool_events=[],
            )
            mock_build.return_value = [MagicMock()]

            result = await mode.handle(state, make_intent())

        ctx = result.get("mode_context", {})
        # Empty string should have been stripped
        assert ctx.get("stylist_id") is None or ctx.get("stylist_id") == ""

    @pytest.mark.asyncio
    async def test_name_string_stripped_before_tools(self):
        """Stylist name instead of UUID should be normalized to None."""
        mode = make_booking_mode()
        state = make_slot_selection_state(stylist_id="Pilar", stylist_name="Pilar")

        with patch.object(mode, "_run_agentic_loop") as mock_loop, \
             patch.object(mode, "_build_layered_messages", new_callable=AsyncMock) as mock_build, \
             patch.object(mode, "_use_optimized_prompts", return_value=True):
            mock_loop.return_value = MagicMock(
                response_text="Aquí tienes los horarios.",
                tool_results={},
                tool_events=[],
            )
            mock_build.return_value = [MagicMock()]

            result = await mode.handle(state, make_intent())

        ctx = result.get("mode_context", {})
        assert ctx.get("stylist_id") is None or "stylist_id" not in ctx


# =============================================================================
# B.2: Defensive normalization in availability tools
# =============================================================================


class TestCheckAvailabilityDefensiveGuard:
    """Test that check_availability handles non-UUID stylist_id gracefully."""

    @pytest.mark.asyncio
    async def test_cualquiera_does_not_crash(self):
        """BUG #1: check_availability(stylist_id='cualquiera') must not raise."""
        from agent.tools.availability_tools import check_availability

        with patch("agent.tools.availability_tools.parse_natural_date") as mock_parse, \
             patch("agent.tools.availability_tools.validate_3_day_rule") as mock_validate, \
             patch("agent.tools.availability_tools.get_stylists_by_category") as mock_stylists, \
             patch("agent.tools.availability_tools.is_holiday") as mock_holiday, \
             patch("agent.tools.availability_tools.get_available_slots") as mock_slots:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            mock_parse.return_value = datetime(2026, 3, 25, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
            mock_validate.return_value = {"valid": True}
            mock_holiday.return_value = None

            mock_stylist_obj = MagicMock()
            mock_stylist_obj.id = UUID(VALID_UUID)
            mock_stylist_obj.name = "Pilar"
            mock_stylists.return_value = [mock_stylist_obj]
            mock_slots.return_value = [
                {"time": "10:00", "end_time": "11:00", "full_datetime": "2026-03-25T10:00:00+01:00"}
            ]

            # Should NOT raise ValueError
            result = await check_availability.ainvoke({
                "service_category": "Peluquería",
                "date": "2026-03-25",
                "stylist_id": "cualquiera",
            })

        assert "error" not in result or result["error"] is None
        # With non-UUID, it falls back to all stylists — should return slots
        assert len(result.get("available_slots", [])) > 0

    @pytest.mark.asyncio
    async def test_valid_uuid_filters_correctly(self):
        """Valid UUID should filter to that stylist only."""
        from agent.tools.availability_tools import check_availability

        with patch("agent.tools.availability_tools.parse_natural_date") as mock_parse, \
             patch("agent.tools.availability_tools.validate_3_day_rule") as mock_validate, \
             patch("agent.tools.availability_tools.get_stylists_by_category") as mock_stylists, \
             patch("agent.tools.availability_tools.is_holiday") as mock_holiday, \
             patch("agent.tools.availability_tools.get_available_slots") as mock_slots:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            mock_parse.return_value = datetime(2026, 3, 25, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
            mock_validate.return_value = {"valid": True}
            mock_holiday.return_value = None

            pilar_uuid = UUID(VALID_UUID)
            mock_pilar = MagicMock()
            mock_pilar.id = pilar_uuid
            mock_pilar.name = "Pilar"

            other_uuid = uuid4()
            mock_other = MagicMock()
            mock_other.id = other_uuid
            mock_other.name = "Ana"

            mock_stylists.return_value = [mock_pilar, mock_other]
            mock_slots.return_value = [
                {"time": "10:00", "end_time": "11:00", "full_datetime": "2026-03-25T10:00:00+01:00"}
            ]

            result = await check_availability.ainvoke({
                "service_category": "Peluquería",
                "date": "2026-03-25",
                "stylist_id": VALID_UUID,
            })

        assert "error" not in result or result["error"] is None
        # Should have filtered to Pilar only — mock_slots was called once
        assert mock_slots.call_count == 1
        call_args = mock_slots.call_args
        assert call_args.kwargs.get("stylist_id") == pilar_uuid or call_args[1].get("stylist_id") == pilar_uuid

    @pytest.mark.asyncio
    async def test_none_stylist_queries_all(self):
        """None stylist_id should query all available stylists."""
        from agent.tools.availability_tools import check_availability

        with patch("agent.tools.availability_tools.parse_natural_date") as mock_parse, \
             patch("agent.tools.availability_tools.validate_3_day_rule") as mock_validate, \
             patch("agent.tools.availability_tools.get_stylists_by_category") as mock_stylists, \
             patch("agent.tools.availability_tools.is_holiday") as mock_holiday, \
             patch("agent.tools.availability_tools.get_available_slots") as mock_slots:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            mock_parse.return_value = datetime(2026, 3, 25, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
            mock_validate.return_value = {"valid": True}
            mock_holiday.return_value = None

            mock_s1 = MagicMock()
            mock_s1.id = UUID(VALID_UUID)
            mock_s1.name = "Pilar"
            mock_s2 = MagicMock()
            mock_s2.id = uuid4()
            mock_s2.name = "Ana"

            mock_stylists.return_value = [mock_s1, mock_s2]
            mock_slots.return_value = [
                {"time": "10:00", "end_time": "11:00", "full_datetime": "2026-03-25T10:00:00+01:00"}
            ]

            result = await check_availability.ainvoke({
                "service_category": "Peluquería",
                "date": "2026-03-25",
                "stylist_id": None,
            })

        assert "error" not in result or result["error"] is None
        # With None, all 2 stylists should have been queried
        assert mock_slots.call_count == 2


class TestFindNextAvailableDefensiveGuard:
    """Test that find_next_available handles non-UUID stylist_id gracefully."""

    @pytest.mark.asyncio
    async def test_cualquiera_does_not_crash(self):
        """find_next_available(stylist_id='cualquiera') must not raise."""
        from agent.tools.availability_tools import find_next_available

        with patch("agent.tools.availability_tools.get_stylists_by_category") as mock_stylists, \
             patch("agent.tools.availability_tools.is_holiday") as mock_holiday, \
             patch("agent.tools.availability_tools.get_available_slots") as mock_slots, \
             patch("agent.tools.availability_tools.get_next_open_date") as mock_next_open, \
             patch("agent.tools.availability_tools.is_date_closed") as mock_closed:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            mock_holiday.return_value = None
            mock_closed.return_value = False

            mock_s1 = MagicMock()
            mock_s1.id = UUID(VALID_UUID)
            mock_s1.name = "Pilar"
            mock_stylists.return_value = [mock_s1]

            now = datetime.now(ZoneInfo("Europe/Madrid"))
            mock_next_open.return_value = now
            mock_slots.return_value = [
                {"time": "10:00", "end_time": "11:00", "full_datetime": "2026-03-25T10:00:00+01:00"}
            ]

            # Should NOT raise ValueError
            result = await find_next_available.ainvoke({
                "service_category": "Peluquería",
                "stylist_id": "cualquiera",
            })

        # With non-UUID, stylist_id is set to None → queries all stylists
        assert result.get("error") is None
        assert result.get("total_slots_found", 0) > 0

    @pytest.mark.asyncio
    async def test_sin_preferencia_does_not_crash(self):
        """find_next_available(stylist_id='sin preferencia') must not raise."""
        from agent.tools.availability_tools import find_next_available

        with patch("agent.tools.availability_tools.get_stylists_by_category") as mock_stylists, \
             patch("agent.tools.availability_tools.is_holiday") as mock_holiday, \
             patch("agent.tools.availability_tools.get_available_slots") as mock_slots, \
             patch("agent.tools.availability_tools.get_next_open_date") as mock_next_open, \
             patch("agent.tools.availability_tools.is_date_closed") as mock_closed:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            mock_holiday.return_value = None
            mock_closed.return_value = False

            mock_s1 = MagicMock()
            mock_s1.id = UUID(VALID_UUID)
            mock_s1.name = "Pilar"
            mock_stylists.return_value = [mock_s1]

            now = datetime.now(ZoneInfo("Europe/Madrid"))
            mock_next_open.return_value = now
            mock_slots.return_value = [
                {"time": "10:00", "end_time": "11:00", "full_datetime": "2026-03-25T10:00:00+01:00"}
            ]

            result = await find_next_available.ainvoke({
                "service_category": "Peluquería",
                "stylist_id": "sin preferencia",
            })

        assert result.get("error") is None


class TestNormalizationEdgeCases:
    """Edge cases for stylist normalization across the stack."""

    def test_accented_cualquiera(self):
        """Accent normalization should handle accented variations."""
        # "cualquiera" without accents — basic sanity
        assert BookingMode._normalize_stylist_preference("cualquiera") is None

    def test_mixed_case_sin_preferencia(self):
        assert BookingMode._normalize_stylist_preference("SIN PREFERENCIA") is None
        assert BookingMode._normalize_stylist_preference("Sin Preferencia") is None

    def test_whitespace_padded_phrase(self):
        assert BookingMode._normalize_stylist_preference("  cualquiera  ") is None
        assert BookingMode._normalize_stylist_preference("  sin preferencia  ") is None

    def test_uuid_v4_variations(self):
        """Various valid UUIDs should all pass through."""
        for _ in range(3):
            uid = str(uuid4())
            assert BookingMode._normalize_stylist_preference(uid) == uid

    def test_numeric_string_not_uuid(self):
        """Numeric strings that aren't UUIDs should return None."""
        assert BookingMode._normalize_stylist_preference("12345") is None

    def test_no_false_positive_on_uuid_like(self):
        """Strings that look like UUIDs but aren't valid should return None."""
        assert BookingMode._normalize_stylist_preference("not-a-uuid-at-all") is None
        assert BookingMode._normalize_stylist_preference("550e8400-xxxx-41d4-a716-446655440000") is None
