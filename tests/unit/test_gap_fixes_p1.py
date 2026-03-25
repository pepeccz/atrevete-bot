"""
Unit tests for P1 gap fixes: GAP-04, GAP-06, GAP-09/10.

GAP-04: stylist_id populated when user chooses stylist via _try_resolve_stylist_from_message
GAP-06: _detect_confirmation_exchange scans last 10 messages (not 4)
GAP-09/10: book() rejects __RESOLVE_FROM_SLOT__ sentinel and stale stylist_ids

All tests are pure unit tests — no DB or LLM calls required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.modes.base import ToolCallRejection
from agent.modes.booking_context import BookingContext
from agent.modes.booking_mode import (
    BookingMode,
    _detect_confirmation_exchange,
    _try_resolve_stylist_from_message,
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


def _make_state(messages: list[dict] | None = None) -> dict:
    state = create_initial_state("conv-001", "+34612345678")
    state["messages"] = messages or []
    return state


def _make_complete_ctx(**overrides) -> BookingContext:
    """BookingContext with all required fields for confirmation detection."""
    defaults = dict(
        service_id="svc-001",
        selected_services=["Corte de Dama"],
        stylist_id="stl-001",
        stylist_name="Ana",
        offered_slots=[
            {
                "stylist_id": "stl-001",
                "full_datetime": "2026-04-01T10:00:00+02:00",
                "time": "10:00",
                "stylist_name": "Ana",
            }
        ],
        customer_name="María",
        customer_id="cust-001",
    )
    defaults.update(overrides)
    return BookingContext(**defaults)


# =============================================================================
# GAP-04: _try_resolve_stylist_from_message
# =============================================================================


class TestGap04TryResolveStylistFromMessage:
    """GAP-04: stylist_id must be populated when the user picks a stylist by name."""

    def test_resolves_stylist_from_user_message(self):
        """User says 'quiero con Ana' → ctx.stylist_id and ctx.stylist_name are set."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-ana-001", "name": "Ana García", "next_slot_summary": "lunes 10:00"},
                {
                    "id": "uuid-pilar-002",
                    "name": "Pilar López",
                    "next_slot_summary": "martes 11:00",
                },
            ]
        )
        assert ctx.stylist_id is None

        _try_resolve_stylist_from_message("quiero con Ana", ctx)

        assert ctx.stylist_id == "uuid-ana-001"
        assert ctx.stylist_name == "Ana García"

    def test_resolves_second_stylist_by_name(self):
        """User says 'para Pilar' → resolves to the second stylist."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-ana-001", "name": "Ana García"},
                {"id": "uuid-pilar-002", "name": "Pilar López"},
            ]
        )

        _try_resolve_stylist_from_message("para Pilar", ctx)

        assert ctx.stylist_id == "uuid-pilar-002"
        assert ctx.stylist_name == "Pilar López"

    def test_accent_insensitive_matching(self):
        """Accents in stylist name or user message are normalized before matching."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-belen-003", "name": "Belén Ruiz"},
            ]
        )

        _try_resolve_stylist_from_message("quiero con Belen", ctx)

        assert ctx.stylist_id == "uuid-belen-003"

    def test_no_match_leaves_stylist_id_none(self):
        """User says something that doesn't match any stylist — ctx unchanged."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-ana-001", "name": "Ana García"},
            ]
        )

        _try_resolve_stylist_from_message("quiero un corte", ctx)

        assert ctx.stylist_id is None
        assert ctx.stylist_name is None

    def test_does_not_overwrite_existing_stylist_id(self):
        """If stylist_id is already set, function is a no-op."""
        ctx = BookingContext(
            stylist_id="uuid-existing",
            stylist_name="Otra",
            prefetched_stylists=[
                {"id": "uuid-ana-001", "name": "Ana García"},
            ],
        )

        _try_resolve_stylist_from_message("quiero con Ana", ctx)

        # Must NOT overwrite the existing stylist_id
        assert ctx.stylist_id == "uuid-existing"
        assert ctx.stylist_name == "Otra"

    def test_empty_message_is_noop(self):
        """Empty user message — no crash and no side effects."""
        ctx = BookingContext(prefetched_stylists=[{"id": "uuid-ana-001", "name": "Ana García"}])

        _try_resolve_stylist_from_message("", ctx)

        assert ctx.stylist_id is None

    def test_empty_prefetched_stylists_is_noop(self):
        """No prefetched stylists — function should not crash."""
        ctx = BookingContext(prefetched_stylists=[])

        _try_resolve_stylist_from_message("quiero con Ana", ctx)

        assert ctx.stylist_id is None

    def test_uses_stylist_id_key_as_fallback(self):
        """Handles 'stylist_id' key as fallback when 'id' is absent."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"stylist_id": "uuid-alt-001", "name": "Carmen Vega"},
            ]
        )

        _try_resolve_stylist_from_message("quiero con Carmen", ctx)

        assert ctx.stylist_id == "uuid-alt-001"

    def test_short_tokens_under_3_chars_not_matched(self):
        """Tokens shorter than 3 characters are skipped to avoid false positives."""
        ctx = BookingContext(
            prefetched_stylists=[
                {"id": "uuid-eva-001", "name": "Eva"},  # 3-char name — still matches
            ]
        )
        # "sí" = 2 chars, should not match
        _try_resolve_stylist_from_message("sí", ctx)
        # "Eva" has 3 chars — qualifies; but "sí" doesn't contain "eva"
        assert ctx.stylist_id is None

        # Now test that "Eva" does match with a proper message
        ctx2 = BookingContext(prefetched_stylists=[{"id": "uuid-eva-001", "name": "Eva"}])
        _try_resolve_stylist_from_message("quiero con Eva", ctx2)
        assert ctx2.stylist_id == "uuid-eva-001"


# =============================================================================
# GAP-06: _detect_confirmation_exchange scans last 10 messages
# =============================================================================


class TestGap06ConfirmationDetectionWindow:
    """GAP-06: confirmation detection must work when there are intermediate messages."""

    def test_detects_confirmation_in_last_4_messages(self):
        """Original narrow window still works — ensures no regression."""
        ctx = _make_complete_ctx()
        messages = [
            {"role": "assistant", "content": "Resumen de tu cita: Corte, Ana, lunes 10:00"},
            {"role": "user", "content": "sí, dale"},
        ]
        state = _make_state(messages)

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_detects_confirmation_with_5_intermediate_messages(self):
        """Confirmation detected even with 5 messages between summary and 'sí'."""
        ctx = _make_complete_ctx()
        messages = [
            {"role": "assistant", "content": "Resumen de tu cita: Corte, Ana, lunes 10:00"},
            {"role": "user", "content": "¿y si quiero para las 11?"},
            {"role": "assistant", "content": "A las 11 también hay disponibilidad con Ana."},
            {"role": "user", "content": "¿cuánto dura el corte?"},
            {"role": "assistant", "content": "El corte de dama dura unos 45 minutos."},
            {"role": "user", "content": "perfecto, confirmo"},
        ]
        state = _make_state(messages)

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_detects_confirmation_with_8_intermediate_messages(self):
        """Window of 10 handles up to 8 intermediate messages + summary + confirmation."""
        ctx = _make_complete_ctx()
        messages = [
            {"role": "user", "content": "hola"},  # extra early msg, outside window
            {"role": "assistant", "content": "Resumen de tu cita: datos de tu cita"},
            {"role": "user", "content": "pregunta 1"},
            {"role": "assistant", "content": "respuesta 1"},
            {"role": "user", "content": "pregunta 2"},
            {"role": "assistant", "content": "respuesta 2"},
            {"role": "user", "content": "pregunta 3"},
            {"role": "assistant", "content": "respuesta 3"},
            {"role": "user", "content": "pregunta 4"},
            {"role": "assistant", "content": "respuesta 4"},
            {"role": "user", "content": "ok dale"},
        ]
        state = _make_state(messages)

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True

    def test_summary_beyond_10_messages_not_detected(self):
        """Summary older than 10 messages is outside the window — not detected."""
        ctx = _make_complete_ctx()
        # Build messages where summary is at position -12 (outside window of 10)
        messages = (
            [{"role": "assistant", "content": "Resumen de tu cita: datos de tu cita"}]
            + [
                {"role": "user", "content": f"pregunta {i}"}
                for i in range(6)  # 6 user msgs
            ]
            + [
                {"role": "assistant", "content": f"respuesta {i}"}
                for i in range(6)  # 6 assistant msgs
            ]
            + [{"role": "user", "content": "sí"}]
        )
        # Total: 1 summary + 12 intermediate + 1 confirm = 14 messages
        # Summary is at index 0, confirmation at index 13 — gap of 12 (> 10)
        state = _make_state(messages)

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False

    def test_requires_data_complete_guard(self):
        """Confirmation exchange is ignored when booking data is incomplete."""
        # ctx without stylist_id — data incomplete
        ctx = BookingContext(
            service_id="svc-001",
            selected_services=["Corte de Dama"],
            stylist_id=None,  # Not set — data is NOT complete
            offered_slots=[{"stylist_id": "s1", "full_datetime": "2026-04-01T10:00:00+02:00"}],
            customer_name="María",
        )
        messages = [
            {"role": "assistant", "content": "Resumen de tu cita: Corte, lunes 10:00"},
            {"role": "user", "content": "sí"},
        ]
        state = _make_state(messages)

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is False

    def test_confirmation_already_shown_not_overwritten(self):
        """If confirmation_shown is already True, the detection is skipped at handle() level."""
        # Note: _detect_confirmation_exchange itself doesn't guard against this;
        # the guard is in handle() which only calls it when confirmation_shown is False.
        # Test that calling it again is idempotent (sets True twice = still True).
        ctx = _make_complete_ctx()
        ctx.confirmation_shown = True
        messages = [
            {"role": "assistant", "content": "Resumen de tu cita: datos de tu cita"},
            {"role": "user", "content": "sí"},
        ]
        state = _make_state(messages)

        _detect_confirmation_exchange(state, ctx)

        assert ctx.confirmation_shown is True  # Still True, no harm done


# =============================================================================
# GAP-09/10: book() rejects sentinel and stale stylist_id
# =============================================================================


class TestGap0910BookSentinelAndStaleStylistId:
    """GAP-09/10: book() gates for __RESOLVE_FROM_SLOT__ and stale stylist UUIDs."""

    def _make_full_ctx(self, offered_slots=None, stylist_id=None) -> BookingContext:
        return BookingContext(
            selected_services=["Corte de Dama"],
            customer_name="María",
            customer_id="cust-001",
            confirmation_shown=True,
            needs_availability_refresh=False,
            stylist_id=stylist_id,
            offered_slots=offered_slots
            or [
                {
                    "stylist_id": "uuid-real-stylist",
                    "full_datetime": "2026-04-01T10:00:00+02:00",
                    "time": "10:00",
                    "stylist_name": "Ana",
                }
            ],
        )

    @pytest.mark.asyncio
    async def test_sentinel_without_slot_index_is_rejected(self):
        """__RESOLVE_FROM_SLOT__ sentinel without slot_index → MISSING_SLOT_INDEX rejection."""
        mode = _make_mode()
        mode._ctx = self._make_full_ctx()

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "__RESOLVE_FROM_SLOT__",
            "start_time": "__RESOLVE_FROM_SLOT__",
            # slot_index is None (not provided)
        }

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "MISSING_SLOT_INDEX"
        assert "slot_index" in result.error_message

    @pytest.mark.asyncio
    async def test_stale_stylist_id_not_in_offered_slots_is_rejected(self):
        """Directly-passed stylist_id not in offered_slots → STALE_STYLIST_ID rejection."""
        mode = _make_mode()
        mode._ctx = self._make_full_ctx(
            offered_slots=[
                {
                    "stylist_id": "uuid-real-stylist",
                    "full_datetime": "2026-04-01T10:00:00+02:00",
                    "time": "10:00",
                    "stylist_name": "Ana",
                }
            ]
        )

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "uuid-STALE-from-history",  # Not in offered slots
            "start_time": "2026-04-01T10:00:00+02:00",
        }

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "STALE_STYLIST_ID"
        assert "uuid-STALE-from-history" in result.error_message

    @pytest.mark.asyncio
    async def test_slot_index_overrides_directly_passed_stylist_id(self):
        """When slot_index IS provided, it wins over any directly-passed stylist_id."""
        mode = _make_mode()
        offered = [
            {
                "stylist_id": "uuid-real-stylist",
                "full_datetime": "2026-04-01T10:00:00+02:00",
                "time": "10:00",
                "stylist_name": "Ana",
            }
        ]
        mode._ctx = self._make_full_ctx(offered_slots=offered)

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "uuid-SOME-OTHER-ID",  # Should be overwritten by slot_index resolution
            "start_time": "some-stale-time",
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", args)

        # slot_index resolved → dict (not a rejection), stylist_id overwritten
        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "uuid-real-stylist"
        assert result["start_time"] == "2026-04-01T10:00:00+02:00"
        assert "slot_index" not in result  # Removed after resolution

    @pytest.mark.asyncio
    async def test_valid_stylist_id_in_offered_slots_passes_through(self):
        """Directly-passed stylist_id that IS in offered_slots passes validation."""
        mode = _make_mode()
        offered = [
            {
                "stylist_id": "uuid-real-stylist",
                "full_datetime": "2026-04-01T10:00:00+02:00",
                "time": "10:00",
                "stylist_name": "Ana",
            }
        ]
        mode._ctx = self._make_full_ctx(offered_slots=offered)

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "uuid-real-stylist",  # Valid — IS in offered_slots
            "start_time": "2026-04-01T10:00:00+02:00",
        }

        result = await mode._pre_tool_call("book", args)

        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "uuid-real-stylist"

    @pytest.mark.asyncio
    async def test_sentinel_with_slot_index_is_resolved_not_rejected(self):
        """__RESOLVE_FROM_SLOT__ WITH slot_index → normal resolution, not rejection."""
        mode = _make_mode()
        offered = [
            {
                "stylist_id": "uuid-real-stylist",
                "full_datetime": "2026-04-01T10:00:00+02:00",
                "time": "10:00",
                "stylist_name": "Ana",
            }
        ]
        mode._ctx = self._make_full_ctx(offered_slots=offered)

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "__RESOLVE_FROM_SLOT__",
            "start_time": "__RESOLVE_FROM_SLOT__",
            "slot_index": 1,
        }

        result = await mode._pre_tool_call("book", args)

        assert not isinstance(result, ToolCallRejection)
        assert result["stylist_id"] == "uuid-real-stylist"
        assert result["start_time"] == "2026-04-01T10:00:00+02:00"

    @pytest.mark.asyncio
    async def test_no_offered_slots_skips_stale_id_validation(self):
        """When offered_slots is None, the stale stylist_id gate is skipped (no DB to validate against)."""
        mode = _make_mode()
        # No offered slots means we can't validate — pass through and let other gates handle it
        mode._ctx = BookingContext(
            selected_services=["Corte de Dama"],
            customer_name="María",
            customer_id="cust-001",
            confirmation_shown=True,
            needs_availability_refresh=False,
            offered_slots=None,  # No slots
        )

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "some-uuid-without-slots",
            "start_time": "2026-04-01T10:00:00+02:00",
        }

        # The NO_OFFERED_SLOTS guard fires BEFORE the stale-id check
        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_OFFERED_SLOTS"

    @pytest.mark.asyncio
    async def test_sentinel_still_present_raises_clear_error_not_invalid_uuid(self):
        """__RESOLVE_FROM_SLOT__ without slot_index gives MISSING_SLOT_INDEX, not INVALID_UUID.

        This is the exact scenario from GAP-10: previously the sentinel would pass
        BookSchema validation, reach book() body, and fail with INVALID_UUID because
        UUID('__RESOLVE_FROM_SLOT__') raises ValueError.
        Now _pre_tool_call intercepts it with a clear, actionable error.
        """
        mode = _make_mode()
        offered = [
            {
                "stylist_id": "uuid-real-stylist",
                "full_datetime": "2026-04-01T10:00:00+02:00",
                "time": "10:00",
                "stylist_name": "Ana",
            }
        ]
        mode._ctx = self._make_full_ctx(offered_slots=offered)

        args = {
            "customer_id": "cust-001",
            "services": ["Corte de Dama"],
            "stylist_id": "__RESOLVE_FROM_SLOT__",
            "start_time": "2026-04-01T10:00:00+02:00",
            # No slot_index
        }

        result = await mode._pre_tool_call("book", args)

        assert isinstance(result, ToolCallRejection)
        # Must be MISSING_SLOT_INDEX, NOT INVALID_UUID (which would be the book() body error)
        assert result.error_code == "MISSING_SLOT_INDEX"
        assert result.error_code != "INVALID_UUID"
