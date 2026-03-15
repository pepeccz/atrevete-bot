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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.base import AgenticLoopResult
from agent.modes.booking_mode import BookingMode
from agent.routing.intent_router import IntentResult
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
        assert "Peinado" in message
        assert "Barro" in message
        assert result["mode_context"]["recommendations_shown"] is True
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
        """Any non-confirm intent at confirmation → show booking summary."""
        mode = make_booking_mode("¿Confirmas la reserva?")
        state = self._make_state_at_confirmation()

        result = await mode.handle(state, make_intent("book"))

        messages = result.get("messages", [])
        assert len(messages) >= 1


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
        assert next_step == "stylist_selection"

    def test_service_selection_advances_with_query_info(self):
        """query_info called AND service_name in context → advance."""
        mode = self.make_mode()
        result = self.make_result(tool_results={"query_info": {}})
        ctx = {"service_name": "Tinte"}
        next_step, _ = mode._advance_step(result, "service_selection", ctx)
        assert next_step == "stylist_selection"

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
        assert next_step == "stylist_selection"

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
        # When _advance_step is called with "confirmation", no tool results → stay
        next_step, _ = mode._advance_step(result, "confirmation", {})
        assert next_step == "confirmation"

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
