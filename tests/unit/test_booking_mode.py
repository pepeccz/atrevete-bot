"""
Unit tests for agent/modes/booking_mode.py — BookingMode v6.0.

Coverage:
- Sub-step initial state: no booking_step → defaults to "service_selection"
- Cancel at any step → transitions to GENERAL
- Cancel at early (service_selection) step → direct GENERAL transition
- Escalate intent at any step → transitions to ESCALATION
- BookingMode mode_name property
- _advance_step: step advancement rules (T-008)
- AgenticLoopResult integration (T-006/T-007)

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_context import BookingSubstep
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
from agent.state.helpers import add_message
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "book", confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint="BOOKING")


def make_mock_llm(response_text: str = "¿Qué servicio deseas?") -> AsyncMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []  # No tool calls → final response
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_booking_mode(llm_response: str = "¿Qué servicio deseas?") -> BookingMode:
    mock_llm = make_mock_llm(llm_response)
    return BookingMode(tools=[], llm_client=mock_llm)


def make_state_with_step(
    booking_step: str | None = None,
    customer_name: str | None = "Juan",
    customer_id: str | None = "cust-123",
) -> dict:
    """Build a ConversationState with optional booking_step in mode_context."""
    state = create_initial_state("conv-001", "+34612345678")
    state["customer_name"] = customer_name
    state["customer_id"] = customer_id
    state["is_first_interaction"] = False
    state["current_mode"] = "BOOKING"

    if booking_step is not None:
        state["mode_context"] = {"booking_step": booking_step}
    else:
        state["mode_context"] = {}  # No step set — defaults to service_selection

    return state


# =============================================================================
# mode_name
# =============================================================================


class TestBookingModeName:
    def test_mode_name_is_booking(self):
        mode = make_booking_mode()
        assert mode.mode_name == "BOOKING"


# =============================================================================
# Initial booking step
# =============================================================================


class TestBookingModeInitialStep:
    """Tests for the initial state when entering BOOKING mode."""

    async def test_no_booking_step_defaults_to_service_selection(self):
        """
        When mode_context has no booking_step, the mode should enter
        service_selection (the first step).
        """
        mode = make_booking_mode()
        state = make_state_with_step(booking_step=None)

        result = await mode.handle(state, make_intent())

        # The result should set/maintain booking_step as service_selection
        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "service_selection"

    async def test_no_booking_step_generates_message(self):
        """First step should produce a response asking about the service."""
        mode = make_booking_mode("¿Qué servicio te gustaría hoy?")
        state = make_state_with_step(booking_step=None)

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1

    async def test_explicit_service_selection_step_handled(self):
        """Explicit service_selection step should work the same as implicit."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        # Should still be in service_selection step
        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "service_selection"


# =============================================================================
# Cancel at any step
# =============================================================================


class TestBookingModeCancel:
    """Tests for cancel intent at various booking steps."""

    async def test_cancel_at_service_selection_transitions_to_general(self):
        """At the very first step, cancel goes directly to GENERAL (no confirmation needed)."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("cancel"))

        assert result.get("current_mode") == "GENERAL"

    async def test_cancel_at_service_selection_no_confirmation_needed(self):
        """At first step, cancel should NOT ask for confirmation."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("cancel"))

        messages = result.get("messages", [])
        combined = " ".join(m.get("content", "") for m in messages)
        assert "¿Seguro" not in combined  # No confirmation dialog at first step

    async def test_reject_at_service_selection_transitions_to_general(self):
        """reject at first step is treated like cancel — go to GENERAL."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("reject"))

        assert result.get("current_mode") == "GENERAL"

    async def test_cancel_intent_at_mid_step_goes_to_general(self):
        """
        The 'cancel' intent at ANY non-first step goes directly to GENERAL.
        Per implementation: `if pending_cancel or intent.intent == "cancel": → GENERAL`
        Only 'reject' triggers the confirmation dialog.
        """
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")

        result = await mode.handle(state, make_intent("cancel"))

        assert result.get("current_mode") == "GENERAL"

    async def test_reject_at_mid_step_asks_confirmation(self):
        """Reject (not cancel) at a non-initial step asks the user to confirm cancellation."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")

        result = await mode.handle(state, make_intent("reject"))

        messages = result.get("messages", [])
        combined = " ".join(m.get("content", "") for m in messages)
        assert "¿Seguro" in combined

    async def test_reject_at_mid_step_sets_pending_cancel(self):
        """Reject at non-initial step should set pending_cancel=True in mode_context."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")

        result = await mode.handle(state, make_intent("reject"))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("pending_cancel") is True

    async def test_cancel_intent_at_slot_selection_goes_to_general(self):
        """Cancel intent during slot selection goes straight to GENERAL (no confirmation)."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="slot_selection")

        result = await mode.handle(state, make_intent("cancel"))

        # cancel intent always goes directly to GENERAL
        assert result.get("current_mode") == "GENERAL"

    async def test_confirmed_cancel_clears_mode_and_transitions_to_general(self):
        """When pending_cancel is True AND user sends cancel → go to GENERAL."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="customer_data")
        state["mode_context"]["pending_cancel"] = True

        result = await mode.handle(state, make_intent("reject"))

        assert result.get("current_mode") == "GENERAL"


# =============================================================================
# Escalate at any step
# =============================================================================


class TestBookingModeEscalate:
    """Tests for escalate intent at various booking steps."""

    async def test_escalate_at_service_selection_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent("escalate"))

        assert result.get("current_mode") == "ESCALATION"

    async def test_escalate_at_confirmation_step_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="confirmation")
        state["mode_context"].update({
            "service_name": "Corte",
            "stylist_name": "Laura",
            "slot_time": "10:00",
            "slot_date": "2026-03-10",
            "booking_first_name": "Juan",
        })

        result = await mode.handle(state, make_intent("escalate"))

        assert result.get("current_mode") == "ESCALATION"

    async def test_escalate_at_mid_booking_transitions_to_escalation(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["mode_context"]["service_name"] = "Tinte"

        result = await mode.handle(state, make_intent("escalate"))

        assert result.get("current_mode") == "ESCALATION"


# =============================================================================
# Sub-step: service_selection
# =============================================================================


class TestBookingModeServiceSelection:
    """Tests for the service_selection sub-step."""

    async def test_service_selection_returns_message(self):
        mode = make_booking_mode("¿Qué servicio te gustaría?")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1

    async def test_service_selection_message_is_assistant_role(self):
        mode = make_booking_mode("¿Qué servicio?")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert messages[0]["role"] == "assistant"

    async def test_service_selection_appends_recommendations_when_available(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="service_selection")

        with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), patch.object(
            mode,
            "_run_agentic_loop",
            new=AsyncMock(
                return_value=AgenticLoopResult(
                    response_text="Perfecto, ya tengo tu servicio.",
                    tool_results={
                        "search_services": {
                            "resolved_service": {
                                "id": "svc-1",
                                "name": "Cortar",
                                "category": "Peluquería",
                                "duration_minutes": 45,
                                "family": "haircut",
                                "combo_recommendations": ["Peinado", "Barro"],
                            }
                        }
                    },
                )
            ),
        ):
            result = await mode.handle(state, make_intent())

        message = result["messages"][0]["content"]
        assert "Perfecto, ya tengo tu servicio." in message
        assert result["mode_context"]["booking_step"] == "add_ons"
        assert result["mode_context"]["pending_recommendations"] == ["Peinado", "Barro"]
        assert result["mode_context"]["recommendations_shown"] is False
        assert result["mode_context"]["selected_services"] == ["Cortar"]


# =============================================================================
# Confirmation step
# =============================================================================


class TestBookingModeConfirmation:
    """Tests for the confirmation step."""

    def _make_state_at_confirmation(self) -> dict:
        state = make_state_with_step(booking_step="confirmation")
        state["mode_context"].update({
            "service_name": "Corte de señora",
            "stylist_name": "Laura",
            "slot_time": "10:00",
            "slot_date": "2026-03-10",
            "booking_first_name": "Juan",
            "booking_last_name": "García",
            "booking_notes": None,
        })
        return state

    async def test_confirm_intent_advances_to_completed(self):
        """confirm intent at confirmation step → booking_step=completed."""
        mode = make_booking_mode()
        state = self._make_state_at_confirmation()

        result = await mode.handle(state, make_intent("confirm"))

        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "completed"

    async def test_non_confirm_at_confirmation_shows_summary(self):
        """Non-confirm intent at confirmation currently raises invalid self-transition."""
        mode = make_booking_mode("¿Confirmas la reserva?")
        state = self._make_state_at_confirmation()

        with pytest.raises(ValueError, match="Invalid booking transition: confirmation -> confirmation"):
            await mode.handle(state, make_intent("book"))


class TestBookingModePolishBehaviors:
    async def test_volver_rewinds_one_step_and_preserves_prior_data(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="slot_selection")
        state["user_message"] = "volver"
        state["mode_context"].update(
            {
                "service_id": "svc-1",
                "service_name": "Cortar",
                "stylist_id": "sty-1",
                "stylist_name": "María",
                "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
                "slot_summary": "20/03 10:00",
            }
        )

        result = await mode.handle(state, make_intent())

        assert result["mode_context"]["booking_step"] == "stylist_selection"
        assert result["mode_context"]["service_name"] == "Cortar"
        assert "selected_slot" not in result["mode_context"]

    async def test_change_service_resets_dependent_context(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "mejor quiero peinado"
        state["mode_context"].update(
            {
                "service_id": "svc-1",
                "service_name": "Cortar",
                "stylist_id": "sty-1",
                "stylist_name": "María",
            }
        )

        result = await mode.handle(state, make_intent())

        assert result["mode_context"]["booking_step"] == "service_selection"
        assert result["mode_context"].get("selected_services") == []
        assert "stylist_id" not in result["mode_context"]

    async def test_slot_selection_captures_requested_range_preferences(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="slot_selection")
        state["user_message"] = "mañana por la tarde"
        state["mode_context"].update(
            {
                "service_id": "svc-1",
                "service_name": "Cortar",
                "service_category": "Peluquería",
                "stylist_id": "sty-1",
                "stylist_name": "María",
            }
        )

        with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), patch.object(
            mode,
            "_run_agentic_loop",
            new=AsyncMock(return_value=AgenticLoopResult(response_text="Te muestro horarios.", tool_results={})),
        ):
            result = await mode.handle(state, make_intent())

        assert result["mode_context"]["availability_start_date"] == "manana"
        assert result["mode_context"]["availability_time_range"] == "afternoon"

    async def test_populate_recurrent_stylist_from_customer_history(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["customer_id"] = "cust-123"
        context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 45,
        }

        stylist = MagicMock()
        stylist.id = "sty-9"
        stylist.name = "Lucía"

        history_tool = MagicMock()
        history_tool.ainvoke = AsyncMock(return_value={
            "appointments": [
                {"stylist_id": "sty-9"},
                {"stylist_id": "sty-9"},
            ]
        })
        availability_tool = MagicMock()
        availability_tool.ainvoke = AsyncMock(return_value={
            "selected_stylist_slots": [
                {"day_name": "mañana", "time": "10:30"},
            ]
        })

        with patch("agent.tools.customer_tools.get_customer_history", new=history_tool), patch(
            "agent.services.availability_service.get_stylist_by_id", new=AsyncMock(return_value=stylist)
        ), patch("agent.tools.availability_tools.find_next_available", new=availability_tool):
            updated = await mode._populate_recurrent_stylist(state, context)

        assert updated["recurrent_stylist_id"] == "sty-9"
        assert updated["recurrent_stylist_name"] == "Lucía"
        assert "10:30" in updated["recurrent_stylist_slot_summary"]


# =============================================================================
# _advance_step unit tests (T-008)
# =============================================================================


class TestAdvanceStep:
    """
    Direct unit tests for BookingMode._advance_step().

    These tests verify the step-advancement logic in isolation without
    calling handle() — they call _advance_step() directly.
    """

    def make_mode(self) -> BookingMode:
        return make_booking_mode()

    def make_result(
        self,
        response_text: str = "OK",
        tool_results: dict | None = None,
    ) -> AgenticLoopResult:
        return AgenticLoopResult(
            response_text=response_text,
            tool_results=tool_results or {},
        )

    # ── service_selection ──────────────────────────────────────────────────────

    def test_service_selection_stays_when_no_tool_results(self):
        """No tools called → stay at service_selection."""
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        next_step, ctx = mode._advance_step(result, "service_selection", {})
        assert next_step == "service_selection"

    def test_service_selection_stays_when_tool_called_but_no_service_name(self):
        """search_services called but service_name not yet in context → stay."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"search_services": []})
        next_step, ctx = mode._advance_step(result, "service_selection", {})
        assert next_step == "service_selection"

    def test_service_selection_advances_when_search_services_returns_result(self):
        """search_services called AND service_name in context → advance."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"search_services": []})
        ctx = {"service_name": "Corte señora"}
        next_step, updated_ctx = mode._advance_step(result, "service_selection", ctx)
        assert next_step == "add_ons"

    def test_service_selection_advances_with_query_info(self):
        """query_info called AND service_name in context → advance."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"query_info": {}})
        ctx = {"service_name": "Tinte"}
        next_step, _ = mode._advance_step(result, "service_selection", ctx)
        assert next_step == "add_ons"

    def test_service_selection_single_match_auto_populates_context(self):
        """search_services returning single result auto-populates service_name."""
        mode = self.make_mode()
        services = [{"id": "svc-1", "name": "Corte señora", "category": "Peluquería"}]
        result = self.make_result(tool_results={"search_services": services})
        # service_name not yet in context — but single match should populate it
        next_step, ctx = mode._advance_step(result, "service_selection", {})
        # Single match → service_name auto-set → advance
        assert ctx["service_name"] == "Corte señora"
        assert ctx["service_id"] == "svc-1"
        assert ctx["service_category"] == "Peluquería"
        assert next_step == "add_ons"

    # ── stylist_selection ──────────────────────────────────────────────────────

    def test_stylist_selection_stays_when_no_list_stylists(self):
        """No list_stylists call → stay at stylist_selection."""
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        next_step, _ = mode._advance_step(result, "stylist_selection", {"service_name": "Corte"})
        assert next_step == "stylist_selection"

    def test_stylist_selection_stays_when_no_stylist_id_in_context(self):
        """list_stylists called but stylist_id not in context → stay."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"list_stylists": []})
        next_step, _ = mode._advance_step(result, "stylist_selection", {})
        assert next_step == "stylist_selection"

    def test_stylist_selection_advances_when_stylist_chosen(self):
        """list_stylists called AND stylist_id in context → advance."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"list_stylists": []})
        ctx = {"stylist_id": "stl-1"}
        next_step, _ = mode._advance_step(result, "stylist_selection", ctx)
        assert next_step == "slot_selection"

    def test_stylist_selection_single_match_auto_populates_context(self):
        """list_stylists returning single result auto-populates stylist_id."""
        mode = self.make_mode()
        stylists = [{"id": "stl-1", "name": "Laura"}]
        result = self.make_result(tool_results={"list_stylists": stylists})
        next_step, ctx = mode._advance_step(result, "stylist_selection", {})
        assert ctx["stylist_id"] == "stl-1"
        assert ctx["stylist_name"] == "Laura"
        assert next_step == "slot_selection"

    # ── notes / legacy customer_data alias ────────────────────────────────────

    def test_customer_data_alias_stays_at_notes_without_turn_input(self):
        """Legacy customer_data alias resolves to notes and stays without user reply."""
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        next_step, _ = mode._advance_step(result, "customer_data", {})
        assert next_step == "notes"

    def test_customer_data_alias_ignores_first_name_for_advancement(self):
        """Notes step no longer advances based on first_name presence alone."""
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        ctx = {"first_name": "Juan"}
        next_step, _ = mode._advance_step(result, "customer_data", ctx)
        assert next_step == "notes"

    def test_customer_data_alias_ignores_booking_first_name_for_advancement(self):
        """Legacy booking_first_name no longer controls booking progression."""
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        ctx = {"booking_first_name": "María"}
        next_step, _ = mode._advance_step(result, "customer_data", ctx)
        assert next_step == "notes"

    # ── confirmation ──────────────────────────────────────────────────────────

    def test_confirmation_intent_confirm_advances_via_step_confirmation(self):
        """
        confirmation + intent=confirm is handled by _step_confirmation returning a
        dict directly (not AgenticLoopResult), so _advance_step is never called.
        This test verifies _advance_step stays at confirmation when reached via
        AgenticLoopResult path (non-confirm).
        """
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        with pytest.raises(ValueError, match="Invalid booking transition: confirmation -> confirmation"):
            mode._advance_step(result, "confirmation", {})

    # ── completed ─────────────────────────────────────────────────────────────

    def test_completed_stays_completed(self):
        """completed step always returns completed."""
        mode = self.make_mode()
        result = self.make_result(tool_results={})
        next_step, _ = mode._advance_step(result, "completed", {})
        assert next_step == "completed"

    # ── unknown step ──────────────────────────────────────────────────────────

    def test_unknown_step_stays_at_current(self):
        """Unrecognized step names now raise a validation error."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"some_tool": {}})
        with pytest.raises(ValueError, match="Invalid booking substep"):
            mode._advance_step(result, "unknown_step", {})


class TestInterpretSlotToolResults:
    def test_find_next_available_with_substitution_populates_semantic_fields(self):
        mode = make_booking_mode()

        interpretation = mode._interpret_slot_tool_results(
            {
                "find_next_available": {
                    "selected_stylist_slots": [
                        {
                            "date": "2026-03-22",
                            "time": "10:00",
                            "full_datetime": "2026-03-22T10:00:00+01:00",
                        }
                    ],
                    "selected_stylist_name": "María",
                    "substitution_made": True,
                    "substitution_reason": "minimum_days_rule",
                    "date_requested": "2026-03-19",
                    "date_substituted": "2026-03-22",
                    "min_valid_date": "2026-03-22",
                }
            },
            {"stylist_id": "sty-1"},
        )

        assert interpretation["has_slots"] is True
        assert interpretation["substitution_made"] is True
        assert interpretation["substitution_reason"] == "minimum_days_rule"
        assert interpretation["date_requested"] == date(2026, 3, 19)
        assert interpretation["date_substituted"] == date(2026, 3, 22)
        assert interpretation["min_valid_date"] == date(2026, 3, 22)
        assert interpretation["stylist_name"] == "María"
        assert interpretation["available_slots"][0]["time"] == "10:00"

    def test_check_availability_date_too_soon_interprets_semantic_fields(self):
        mode = make_booking_mode()

        interpretation = mode._interpret_slot_tool_results(
            {
                "check_availability": {
                    "available_slots": [],
                    "date_too_soon": True,
                    "date_requested": "2026-03-19",
                    "min_valid_date": "2026-03-22",
                }
            },
            {"stylist_id": "sty-1"},
        )

        assert interpretation["has_slots"] is False
        assert interpretation["substitution_made"] is True
        assert interpretation["substitution_reason"] == "minimum_days_rule"
        assert interpretation["date_requested"] == date(2026, 3, 19)
        assert interpretation["min_valid_date"] == date(2026, 3, 22)
        assert interpretation["no_slots_for_chosen_stylist"] is True

    def test_interpret_distinguishes_chosen_stylist_exhaustion_from_global_exhaustion(self):
        mode = make_booking_mode()

        chosen_interpretation = mode._interpret_slot_tool_results(
            {
                "find_next_available": {
                    "selected_stylist_slots": [],
                    "soonest_any": {
                        "date": "2026-03-25",
                        "time": "11:00",
                        "stylist_id": "sty-2",
                        "is_different_stylist": True,
                    },
                }
            },
            {"stylist_id": "sty-1"},
        )
        any_interpretation = mode._interpret_slot_tool_results(
            {"find_next_available": {"available_dates": []}},
            {},
        )

        assert chosen_interpretation["has_slots"] is False
        assert chosen_interpretation["no_slots_for_chosen_stylist"] is True
        assert chosen_interpretation["no_slots_for_any_stylist"] is False

        assert any_interpretation["has_slots"] is False
        assert any_interpretation["no_slots_for_chosen_stylist"] is False
        assert any_interpretation["no_slots_for_any_stylist"] is True

    def test_interpret_handles_empty_malformed_and_legacy_payloads_safely(self):
        mode = make_booking_mode()

        empty_interpretation = mode._interpret_slot_tool_results({}, {})
        malformed_interpretation = mode._interpret_slot_tool_results(
            {"find_next_available": "oops"},
            {},
        )
        legacy_interpretation = mode._interpret_slot_tool_results(
            {
                "find_next_available": [
                    {
                        "start_time": "2026-03-22T10:00:00+01:00",
                        "stylist_id": "sty-1",
                    }
                ]
            },
            {"stylist_id": "sty-1"},
        )

        assert empty_interpretation["has_slots"] is False
        assert empty_interpretation["available_slots"] is None
        assert malformed_interpretation["has_slots"] is False
        assert malformed_interpretation["substitution_made"] is False
        assert legacy_interpretation["has_slots"] is True
        assert legacy_interpretation["available_slots"][0]["start_time"] == "2026-03-22T10:00:00+01:00"


class TestAdvanceStepSlotSelection:
    def make_mode(self) -> BookingMode:
        return make_booking_mode()

    def make_result(self, tool_results: dict | None = None) -> AgenticLoopResult:
        return AgenticLoopResult(response_text="OK", tool_results=tool_results or {})

    def test_slot_selection_uses_slot_interpretation_instead_of_raw_payload(self):
        mode = self.make_mode()
        result = self.make_result(
            tool_results={
                "check_availability": {
                    "available_slots": [{"start_time": "2026-03-22T10:00:00+01:00"}],
                }
            }
        )
        mode_context = {"stylist_id": "sty-1", "stylist_name": "María"}

        with patch.object(
            mode,
            "_interpret_slot_tool_results",
            return_value={
                "has_slots": False,
                "available_slots": None,
                "no_slots_for_chosen_stylist": True,
                "substitution_made": False,
            },
        ) as interpret_mock:
            next_step, updated_context = mode._advance_step(result, "slot_selection", mode_context)

        interpret_mock.assert_called_once()
        assert next_step == "slot_selection"
        assert updated_context["no_slots_for_stylist"] is True
        assert "selected_slot" not in updated_context

    def test_slot_selection_stays_when_no_slots_for_chosen_stylist(self):
        mode = self.make_mode()
        result = self.make_result(
            tool_results={
                "find_next_available": {
                    "selected_stylist_slots": [],
                    "soonest_any": {"stylist_id": "sty-2", "is_different_stylist": True},
                }
            }
        )

        next_step, updated_context = mode._advance_step(
            result,
            BookingSubstep.SLOT_SELECTION,
            {"stylist_id": "sty-1", "stylist_name": "María"},
        )

        assert next_step == "slot_selection"
        assert updated_context["booking_step"] == "slot_selection"
        assert updated_context["no_slots_for_stylist"] is True

    def test_slot_selection_advances_to_customer_name_when_interpretation_has_slots(self):
        mode = self.make_mode()
        result = self.make_result(
            tool_results={
                "check_availability": {
                    "available_slots": [
                        {
                            "start_time": "2026-03-22T10:00:00+01:00",
                            "full_datetime": "2026-03-22T10:00:00+01:00",
                        }
                    ]
                }
            }
        )

        next_step, updated_context = mode._advance_step(
            result,
            BookingSubstep.SLOT_SELECTION,
            {"stylist_id": "sty-1", "stylist_name": "María"},
        )

        assert next_step == "customer_name"
        assert updated_context["booking_step"] == "customer_name"
        assert updated_context["selected_slot"]["start_time"] == "2026-03-22T10:00:00+01:00"


class TestBookingModeAddOnsAndCustomerName:
    async def test_handle_add_ons_auto_skips_when_pending_recommendations_empty(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="add_ons")
        context = {
            "booking_step": "add_ons",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "pending_recommendations": [],
        }

        expected = {
            "messages": [{"role": "assistant", "content": "Seguimos", "timestamp": "now"}],
            "mode_context": {"booking_step": "stylist_selection", "service_name": "Cortar"},
            "last_node": "booking",
            "user_message": None,
        }

        with patch.object(mode, "_handle_stylist_selection", new=AsyncMock(return_value=expected)) as handler_mock:
            result = await mode._handle_add_ons(state, context)

        handler_mock.assert_awaited_once()
        assert result == expected

    async def test_handle_add_ons_decline_sets_flag_and_advances(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="add_ons")
        state["user_message"] = "no"
        context = {
            "booking_step": "add_ons",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "pending_recommendations": ["Tratamiento hidratante"],
            "add_ons_options": [
                {
                    "id": "addon-1",
                    "name": "Tratamiento hidratante",
                    "description": "Nutre el cabello",
                    "duration_minutes": 20,
                }
            ],
        }

        with patch.object(mode, "_run_agentic_loop", new=AsyncMock(return_value=AgenticLoopResult(response_text="Perfecto", tool_results={}))), patch.object(mode, "_handle_stylist_selection", new=AsyncMock()) as handler_mock:
            result = await mode._handle_add_ons(state, context)

        handler_mock.assert_not_called()
        assert result["mode_context"]["add_ons_declined"] is True
        assert result["mode_context"]["booking_step"] == "stylist_selection"

    async def test_handle_customer_name_auto_skips_when_state_has_name(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="customer_name", customer_name="Maria")
        context = {
            "booking_step": "customer_name",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Laura",
            "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        }
        result = await mode._handle_customer_name(state, context)

        assert result["customer_name"] == "Maria"
        assert result["customer_id"] == "cust-123"
        assert result["mode_context"]["booking_step"] == "notes"
        assert result["mode_context"]["customer_name"] == "Maria"

    async def test_handle_customer_name_collects_reply_and_advances(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="customer_name", customer_name=None)
        state["user_message"] = "Juan Perez"
        context = {
            "booking_step": "customer_name",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Laura",
            "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        }

        with patch.object(mode, "_run_agentic_loop", new=AsyncMock(return_value=AgenticLoopResult(response_text="A que nombre agendo la cita?", tool_results={}))):
            result = await mode._handle_customer_name(state, context)

        assert result["mode_context"]["customer_name"] == "Juan Perez"
        assert result["mode_context"]["booking_step"] == "notes"

    async def test_handle_customer_name_waits_for_reply_when_missing(self):
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="customer_name", customer_name=None)
        state["user_message"] = ""
        context = {
            "booking_step": "customer_name",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Laura",
            "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
        }

        with patch.object(mode, "_run_agentic_loop", new=AsyncMock(return_value=AgenticLoopResult(response_text="A que nombre agendo la cita?", tool_results={}))):
            result = await mode._handle_customer_name(state, context)

        assert result["mode_context"]["booking_step"] == "customer_name"
        assert "customer_name" not in result["mode_context"]

    def test_previous_substep_handles_new_steps(self):
        assert BookingMode._previous_substep(BookingSubstep.CUSTOMER_NAME) == BookingSubstep.SLOT_SELECTION
        assert BookingMode._previous_substep(BookingSubstep.ADD_ONS) == BookingSubstep.SERVICE_SELECTION
        assert BookingMode._previous_substep(BookingSubstep.STYLIST_SELECTION) == BookingSubstep.ADD_ONS
        assert BookingMode._previous_substep(BookingSubstep.NOTES) == BookingSubstep.CUSTOMER_NAME


# =============================================================================
# AgenticLoopResult integration tests (T-007)
# =============================================================================


class TestAgenticLoopResultIntegration:
    """
    Tests that verify handle() correctly processes AgenticLoopResult from
    step handlers and builds the state update dict with booking_step.
    """

    async def test_handle_service_selection_returns_booking_step_in_mode_context(self):
        """
        handle() at service_selection step must include booking_step in mode_context.
        """
        mode = make_booking_mode("¿Qué servicio te gustaría?")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        mode_context = result.get("mode_context", {})
        assert "booking_step" in mode_context

    async def test_handle_service_selection_stays_at_service_selection_without_context(self):
        """
        Without service_name in mode_context, service_selection stays put.
        """
        mode = make_booking_mode("¿Qué servicio?")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "service_selection"

    async def test_handle_returns_assistant_message(self):
        """
        handle() must always return at least one assistant message.
        """
        mode = make_booking_mode("Respuesta de prueba")
        state = make_state_with_step(booking_step="service_selection")

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        assert len(messages) >= 1
        assert messages[0]["role"] == "assistant"


# =============================================================================
# Reject intent at ADD_ONS step (should NOT cancel)
# =============================================================================


class TestBookingModeRejectAtAddOns:
    """Reject at ADD_ONS means declining the recommendation, NOT cancelling the booking."""

    async def test_reject_at_add_ons_advances_to_stylist_selection(self):
        """reject intent at add_ons should advance to stylist_selection, not trigger cancel flow."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="add_ons")
        state["user_message"] = "no, gracias"
        state["mode_context"].update({
            "service_id": "svc-1",
            "service_name": "Cortar",
            "service_category": "Peluquería",
            "pending_recommendations": ["Tratamiento hidratante"],
        })

        stylist_response = {
            **mode._response_updates(state, "Perfecto. ¿Tenés preferencia de estilista?"),
            "mode_context": {
                "booking_step": "stylist_selection",
                "service_id": "svc-1",
                "service_name": "Cortar",
                "add_ons_declined": True,
            },
            "last_node": "booking",
            "user_message": None,
        }

        with patch.object(mode, "_handle_stylist_selection", new=AsyncMock(return_value=stylist_response)):
            result = await mode.handle(state, make_intent("reject"))

        # Must NOT transition to GENERAL (cancel flow)
        assert result.get("current_mode") != "GENERAL"
        # Response should NOT contain cancel-related text
        messages = result.get("messages", [])
        combined = " ".join(m.get("content", "") for m in messages)
        assert "cancelar" not in combined.lower()
        # Must advance to stylist_selection
        mode_context = result.get("mode_context", {})
        assert mode_context.get("booking_step") == "stylist_selection"
        assert mode_context.get("add_ons_declined") is True


# =============================================================================
# _handle_stylist_selection passes list_stylists tool
# =============================================================================


# =============================================================================
# _prefetch_stylist_options error flag injection
# =============================================================================


class TestPrefetchStylistOptionsError:
    """Verify _prefetch_stylist_options returns typed PrefetchResult variants."""

    # Task 5.1 — list_stylists soft error → PrefetchToolError (spec: tool error stops pipeline)
    @pytest.mark.asyncio
    async def test_prefetch_returns_tool_error_when_list_stylists_returns_error_field(self):
        """If list_stylists returns error field, must return PrefetchToolError and NOT call find_next_available."""
        mode = make_booking_mode()
        mode_context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 45,
            "booking_step": "stylist_selection",
        }

        mock_list = MagicMock()
        mock_list.ainvoke = AsyncMock(return_value={"stylists": [], "error": "DB timeout"})
        mock_avail = MagicMock()
        mock_avail.ainvoke = AsyncMock(return_value={"available_stylists": []})

        with patch("agent.tools.info_tools.list_stylists", new=mock_list), \
             patch("agent.tools.availability_tools.find_next_available", new=mock_avail):
            result = await mode._prefetch_stylist_options(mode_context)

        assert result["status"] == "tool_error"
        assert result.get("error_detail") == "DB timeout"
        # find_next_available must NOT be called (spec: tool error stops pipeline)
        mock_avail.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefetch_returns_tool_error_when_list_stylists_raises(self):
        """If list_stylists.ainvoke raises, must return PrefetchToolError."""
        mode = make_booking_mode()
        mode_context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 45,
            "booking_step": "stylist_selection",
        }

        failing_tool = MagicMock()
        failing_tool.ainvoke = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch("agent.tools.info_tools.list_stylists", new=failing_tool):
            result = await mode._prefetch_stylist_options(mode_context)

        assert result["status"] == "tool_error"
        assert "DB connection lost" in result.get("error_detail", "")

    # Task 5.2 — find_next_available soft error + empty list → PrefetchNoAvailability
    @pytest.mark.asyncio
    async def test_prefetch_returns_no_availability_when_find_next_available_returns_error_field(self):
        """If find_next_available returns error with empty list, must return PrefetchNoAvailability."""
        mode = make_booking_mode()
        mode_context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 45,
        }

        mock_list = MagicMock()
        mock_list.ainvoke = AsyncMock(return_value={
            "stylists": [{"name": "Ana", "id": "sty-1"}],
        })
        mock_avail = MagicMock()
        mock_avail.ainvoke = AsyncMock(return_value={
            "available_stylists": [],
            "error": "No dates found",
        })

        with patch("agent.tools.info_tools.list_stylists", new=mock_list), \
             patch("agent.tools.availability_tools.find_next_available", new=mock_avail):
            result = await mode._prefetch_stylist_options(mode_context)

        assert result["status"] == "no_availability"
        assert result.get("error_detail") == "No dates found"

    # Task 5.3 — both tools succeed → PrefetchOk
    @pytest.mark.asyncio
    async def test_prefetch_returns_ok_when_both_tools_succeed(self):
        """On success, must return PrefetchOk with prefetched_stylists populated."""
        mode = make_booking_mode()
        mode_context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 45,
        }

        mock_list = MagicMock()
        mock_list.ainvoke = AsyncMock(return_value={
            "stylists": [{"name": "Ana", "id": "sty-1"}],
        })
        mock_avail = MagicMock()
        mock_avail.ainvoke = AsyncMock(return_value={"available_stylists": []})

        with patch("agent.tools.info_tools.list_stylists", new=mock_list), \
             patch("agent.tools.availability_tools.find_next_available", new=mock_avail):
            result = await mode._prefetch_stylist_options(mode_context)

        assert result["status"] == "ok"
        assert "prefetched_stylists" in result
        assert len(result["prefetched_stylists"]) == 1
        assert result["prefetched_stylists"][0]["name"] == "Ana"
        assert result.get("prefetch_error") is None  # No error key in PrefetchOk

    # Keep backward-compat test for success path
    @pytest.mark.asyncio
    async def test_prefetch_does_not_set_error_flag_on_success(self):
        """On success, status must be 'ok' and prefetched_stylists must be present."""
        mode = make_booking_mode()
        mode_context = {
            "service_category": "Peluquería",
            "service_duration_minutes": 45,
        }

        mock_list = MagicMock()
        mock_list.ainvoke = AsyncMock(return_value={"stylists": []})
        mock_avail = MagicMock()
        mock_avail.ainvoke = AsyncMock(return_value={"available_stylists": []})

        with patch("agent.tools.info_tools.list_stylists", new=mock_list), \
             patch("agent.tools.availability_tools.find_next_available", new=mock_avail):
            result = await mode._prefetch_stylist_options(mode_context)

        assert result["status"] == "ok"
        assert "prefetched_stylists" in result


# =============================================================================
# Task 5.4–5.6: _handle_stylist_selection path tests
# =============================================================================


def _make_prefetch_ok(
    stylist_name: str = "Ana",
    stylist_id: str = "sty-1",
    soonest_slot: str = "lunes a las 10:00",
) -> dict:
    """Build a PrefetchOk-compatible dict for mocking."""
    return {
        "status": "ok",
        "prefetched_stylists": [{"name": stylist_name, "id": stylist_id, "next_slot_summary": soonest_slot}],
        "soonest_any_slot": soonest_slot,
        "soonest_any_slot_candidate": {
            "stylist_id": stylist_id,
            "stylist_name": stylist_name,
            "slot_datetime": "2026-03-23T10:00:00",
            "slot_summary": soonest_slot,
        },
    }


class TestHandleStylistSelectionPaths:
    """Tests for the 6 paths in _handle_stylist_selection (spec scenarios A–F)."""

    def _make_context(self) -> dict:
        return {
            "booking_step": "stylist_selection",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "service_category": "Peluquería",
        }

    # Task 5.4 — Path A: resolver match → same-turn handoff → _handle_slot_selection called
    @pytest.mark.asyncio
    async def test_path_a_resolver_match_calls_handle_slot_selection(self):
        """Path A: prefetch=ok, resolver=match → _handle_slot_selection called, LLM not called."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "cualquiera"
        context = self._make_context()

        slot_response = {
            **add_message(state, "assistant", "Aquí están los horarios disponibles."),
            "mode_context": {"booking_step": "slot_selection", "stylist_id": "sty-1"},
            "last_node": "booking",
            "user_message": None,
        }

        with patch.object(mode, "_populate_recurrent_stylist", new=AsyncMock(side_effect=lambda s, c: c)), \
             patch.object(mode, "_prefetch_stylist_options", new=AsyncMock(return_value=_make_prefetch_ok())), \
             patch.object(mode, "_handle_slot_selection", new=AsyncMock(return_value=slot_response)) as mock_slot, \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock()) as mock_llm:
            result = await mode._handle_stylist_selection(state, context)

        # _handle_slot_selection must be called (same-turn handoff)
        mock_slot.assert_called_once()
        # _run_agentic_loop must NOT be called (no LLM turn for stylist step)
        mock_llm.assert_not_called()
        # The result is from _handle_slot_selection
        assert result is slot_response

    # Task 5.4 — Path A: booking_step set to SLOT_SELECTION before handoff
    @pytest.mark.asyncio
    async def test_path_a_context_has_stylist_set_before_slot_handoff(self):
        """Path A: stylist_id and stylist_name must be set in context passed to _handle_slot_selection."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "cualquiera"
        context = self._make_context()

        captured_context = {}

        async def capture_slot(st, ctx):
            captured_context.update(ctx)
            return {"last_node": "booking", "user_message": None, "mode_context": {}}

        with patch.object(mode, "_populate_recurrent_stylist", new=AsyncMock(side_effect=lambda s, c: c)), \
             patch.object(mode, "_prefetch_stylist_options", new=AsyncMock(return_value=_make_prefetch_ok())), \
             patch.object(mode, "_handle_slot_selection", side_effect=capture_slot):
            await mode._handle_stylist_selection(state, context)

        assert captured_context.get("stylist_id") == "sty-1"
        assert captured_context.get("stylist_name") == "Ana"
        assert captured_context.get("booking_step") == "slot_selection"

    # Task 5.5 — Path B: resolver no match → LLM called, booking_step stays STYLIST_SELECTION
    @pytest.mark.asyncio
    async def test_path_b_resolver_no_match_calls_llm(self):
        """Path B: prefetch=ok, resolver=None → LLM called, booking_step stays STYLIST_SELECTION."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "no sé"  # ambiguous — resolver won't match
        context = self._make_context()

        llm_result = AgenticLoopResult(response_text="¿Cuál estilista preferís?", tool_results={})

        with patch.object(mode, "_populate_recurrent_stylist", new=AsyncMock(side_effect=lambda s, c: c)), \
             patch.object(mode, "_prefetch_stylist_options", new=AsyncMock(return_value=_make_prefetch_ok())), \
             patch.object(mode, "_resolve_stylist_from_message", return_value=None), \
             patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock(return_value=llm_result)) as mock_llm, \
             patch.object(mode, "_handle_slot_selection", new=AsyncMock()) as mock_slot:
            result = await mode._handle_stylist_selection(state, context)

        # LLM must be called
        mock_llm.assert_called_once()
        # _handle_slot_selection must NOT be called
        mock_slot.assert_not_called()
        # booking_step stays in STYLIST_SELECTION (not advanced unless LLM signals it)
        mode_ctx = result.get("mode_context", {})
        assert mode_ctx.get("booking_step") == "stylist_selection"

    # Task 5.6 — Path C: no_availability → hardcoded message, no LLM
    @pytest.mark.asyncio
    async def test_path_c_no_availability_returns_hardcoded_message(self):
        """Path C: prefetch=no_availability → hardcoded Spanish message, LLM not called, step stays."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "Sí"
        context = self._make_context()

        no_avail_result = {
            "status": "no_availability",
            "error_detail": "No dates found",
        }

        with patch.object(mode, "_populate_recurrent_stylist", new=AsyncMock(side_effect=lambda s, c: c)), \
             patch.object(mode, "_prefetch_stylist_options", new=AsyncMock(return_value=no_avail_result)), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock()) as mock_llm, \
             patch.object(mode, "_handle_slot_selection", new=AsyncMock()) as mock_slot:
            result = await mode._handle_stylist_selection(state, context)

        # LLM must NOT be called
        mock_llm.assert_not_called()
        # _handle_slot_selection must NOT be called
        mock_slot.assert_not_called()
        # Response must contain no-availability text (from messages)
        messages = result.get("messages", [])
        assert any("disponibilidad" in str(m).lower() for m in messages), (
            f"Expected 'disponibilidad' in messages, got: {messages}"
        )
        # mode_context must stay in STYLIST_SELECTION
        mode_ctx = result.get("mode_context", {})
        assert mode_ctx.get("booking_step") == "stylist_selection"
        # stylist_id must NOT be set
        assert mode_ctx.get("stylist_id") is None

    # Task 5.6 — Path D: tool_error → hardcoded message, no LLM
    @pytest.mark.asyncio
    async def test_path_d_tool_error_returns_hardcoded_message(self):
        """Path D: prefetch=tool_error → hardcoded technical error message, LLM not called."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "cualquiera"
        context = self._make_context()

        tool_error_result = {
            "status": "tool_error",
            "error_detail": "DB connection refused",
        }

        with patch.object(mode, "_populate_recurrent_stylist", new=AsyncMock(side_effect=lambda s, c: c)), \
             patch.object(mode, "_prefetch_stylist_options", new=AsyncMock(return_value=tool_error_result)), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock()) as mock_llm, \
             patch.object(mode, "_handle_slot_selection", new=AsyncMock()) as mock_slot:
            result = await mode._handle_stylist_selection(state, context)

        # LLM must NOT be called
        mock_llm.assert_not_called()
        # _handle_slot_selection must NOT be called
        mock_slot.assert_not_called()
        # Response must contain technical error text
        messages = result.get("messages", [])
        assert any("técnico" in str(m).lower() or "problema" in str(m).lower() for m in messages), (
            f"Expected technical error mention in messages, got: {messages}"
        )
        # mode_context must stay in STYLIST_SELECTION
        mode_ctx = result.get("mode_context", {})
        assert mode_ctx.get("booking_step") == "stylist_selection"


class TestStylistSelectionToolProvision:
    """Verify _handle_stylist_selection passes list_stylists to the agentic loop (Path B)."""

    @pytest.mark.asyncio
    async def test_handle_stylist_selection_passes_list_stylists_tool(self):
        """_handle_stylist_selection must provide list_stylists as a fallback tool (Path B — LLM path)."""
        mode = make_booking_mode()
        state = make_state_with_step(booking_step="stylist_selection")
        state["user_message"] = "no sé cuál"  # ambiguous → forces Path B (LLM)
        context = {
            "booking_step": "stylist_selection",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "service_category": "Peluquería",
        }

        # Use a PrefetchOk result but with resolver returning None to force LLM path
        prefetch_ok = {
            "status": "ok",
            "prefetched_stylists": [],
            "soonest_any_slot": None,
            "soonest_any_slot_candidate": None,
        }

        captured_tools = []

        async def mock_agentic_loop(messages, tools=None):
            captured_tools.extend(tools or [])
            return AgenticLoopResult(response_text="Te muestro las estilistas.", tool_results={})

        with patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_run_agentic_loop", side_effect=mock_agentic_loop), \
             patch.object(mode, "_populate_recurrent_stylist", new=AsyncMock(side_effect=lambda s, c: c)), \
             patch.object(mode, "_prefetch_stylist_options", new=AsyncMock(return_value=prefetch_ok)), \
             patch.object(mode, "_resolve_stylist_from_message", return_value=None):
            await mode._handle_stylist_selection(state, context)

        tool_names = [getattr(t, "name", str(t)) for t in captured_tools]
        assert "list_stylists" in tool_names, (
            f"Expected list_stylists in tools, got: {tool_names}"
        )


# =============================================================================
# T3.1-T3.5: _handle_completed defensive guard + error_count + mode_context
# =============================================================================


def _make_completed_state(
    customer_id: str | None = None,
    pending_whatsapp_name: str | None = None,
    customer_first_name: str | None = None,
    customer_phone: str = "+34600000001",
    error_count: int = 0,
) -> dict:
    """Build a state for _handle_completed tests."""
    state = create_initial_state("conv-completed", customer_phone)
    state["customer_id"] = customer_id
    state["customer_phone"] = customer_phone
    state["customer_first_name"] = customer_first_name
    state["pending_whatsapp_name"] = pending_whatsapp_name
    state["error_count"] = error_count
    state["current_mode"] = "BOOKING"
    state["is_first_interaction"] = False
    return state


def _make_completed_mode_context(
    selected_slot: dict | None = None,
    stylist_id: str = "sty-1",
    service_name: str = "Corte",
    first_name: str | None = None,
) -> dict:
    return {
        "booking_step": "confirmation",
        "stylist_id": stylist_id,
        "service_name": service_name,
        "selected_slot": selected_slot or {"start_time": "2026-03-25T10:00:00+01:00"},
        "selected_services": [service_name],
        **({"first_name": first_name} if first_name else {}),
    }


class TestHandleCompletedDefensiveGuard:
    """
    T3.1 — New client, name from pending_whatsapp_name: _create_customer_if_needed called,
            book() receives returned UUID.
    T3.2 — Returning client with customer_id set: _create_customer_if_needed NOT called,
            book() called with existing UUID directly.
    T3.3 — New client, no phone: _create_customer_if_needed returns None,
            book() NOT called, error response returned.
    """

    def _make_mode(self, loop_response: str = "Error al reservar.") -> BookingMode:
        mock_llm = make_mock_llm(loop_response)
        return BookingMode(tools=[], llm_client=mock_llm)

    @pytest.mark.asyncio
    async def test_new_client_name_from_pending_whatsapp_name_creates_customer(self):
        """T3.1: customer_id=None + pending_whatsapp_name → _create_customer_if_needed called,
        book() receives the new UUID."""
        mode = self._make_mode()
        state = _make_completed_state(
            customer_id=None,
            pending_whatsapp_name="María",
            customer_phone="+34600000001",
        )
        mode_context = _make_completed_mode_context()

        mock_book = MagicMock()
        mock_book.ainvoke = AsyncMock(return_value={"appointment_id": "appt-123"})

        with patch("agent.tools.booking_tools.book", new=mock_book), \
             patch.object(
                 mode,
                 "_create_customer_if_needed",
                 new=AsyncMock(return_value="new-uuid-456"),
             ) as mock_create, \
             patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_use_optimized_prompts", return_value=False), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock(
                 return_value=AgenticLoopResult(response_text="¡Reservado!", tool_results={})
             )):
            result = await mode._handle_completed(state, mode_context)

        # _create_customer_if_needed was called with name chain: first_name → pending_whatsapp_name
        mock_create.assert_awaited_once()
        call_args = mock_create.call_args
        assert call_args[0][1] == "María"  # resolved_name from pending_whatsapp_name

        # book() was called with the new UUID
        mock_book.ainvoke.assert_awaited_once()
        book_call = mock_book.ainvoke.call_args[0][0]
        assert book_call["customer_id"] == "new-uuid-456"

        # Success path: appointment created flag is set
        assert result.get("appointment_created") is True

    @pytest.mark.asyncio
    async def test_returning_client_skips_customer_creation(self):
        """T3.2: customer_id already set → _create_customer_if_needed NOT called,
        book() uses existing UUID."""
        mode = self._make_mode()
        state = _make_completed_state(customer_id="existing-uuid-123")
        mode_context = _make_completed_mode_context()

        mock_book = MagicMock()
        mock_book.ainvoke = AsyncMock(return_value={"appointment_id": "appt-999"})

        with patch("agent.tools.booking_tools.book", new=mock_book), \
             patch.object(
                 mode,
                 "_create_customer_if_needed",
                 new=AsyncMock(return_value="should-not-be-called"),
             ) as mock_create, \
             patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_use_optimized_prompts", return_value=False), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock(
                 return_value=AgenticLoopResult(response_text="¡Reservado!", tool_results={})
             )):
            result = await mode._handle_completed(state, mode_context)

        # _create_customer_if_needed must NOT be called
        mock_create.assert_not_awaited()

        # book() was called with existing UUID
        book_call = mock_book.ainvoke.call_args[0][0]
        assert book_call["customer_id"] == "existing-uuid-123"

    @pytest.mark.asyncio
    async def test_no_phone_customer_creation_returns_none_book_fails(self):
        """T3.3: customer_id=None + no phone → creation returns None → book() called with
        empty string → raises ValueError → error response with error_count incremented."""
        mode = self._make_mode("No se pudo completar la reserva.")
        state = _make_completed_state(
            customer_id=None,
            customer_phone="",  # No phone
        )
        state["customer_phone"] = ""
        mode_context = _make_completed_mode_context()

        # book() gets called with empty customer_id and raises (as UUID("") would)
        mock_book = MagicMock()
        mock_book.ainvoke = AsyncMock(
            side_effect=ValueError("badly formed hexadecimal UUID string: ")
        )

        with patch("agent.tools.booking_tools.book", new=mock_book), \
             patch.object(
                 mode,
                 "_create_customer_if_needed",
                 new=AsyncMock(return_value=None),
             ), \
             patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_use_optimized_prompts", return_value=False), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock(
                 return_value=AgenticLoopResult(response_text="Error al reservar.", tool_results={})
             )):
            result = await mode._handle_completed(state, mode_context)

        # Error response returned, no appointment created
        assert result.get("appointment_created") is not True
        # error_count incremented
        assert result.get("error_count", 0) >= 1
        # mode_context preserved at confirmation step
        assert result["mode_context"]["booking_step"] == "confirmation"


class TestHandleCompletedErrorCount:
    """T3.4: booking failure increments error_count by 1."""

    @pytest.mark.asyncio
    async def test_booking_failure_increments_error_count(self):
        """T3.4: When book() fails, error_count in state update is prev + 1."""
        mode = BookingMode(tools=[], llm_client=make_mock_llm())
        state = _make_completed_state(
            customer_id="uuid-existing",
            error_count=2,
        )
        mode_context = _make_completed_mode_context()

        mock_book = MagicMock()
        mock_book.ainvoke = AsyncMock(side_effect=ValueError("booking exploded"))

        with patch("agent.tools.booking_tools.book", new=mock_book), \
             patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_use_optimized_prompts", return_value=False), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock(
                 return_value=AgenticLoopResult(response_text="Hubo un error.", tool_results={})
             )):
            result = await mode._handle_completed(state, mode_context)

        assert result["error_count"] == 3  # prev(2) + 1


class TestHandleCompletedModeContextPreservation:
    """T3.5: booking failure preserves mode_context — slot data intact, last_error set."""

    @pytest.mark.asyncio
    async def test_error_preserves_mode_context_fields(self):
        """T3.5: On error, mode_context preserves selected_slot, stylist_id, service_name,
        booking_step=confirmation, and adds last_error."""
        mode = BookingMode(tools=[], llm_client=make_mock_llm())
        state = _make_completed_state(customer_id="uuid-existing")
        mode_context = _make_completed_mode_context(
            selected_slot={"start_time": "2026-03-25T10:00:00+01:00"},
            stylist_id="sty-42",
            service_name="Tinte completo",
        )

        mock_book = MagicMock()
        mock_book.ainvoke = AsyncMock(side_effect=ValueError("network timeout"))

        with patch("agent.tools.booking_tools.book", new=mock_book), \
             patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
             patch.object(mode, "_use_optimized_prompts", return_value=False), \
             patch.object(mode, "_run_agentic_loop", new=AsyncMock(
                 return_value=AgenticLoopResult(response_text="Hubo un problema.", tool_results={})
             )):
            result = await mode._handle_completed(state, mode_context)

        ctx = result["mode_context"]
        assert ctx["booking_step"] == "confirmation"
        assert ctx["selected_slot"] == {"start_time": "2026-03-25T10:00:00+01:00"}
        assert ctx["stylist_id"] == "sty-42"
        assert ctx["service_name"] == "Tinte completo"
        assert ctx["last_error"] == "network timeout"


# ── NEW TESTS for Bug Fixes (pending_clarification + token filter) ─────────────


@pytest.mark.asyncio
async def test_handle_service_selection_clears_pending_clarification_after_resolve():
    """When user answers clarification, pending_clarification should be set to None."""
    mode = BookingMode()
    state = default_conversation_state()
    
    # Setup: booking_step = SERVICE_SELECTION with a pending clarification
    mode_context = {
        "booking_step": "service_selection",
        "pending_clarification": {
            "axis": "audience",
            "question_hint": "¿Es para dama, caballero, niño o niña?",
            "options": [
                {"value": "dama", "service_name": "Corte Dama", "service_id": "srv-1", "duration_minutes": 30, "category": "Peluquería"},
                {"value": "caballero", "service_name": "Corte Caballero", "service_id": "srv-2", "duration_minutes": 25, "category": "Peluquería"},
                {"value": "niño", "service_name": "Corte Niño", "service_id": "srv-3", "duration_minutes": 20, "category": "Peluquería"},
            ],
        },
    }
    
    # User says "caballero"
    state["messages"].append({"role": "user", "content": "Un corte de caballero", "timestamp": datetime.now(UTC)})
    
    # Mock search_services for normal path (fallback)
    with patch("agent.tools.search_services.search_services", new=AsyncMock(return_value={})), \
         patch.object(mode, "_parse_clarification_answer", return_value=("audience", "caballero")), \
         patch.object(mode, "_get_last_user_message", return_value="Un corte de caballero"), \
         patch.object(mode, "_build_layered_messages", new=AsyncMock(return_value=[])), \
         patch.object(mode, "_use_optimized_prompts", return_value=False), \
         patch.object(mode, "_run_agentic_loop", new=AsyncMock(
             return_value=AgenticLoopResult(response_text="Perfecto, elegiste Corte Caballero.", tool_results={})
         )):
        result = await mode._handle_service_selection(state, mode_context)
    
    # Check that pending_clarification was cleared (set to None)
    returned_context = result["mode_context"]
    assert returned_context["pending_clarification"] is None, "pending_clarification should be None after resolution"
    assert returned_context["service_name"] == "Corte Caballero"
    assert returned_context["booking_step"] == "add_ons"  # Should advance to next step


@pytest.mark.asyncio
async def test_booking_response_filters_customer_name_token():
    """When LLM response contains customer name token, fallback to safe response."""
    mode = BookingMode()
    state = default_conversation_state()
    state["customer_name"] = "María"
    
    # Simulate LLM generating a response with name leak
    llm_response = "¡Hola, María! ¿Qué servicio querés para tu corte?"
    
    # Call _response_updates which should detect and filter the name
    updates = mode._response_updates(state, llm_response)
    
    # Check that the response was replaced with fallback
    messages = updates.get("messages", [])
    assert len(messages) > 0, "Message should be added"
    
    final_message = messages[-1]["content"]
    assert "María" not in final_message, "Customer name should not appear in final response"
    assert "De acuerdo, continuemos" in final_message, "Fallback response should be used"


def test_contains_customer_name_token_handles_variations():
    """Filter should match name regardless of case/accents."""
    mode = BookingMode()
    
    # Test: "María" matches "maria", "MARIA", "Maria"
    assert mode._contains_customer_name_token("Hola, maria!", "María") is True
    assert mode._contains_customer_name_token("Hola, MARIA!", "María") is True
    assert mode._contains_customer_name_token("Hola, Maria!", "María") is True
    
    # Test: "José" matches in different cases
    assert mode._contains_customer_name_token("Hola, jose!", "José") is True
    assert mode._contains_customer_name_token("Hola, JOSE!", "José") is True
    
    # Test: "Luis" in different cases
    assert mode._contains_customer_name_token("Hola, luis!", "Luis") is True
    assert mode._contains_customer_name_token("Hola, LUIS!", "Luis") is True
    
    # Test: Name NOT in response (should return False)
    assert mode._contains_customer_name_token("Hola, qué servicio quieres?", "María") is False


def test_contains_customer_name_token_ignores_short_tokens():
    """Tokens <3 chars should not trigger false positives."""
    mode = BookingMode()
    
    # Test: "Al" (2 chars) should be skipped, but "Al" might match as a word
    # If name is "Al", tokens are ["Al"] (2 chars), skipped → should return False
    assert mode._contains_customer_name_token("Al servicio le voy", "Al") is False
    
    # Test: "Ana" (3 chars, boundary) — should be considered (≥3)
    # This is a boundary test — "Ana" has exactly 3 chars, so it should match
    assert mode._contains_customer_name_token("Hola, Ana, ¿qué tal?", "Ana") is True
    
    # Test: Short middle name should not match
    # "José María" → tokens ["José", "María"], both ≥3 chars
    # "jose" matches → True (but "maria" also ≥3)
    assert mode._contains_customer_name_token("Hola, José María!", "Carlos Manuel") is False
    
    # Test: Single letter should be skipped
    assert mode._contains_customer_name_token("Hola A, ¿cómo estás?", "A") is False
