"""Unit tests for booking-confirmation-message-fix.

Covers:
- format_service_list() — Spanish grammar for service name lists
- confirmed_services lifecycle: field creation, reset_transient exclusion, serialization
- extract_booking_result() — populating confirmed_services from various result shapes
- _build_response() — confirmation message includes all confirmed services

No DB, no LLM — all external dependencies are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context import BookingContext, format_service_list
from agent.modes.tool_extractors import extract_booking_result

# =============================================================================
# Helpers
# =============================================================================


def make_booking_mode():
    """Create a BookingMode with a mocked LLM (no real calls)."""
    from agent.modes.booking_mode import BookingMode

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)
    return BookingMode(tools=[], llm_client=mock_llm)


def make_state(mode_context: dict | None = None) -> dict:
    """Minimal ConversationState for _build_response tests."""
    from agent.state.schemas import create_initial_state

    state = create_initial_state("conv-test", "+34600000000")
    state["customer_name"] = "Ana"
    state["customer_id"] = "cust-001"
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"
    state["mode_context"] = mode_context or {}
    state["messages"] = [{"role": "user", "content": "quiero reservar"}]
    return state


# =============================================================================
# format_service_list
# =============================================================================


class TestFormatServiceList:
    def test_format_empty_list(self):
        """Empty list returns empty string."""
        assert format_service_list([]) == ""

    def test_format_single_service(self):
        """Single service returns the service name as-is."""
        assert format_service_list(["Corte Caballero"]) == "Corte Caballero"

    def test_format_two_services(self):
        """Two services joined with 'y' (no comma)."""
        result = format_service_list(["Corte Caballero", "Corte Niño"])
        assert result == "Corte Caballero y Corte Niño"

    def test_format_three_services(self):
        """Three services: comma-separated with 'y' before last."""
        result = format_service_list(["A", "B", "C"])
        assert result == "A, B y C"

    def test_format_four_services(self):
        """Four services: comma-separated with 'y' before last."""
        result = format_service_list(["A", "B", "C", "D"])
        assert result == "A, B, C y D"


# =============================================================================
# confirmed_services lifecycle
# =============================================================================


class TestConfirmedServicesLifecycle:
    def test_confirmed_services_survives_reset_transient(self):
        """reset_transient() clears draft fields but preserves confirmed_services (SC-5)."""
        ctx = BookingContext(
            selected_services=["svc-1"],
            service_name="Corte Caballero",
        )
        ctx.confirmed_services = ["Corte Caballero"]

        ctx.reset_transient()

        # Draft field cleared
        assert ctx.selected_services == []
        # Post-booking metadata preserved
        assert ctx.confirmed_services == ["Corte Caballero"]

    def test_confirmed_services_roundtrips_serialization(self):
        """to_mode_context() → from_mode_context() preserves confirmed_services (SC-3)."""
        ctx = BookingContext(service_name="Corte Caballero")
        ctx.confirmed_services = ["Corte Caballero", "Corte Niño"]

        serialized = ctx.to_mode_context()
        restored = BookingContext.from_mode_context(serialized)

        assert restored.confirmed_services == ["Corte Caballero", "Corte Niño"]

    def test_confirmed_services_default_is_empty_list(self):
        """Default value is empty list, not None."""
        ctx = BookingContext()
        assert ctx.confirmed_services == []
        assert isinstance(ctx.confirmed_services, list)


# =============================================================================
# extract_booking_result — populating confirmed_services
# =============================================================================


class TestExtractBookingResultConfirmedServices:
    def _make_success_result(self, **extra) -> dict:
        return {
            "success": True,
            "appointment_id": "appt-001",
            "stylist_id": "sty-001",
            **extra,
        }

    def test_extract_multi_service_from_service_names(self):
        """service_names string 'A, B' → confirmed_services ['A', 'B'] (SC-4)."""
        ctx = BookingContext(service_name="A", stylist_name="Ana", stylist_id="sty-001")
        result = self._make_success_result(service_names="Corte Caballero, Corte Niño")

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == ["Corte Caballero", "Corte Niño"]

    def test_extract_single_service_from_service_name_fallback(self):
        """No service_names → falls back to service_name on ctx."""
        ctx = BookingContext(
            service_name="Corte Caballero", stylist_name="Ana", stylist_id="sty-001"
        )
        result = self._make_success_result()  # no service_names key

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == ["Corte Caballero"]

    def test_extract_from_services_list_priority(self):
        """result['service_names'] as a list is assigned directly."""
        ctx = BookingContext(service_name="A", stylist_name="Ana", stylist_id="sty-001")
        result = self._make_success_result(service_names=["A", "B", "C"])

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == ["A", "B", "C"]

    # --- REQ-4: structured services list takes priority over service_names string ---

    def test_extract_services_list_takes_priority_over_service_names(self):
        """REQ-4: result['services'] list is used first, ignoring service_names (SC-4b)."""
        ctx = BookingContext(service_name="A", stylist_name="Ana", stylist_id="sty-001")
        # Both keys present — 'services' must win
        result = self._make_success_result(
            services=["Corte Caballero", "Tinte Raíz"],
            service_names="ShouldBeIgnored, AnotherIgnored",
        )

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == ["Corte Caballero", "Tinte Raíz"]

    def test_extract_services_list_empty_falls_back_to_service_names(self):
        """REQ-4: empty services list falls back to service_names string (SC-4b)."""
        ctx = BookingContext(service_name="A", stylist_name="Ana", stylist_id="sty-001")
        result = self._make_success_result(
            services=[],  # empty list — skip to next priority
            service_names="Corte Caballero, Corte Niño",
        )

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == ["Corte Caballero", "Corte Niño"]

    def test_extract_service_names_empty_string_no_exception(self):
        """REQ-4: service_names='' with no services list falls back to service_name (SC-4b)."""
        ctx = BookingContext(
            service_name="Corte Caballero", stylist_name="Ana", stylist_id="sty-001"
        )
        result = self._make_success_result(service_names="")  # empty string, falsy

        extract_booking_result(result, ctx)

        # Empty service_names should fall through to service_name
        assert ctx.confirmed_services == ["Corte Caballero"]
        assert isinstance(ctx.confirmed_services, list)

    def test_extract_service_names_none_no_exception(self):
        """REQ-4: service_names=None with no services list falls back gracefully (SC-4b)."""
        ctx = BookingContext(service_name="Corte Dama", stylist_name="Ana", stylist_id="sty-001")
        result = self._make_success_result(service_names=None)  # explicit None

        extract_booking_result(result, ctx)

        # None service_names should fall through to service_name
        assert ctx.confirmed_services == ["Corte Dama"]
        assert isinstance(ctx.confirmed_services, list)

    def test_extract_all_empty_returns_empty_list_no_exception(self):
        """REQ-4: all service sources empty → [] without raising (SC-4b)."""
        ctx = BookingContext(stylist_name="Ana", stylist_id="sty-001")
        # No services, no service_names, no service_name
        result = self._make_success_result(services=None, service_names=None)

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == []

    def test_extract_no_service_fields_no_exception(self):
        """No service_names, no service_name → confirmed_services is [] — no exception (SC-4b)."""
        ctx = BookingContext(stylist_name="Ana", stylist_id="sty-001")
        # ctx.service_name is None, result has no service_names
        result = self._make_success_result()

        extract_booking_result(result, ctx)

        assert ctx.confirmed_services == []

    def test_confirmed_services_set_before_reset_transient(self):
        """confirmed_services is populated and survives reset_transient call within extractor."""
        ctx = BookingContext(
            service_name="Corte Dama",
            stylist_name="Ana",
            stylist_id="sty-001",
            selected_services=["Corte Dama"],
        )
        result = self._make_success_result(service_names="Corte Dama, Tinte Raíz")

        extract_booking_result(result, ctx)

        # selected_services cleared by reset_transient
        assert ctx.selected_services == []
        # confirmed_services survives
        assert ctx.confirmed_services == ["Corte Dama", "Tinte Raíz"]


# =============================================================================
# _build_response — confirmation message includes all services
# =============================================================================


class TestBuildResponseConfirmationMessage:
    def _make_completed_ctx(
        self,
        confirmed_services: list[str],
        service_name: str | None = None,
        selected_services: list[str] | None = None,
    ) -> BookingContext:
        ctx = BookingContext(
            stylist_name="Ana",
            stylist_id="sty-001",
            service_name=service_name,
            # selected_services defaults to confirmed_services when not supplied —
            # in a real booking selected_services is always populated and must match
            # confirmed_services for the Bug C guard to allow format_service_list().
            selected_services=(
                selected_services if selected_services is not None else list(confirmed_services)
            ),
            last_booked_slot={"date": "lunes 25 de marzo", "time": "10:00"},
            customer_name="María",
            customer_id="cust-001",
        )
        ctx.confirmed_services = confirmed_services
        ctx._booking_completed = True
        return ctx

    def test_confirmation_message_includes_all_services(self):
        """confirmed_services=['Corte Caballero','Corte Niño'] → message has 'Corte Caballero y Corte Niño' (SC-1).

        Bug C guard: selected_services mirrors confirmed_services (genuine multi-service booking)
        so both are shown.
        """
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx(
            confirmed_services=["Corte Caballero", "Corte Niño"],
            # selected_services defaults to confirmed_services (genuine 2-service booking)
        )
        llm_result = AgenticLoopResult(
            response_text="Cita confirmada.",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        assert messages, "Expected messages in state updates"
        response_text = messages[0]["content"]

        assert "Corte Caballero y Corte Niño" in response_text

    def test_confirmation_message_single_service_no_regression(self):
        """Single confirmed service renders without 'y' connector (SC-2 no regression)."""
        mode = make_booking_mode()
        state = make_state()
        ctx = self._make_completed_ctx(
            confirmed_services=["Corte Caballero"],
        )
        llm_result = AgenticLoopResult(
            response_text="Cita confirmada.",
            tool_results={},
        )

        with (
            patch("agent.modes.booking_mode.get_system_prompt", return_value=""),
            patch("agent.modes.booking_mode.load_markdown", return_value=""),
        ):
            updates = mode._build_response(state, ctx, llm_result)

        messages = updates.get("messages", [])
        response_text = messages[0]["content"]

        assert "Corte Caballero" in response_text
        assert " y " not in response_text.split("✂️")[-1].split("\n")[0]
