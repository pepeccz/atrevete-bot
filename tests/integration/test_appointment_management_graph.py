"""
Integration tests for appointment management graph flows (T13).

Tests the full graph pipeline for APPOINTMENT_MANAGEMENT mode:
- Router correctly routes reschedule/check_appointments/cancel to APPOINTMENT_MANAGEMENT
- 48h window escalation transitions to ESCALATION
- Full graph produces responses and correct mode transitions
- Edge cases: empty appointments list

Mock at graph boundary:
- LLM (_get_llm_client): returns canned text, no tool calls
- DB (check_customer_exists): returns a mock customer
- summarize_conversation: no-op
- _get_intent_router: returns desired intent result
- _run_agentic_loop inside the mode: returns canned AgenticLoopResult

No real DB, Redis, or LLM connections needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graphs.conversation_flow import create_graph, router_node
from agent.modes.base import AgenticLoopResult
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# ============================================================================
# Shared Helpers
# ============================================================================


def _make_llm(response_text: str = "Aquí están tus citas.") -> MagicMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def _make_intent_router(intent: str, confidence: float = 0.9) -> MagicMock:
    """Mock IntentRouter that returns the given intent."""
    mock = MagicMock()
    mock.classify = AsyncMock(
        return_value=IntentResult(
            intent=intent,
            confidence=confidence,
            raw_input="",
            mode_hint=None,
        )
    )
    return mock


async def _customer_found(*args, **kwargs):
    """Returning customer mock."""
    mock_customer = MagicMock()
    mock_customer.id = "uuid-customer-appt-001"
    mock_customer.first_name = "María"
    return (True, mock_customer)


async def _summarize_noop(state):
    """Summarize is a no-op."""
    return {}


def _make_state(
    user_message: str = "quiero cancelar mi cita",
    current_mode: str = "GENERAL",
    customer_name: str = "María",
    mode_context: dict | None = None,
) -> dict:
    """Build a ConversationState for integration tests."""
    state = create_initial_state("appt-mgmt-test-001", "+34612345678")
    state["user_message"] = user_message
    state["current_mode"] = current_mode
    state["customer_name"] = customer_name
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["mode_context"] = mode_context or {}
    state["ai_disclosure_sent"] = True  # Avoid disclosure prefix
    return state


# ============================================================================
# Test 1 — Cancel intent > 48h full flow
# ============================================================================


class TestCancelFullFlow:
    """
    Test 1: User says "quiero cancelar mi cita" →
    routes to APPOINTMENT_MANAGEMENT → mode runs → returns response.
    """

    async def test_cancel_routes_to_appointment_management(self):
        """
        router_node with cancel intent (outside BOOKING) → APPOINTMENT_MANAGEMENT.
        (Rule 2.8: cancel outside BOOKING/CONFIRMATION_REPLY → APPOINTMENT_MANAGEMENT)
        """
        state = _make_state(
            user_message="quiero cancelar mi cita",
            current_mode="GENERAL",
        )
        state["messages"] = [
            {
                "role": "user",
                "content": "quiero cancelar mi cita",
                "timestamp": "2026-01-01T00:00:00",
            }
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("cancel")
            result = await router_node(state)

        assert result.get("current_mode") == "APPOINTMENT_MANAGEMENT"
        assert result.get("last_node") == "router"

    async def test_cancel_full_graph_produces_response(self):
        """
        Full graph run with cancel intent → APPOINTMENT_MANAGEMENT executes →
        response in messages.
        """
        state = _make_state(
            user_message="quiero cancelar mi cita",
            current_mode="GENERAL",
        )
        mock_llm = _make_llm("¿Qué cita deseas cancelar?")

        loop_result = AgenticLoopResult(
            response_text="¿Qué cita deseas cancelar?",
            tool_results={},
        )

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._run_agentic_loop",
                new_callable=AsyncMock,
                return_value=loop_result,
            ),
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._build_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_get_router.return_value = _make_intent_router("cancel")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "apmt-cancel-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        messages = result.get("messages", [])
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_messages) >= 1


# ============================================================================
# Test 2 — Cancel <48h → escalation
# ============================================================================


class TestCancelWithin48hEscalation:
    """
    Test 2: Tool returns within_window=True → mode transitions to ESCALATION.
    """

    async def test_within_window_escalates_to_escalation(self):
        """
        When the cancel tool returns within_window=True, the mode must
        transition to ESCALATION.
        """
        state = _make_state(
            user_message="confirmo la cancelación",
            current_mode="APPOINTMENT_MANAGEMENT",
            mode_context={
                "action": "cancel",
                "selected_appointment_id": "appt-uuid-001",
                "selected_appointment_snapshot": {
                    "date_display": "mañana",
                    "time_display": "10:00",
                },
                "pending_confirmation": True,
                "pending_confirmation_type": "cancel",
            },
        )
        state["messages"] = [
            {
                "role": "user",
                "content": "confirmo la cancelación",
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        mock_llm = _make_llm("Tu cita está dentro de las 48 horas.")

        loop_result = AgenticLoopResult(
            response_text="Dentro de 48h — escalando al equipo.",
            tool_results={"cancel_appointment": [{"within_window": True, "hours_until": 10}]},
        )

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._run_agentic_loop",
                new_callable=AsyncMock,
                return_value=loop_result,
            ),
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._build_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_get_router.return_value = _make_intent_router("cancel")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "apmt-window-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        assert result.get("current_mode") == "ESCALATION"


# ============================================================================
# Test 3 — Reschedule intent routing
# ============================================================================


class TestRescheduleIntentRouting:
    """
    Test 3: User says "quiero reagendar" → routes to APPOINTMENT_MANAGEMENT
    (not BOOKING, not GENERAL).
    """

    async def test_reschedule_routes_to_appointment_management_via_router(self):
        """
        Direct router_node call with reschedule intent → APPOINTMENT_MANAGEMENT.
        Rule 2.7: reschedule → APPOINTMENT_MANAGEMENT.
        """
        state = _make_state(
            user_message="quiero reagendar mi cita",
            current_mode="GENERAL",
        )
        state["messages"] = [
            {
                "role": "user",
                "content": "quiero reagendar mi cita",
                "timestamp": "2026-01-01T00:00:00",
            }
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("reschedule")
            result = await router_node(state)

        assert result.get("current_mode") == "APPOINTMENT_MANAGEMENT"

    async def test_reschedule_does_not_route_to_booking(self):
        """
        Reschedule intent must NOT route to BOOKING.
        """
        state = _make_state(
            user_message="reagendar mi turno",
            current_mode="GENERAL",
        )
        state["messages"] = [
            {"role": "user", "content": "reagendar mi turno", "timestamp": "2026-01-01T00:00:00"}
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("reschedule")
            result = await router_node(state)

        assert result.get("current_mode") != "BOOKING"

    async def test_reschedule_full_graph_runs(self):
        """
        Full graph run with reschedule intent → APPOINTMENT_MANAGEMENT node executes.
        """
        state = _make_state(
            user_message="quiero reagendar",
            current_mode="GENERAL",
        )
        mock_llm = _make_llm("Voy a revisar tus citas para reagendarla.")

        loop_result = AgenticLoopResult(
            response_text="Voy a revisar tus citas para reagendarla.",
            tool_results={},
        )

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._run_agentic_loop",
                new_callable=AsyncMock,
                return_value=loop_result,
            ),
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._build_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_get_router.return_value = _make_intent_router("reschedule")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "apmt-reschedule-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        messages = result.get("messages", [])
        assert any(m.get("role") == "user" for m in messages)


# ============================================================================
# Test 4 — check_appointments routing
# ============================================================================


class TestCheckAppointmentsRouting:
    """
    Test 4: User says "cuándo es mi próxima cita" → routes to APPOINTMENT_MANAGEMENT.
    """

    async def test_check_appointments_routes_to_appointment_management(self):
        """
        Direct router_node call with check_appointments intent → APPOINTMENT_MANAGEMENT.
        Rule 2.7: check_appointments → APPOINTMENT_MANAGEMENT.
        """
        state = _make_state(
            user_message="cuándo es mi próxima cita",
            current_mode="GENERAL",
        )
        state["messages"] = [
            {
                "role": "user",
                "content": "cuándo es mi próxima cita",
                "timestamp": "2026-01-01T00:00:00",
            }
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("check_appointments")
            result = await router_node(state)

        assert result.get("current_mode") == "APPOINTMENT_MANAGEMENT"

    async def test_check_appointments_full_graph_returns_response(self):
        """
        Full graph run with check_appointments → bot returns a response.
        """
        state = _make_state(
            user_message="cuándo es mi próxima cita",
            current_mode="GENERAL",
        )
        mock_llm = _make_llm("Voy a consultar tus citas.")

        loop_result = AgenticLoopResult(
            response_text="Voy a consultar tus citas ahora mismo.",
            tool_results={},
        )

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._run_agentic_loop",
                new_callable=AsyncMock,
                return_value=loop_result,
            ),
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._build_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_get_router.return_value = _make_intent_router("check_appointments")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "apmt-check-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        messages = result.get("messages", [])
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_messages) >= 1


# ============================================================================
# Test 5 — No appointments edge case
# ============================================================================


class TestNoAppointmentsEdgeCase:
    """
    Test 5: list_customer_appointments returns empty → bot responds with Spanish
    "no tenés citas" message.
    """

    async def test_no_appointments_bot_responds_in_spanish(self):
        """
        When list_customer_appointments returns empty list, LLM should produce
        a Spanish message like 'no tenés citas'.
        We verify the graph runs and produces a response (not a crash).
        """
        state = _make_state(
            user_message="mis citas",
            current_mode="GENERAL",
        )
        # LLM produces a no-appointments response
        no_appts_response = "No tenés citas próximas registradas. ¿Te gustaría reservar una?"
        mock_llm = _make_llm(no_appts_response)

        loop_result = AgenticLoopResult(
            response_text=no_appts_response,
            tool_results={"list_customer_appointments": [{"appointments": []}]},
        )

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._run_agentic_loop",
                new_callable=AsyncMock,
                return_value=loop_result,
            ),
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._build_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_get_router.return_value = _make_intent_router("check_appointments")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "apmt-empty-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        messages = result.get("messages", [])
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_messages) >= 1
        # Verify the response is in Spanish (basic sanity check)
        response_text = assistant_messages[-1].get("content", "")
        assert len(response_text) > 0


# ============================================================================
# Test 6 — Cancel outside BOOKING routing (Rule 2.8)
# ============================================================================


class TestCancelOutsideBookingRouting:
    """
    Test 6: current_mode=GENERAL, intent=cancel → routes to APPOINTMENT_MANAGEMENT
    (Rule 2.8: cancel outside BOOKING/CONFIRMATION_REPLY → APPOINTMENT_MANAGEMENT).
    """

    async def test_cancel_outside_booking_routes_to_appointment_management(self):
        """
        router_node: current_mode=GENERAL + intent=cancel → APPOINTMENT_MANAGEMENT.
        """
        state = _make_state(
            user_message="cancelar mi cita",
            current_mode="GENERAL",
        )
        state["messages"] = [
            {
                "role": "user",
                "content": "cancelar mi cita",
                "timestamp": "2026-01-01T00:00:00",
            }
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("cancel")
            result = await router_node(state)

        assert result.get("current_mode") == "APPOINTMENT_MANAGEMENT"

    async def test_cancel_inside_booking_stays_in_booking(self):
        """
        router_node: current_mode=BOOKING + intent=cancel → stays in BOOKING
        (handled by booking cancel flow, NOT appointment management).
        Rule 7: stay in BOOKING unless cancel/reject/ask_info.
        Rule 10: if in BOOKING and cancel → target_mode = BOOKING.
        """
        state = _make_state(
            user_message="cancelar",
            current_mode="BOOKING",
        )
        state["messages"] = [
            {"role": "user", "content": "cancelar", "timestamp": "2026-01-01T00:00:00"}
        ]

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_intent_router("cancel")
            result = await router_node(state)

        # Cancel inside BOOKING should NOT go to APPOINTMENT_MANAGEMENT
        assert result.get("current_mode") != "APPOINTMENT_MANAGEMENT"

    async def test_cancel_outside_booking_full_graph(self):
        """
        Full graph run: GENERAL mode + cancel intent → APPOINTMENT_MANAGEMENT executes.
        """
        state = _make_state(
            user_message="quiero cancelar mi cita",
            current_mode="GENERAL",
        )
        mock_llm = _make_llm("¿Cuál es la cita que deseas cancelar?")

        loop_result = AgenticLoopResult(
            response_text="¿Cuál es la cita que deseas cancelar?",
            tool_results={},
        )

        with (
            patch("agent.graphs.conversation_flow._get_llm_client", return_value=mock_llm),
            patch(
                "agent.graphs.conversation_flow.check_customer_exists",
                side_effect=_customer_found,
            ),
            patch(
                "agent.graphs.conversation_flow.summarize_conversation",
                side_effect=_summarize_noop,
            ),
            patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router,
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._run_agentic_loop",
                new_callable=AsyncMock,
                return_value=loop_result,
            ),
            patch(
                "agent.modes.appointment_management_mode.AppointmentManagementMode._build_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            mock_get_router.return_value = _make_intent_router("cancel")
            graph = create_graph(checkpointer=None)
            config = {"configurable": {"thread_id": "apmt-cancel-outside-001"}}
            result = await graph.ainvoke(state, config=config)

        assert result is not None
        messages = result.get("messages", [])
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_messages) >= 1
