"""
Unit tests for agent/modes/appointment_management_mode.py.

Coverage:
1. query flow: handle() with intent="check_appointments" → pre-resolver sets action="query"
2. cancel flow — happy path: pending_confirmation=True + type="cancel" → tool allowed
3. cancel flow — gate blocks: pending_confirmation=False → cancel blocked
4. reschedule flow — gate blocks: pending_confirmation=True but type="cancel" mismatch
5. reschedule flow — no slot set: pending_confirmation=True + type="reschedule" but no slot
6. 48h escalation: tool returns within_window=True → ESCALATION
7. completion: tool returns success=True → ctx.action_completed=True → GENERAL
8. selection pre-resolver: user_message="2", appointments_list has 2 items → index 2 selected
9. confirmation pre-resolver: user says "sí" + pending_confirmation=False + action="cancel"
10. negative pre-resolver: user says "no" + pending_confirmation=True → reset

All LLM calls are mocked — tests do NOT require a real LLM or DB.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.appointment_context import AppointmentContext
from agent.modes.appointment_management_mode import AppointmentManagementMode
from agent.modes.base import AgenticLoopResult, ToolCallRejection
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "check_appointments", confidence: float = 0.9) -> IntentResult:
    return IntentResult(
        intent=intent,
        confidence=confidence,
        raw_input="test",
        mode_hint="APPOINTMENT_MANAGEMENT",
    )


def make_mock_llm(response_text: str = "¿En qué puedo ayudarte?") -> MagicMock:
    """Mock LLM that returns a simple text response with no tool calls."""
    mock = MagicMock()
    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_mode(llm_response: str = "¿En qué puedo ayudarte?") -> AppointmentManagementMode:
    mock_llm = make_mock_llm(llm_response)
    return AppointmentManagementMode(tools=[], llm_client=mock_llm)


def make_state(
    customer_name: str | None = "María",
    customer_id: str | None = "cust-001",
    customer_phone: str = "+34612345678",
    user_message: str = "quiero cancelar mi cita",
    mode_context: dict | None = None,
    current_mode: str = "APPOINTMENT_MANAGEMENT",
    ai_disclosure_sent: bool = True,
) -> dict:
    """Build a ConversationState for AppointmentManagementMode tests."""
    state = create_initial_state("conv-appt-001", customer_phone)
    state["customer_name"] = customer_name
    state["customer_id"] = customer_id
    state["is_first_interaction"] = False
    state["current_mode"] = current_mode
    state["mode_context"] = mode_context or {}
    state["ai_disclosure_sent"] = ai_disclosure_sent  # Avoid disclosure prefix in tests
    # Add a user message so _get_last_user_message finds something
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


def make_agentic_loop_result(
    response_text: str = "Aquí están tus citas.",
    tool_results: dict | None = None,
) -> AgenticLoopResult:
    """Build a mock AgenticLoopResult for use with AsyncMock."""
    return AgenticLoopResult(
        response_text=response_text,
        tool_results=tool_results or {},
    )


# =============================================================================
# 1. Import and Instantiation
# =============================================================================


class TestAppointmentManagementModeInstantiation:
    def test_can_import_and_create(self):
        mode = make_mode()
        assert mode is not None

    def test_mode_name_is_appointment_management(self):
        mode = make_mode()
        assert mode.mode_name == "APPOINTMENT_MANAGEMENT"


# =============================================================================
# 2. Query flow — handle() with intent="check_appointments"
# =============================================================================


class TestQueryFlow:
    """Test that intent=check_appointments sets action=query and calls LLM."""

    @pytest.mark.asyncio
    async def test_check_appointments_intent_sets_action_query(self):
        """
        handle() with intent='check_appointments' → pre-resolver sets ctx.action='query'.
        """
        mode = make_mode("Tus citas son...")
        state = make_state(user_message="cuándo tengo turno", mode_context={})
        intent = make_intent("check_appointments")

        loop_result = make_agentic_loop_result("Tus citas son...")

        with patch.object(mode, "_invoke_create_agent", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = loop_result
            with patch.object(mode, "_build_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                result = await mode.handle(state, intent)

        # Pre-resolver must have set action=query via the intent
        assert mock_loop.called
        # The mode context should contain action='query' in its output
        mode_ctx = result.get("mode_context", {})
        assert mode_ctx.get("action") == "query"

    @pytest.mark.asyncio
    async def test_query_intent_does_not_transition_mode(self):
        """
        Query flow that doesn't complete should stay in APPOINTMENT_MANAGEMENT.
        (no escalation, no completion — normal turn)
        """
        mode = make_mode("Aquí están tus citas.")
        state = make_state(user_message="mis citas", mode_context={})
        intent = make_intent("check_appointments")

        loop_result = make_agentic_loop_result("Aquí están tus citas.")

        with patch.object(mode, "_invoke_create_agent", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = loop_result
            with patch.object(mode, "_build_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                result = await mode.handle(state, intent)

        # No mode transition (no current_mode key → stays in APPOINTMENT_MANAGEMENT)
        assert (
            result.get("current_mode") is None
            or result.get("current_mode") == "APPOINTMENT_MANAGEMENT"
        )
        assert result.get("last_node") == "appointment_management"


# =============================================================================
# 3. Cancel flow — happy path: gate allows cancel_appointment
# =============================================================================


# =============================================================================
# T-39: Architecture guard — no individual tools or closure factory
# =============================================================================


class TestAppointmentManagementModeNoIndividualTools:
    """T-39: Mode must NOT import individual appointment tools or closure factory."""

    def test_no_individual_tools_in_source(self):
        """list_customer_appointments, cancel_appointment, reschedule_appointment
        must NOT be imported as tools in appointment_management_mode source."""
        import inspect
        from agent.modes import appointment_management_mode as _amm

        src = inspect.getsource(_amm)
        for tool_name in (
            "list_customer_appointments",
            "cancel_appointment",
            "reschedule_appointment",
        ):
            assert tool_name not in src, (
                f"{tool_name} found in appointment_management_mode source — "
                "individual tools were consolidated into manage_appointments"
            )

    def test_no_closure_factory_in_source(self):
        """create_appointment_tools must NOT appear in appointment_management_mode source."""
        import inspect
        from agent.modes import appointment_management_mode as _amm

        src = inspect.getsource(_amm)
        assert "create_appointment_tools" not in src, (
            "create_appointment_tools found in appointment_management_mode source — "
            "the closure factory was removed in favor of manage_appointments"
        )

    def test_get_tools_returns_manage_appointments(self):
        """get_tools() must include manage_appointments (the consolidated tool)."""
        mode = make_mode()
        tools = mode.get_tools()
        tool_names = [t.name for t in tools]
        assert "manage_appointments" in tool_names, (
            "manage_appointments not found in get_tools() — "
            "it should be the single consolidated appointment management tool"
        )


# =============================================================================
# 3. Cancel flow — happy path: gate allows manage_appointments(cancel)
# =============================================================================


class TestCancelGateHappyPath:
    """_pre_tool_call allows manage_appointments(action='cancel') when pending_confirmation=True."""

    @pytest.mark.asyncio
    async def test_cancel_allowed_with_pending_confirmation(self):
        """
        pending_confirmation=True + type='cancel' → _pre_tool_call passes through.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=True,
            pending_confirmation_type="cancel",
            selected_appointment_id="appt-uuid-001",
        )
        tool_args = {"action": "cancel", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert not isinstance(result, ToolCallRejection)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_cancel_injects_appointment_id_from_context(self):
        """
        _pre_tool_call injects the appointment_id from ctx, overwriting LLM value.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=True,
            pending_confirmation_type="cancel",
            selected_appointment_id="real-appt-uuid",
        )
        tool_args = {"action": "cancel", "appointment_id": "llm-hallucinated-uuid"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, dict)
        assert result["appointment_id"] == "real-appt-uuid"


# =============================================================================
# 4. Cancel flow — gate blocks when pending_confirmation=False
# =============================================================================


class TestCancelGateBlocks:
    """_pre_tool_call blocks manage_appointments(cancel) when pending_confirmation=False."""

    @pytest.mark.asyncio
    async def test_cancel_blocked_without_pending_confirmation(self):
        """
        pending_confirmation=False → _pre_tool_call returns ToolCallRejection.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=False,
            selected_appointment_id="appt-uuid-001",
        )
        tool_args = {"action": "cancel", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_REQUIRED"
        assert result.name == "manage_appointments"

    @pytest.mark.asyncio
    async def test_cancel_blocked_reason_contains_spanish_message(self):
        """
        Block reason must contain a Spanish instruction for the LLM.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=False,
        )
        tool_args = {"action": "cancel"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, ToolCallRejection)
        # The error message must contain a Spanish guidance phrase
        assert (
            "confirmación" in result.error_message.lower()
            or "confirmar" in result.error_message.lower()
        )

    @pytest.mark.asyncio
    async def test_cancel_blocked_no_ctx(self):
        """When _ctx is None (edge case), manage_appointments(cancel) is blocked with NO_CONTEXT."""
        mode = make_mode()
        mode._ctx = None
        tool_args = {"action": "cancel", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_CONTEXT"


# =============================================================================
# 5. Reschedule flow — gate blocks when type mismatch
# =============================================================================


class TestRescheduleGateMismatch:
    """
    _pre_tool_call blocks manage_appointments(reschedule) when pending_confirmation type mismatches.
    """

    @pytest.mark.asyncio
    async def test_reschedule_blocked_when_confirmation_type_is_cancel(self):
        """
        pending_confirmation=True but pending_confirmation_type='cancel' (mismatch)
        → manage_appointments(reschedule) is blocked.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="reschedule",
            pending_confirmation=True,
            pending_confirmation_type="cancel",  # mismatch
            selected_appointment_id="appt-uuid-001",
            pending_new_slot={"full_datetime": "2026-04-01T10:00:00+01:00"},
        )
        tool_args = {"action": "reschedule", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_REQUIRED"

    @pytest.mark.asyncio
    async def test_reschedule_blocked_without_any_confirmation(self):
        """
        pending_confirmation=False → manage_appointments(reschedule) blocked.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="reschedule",
            pending_confirmation=False,
            selected_appointment_id="appt-uuid-001",
            pending_new_slot={"full_datetime": "2026-04-01T10:00:00+01:00"},
        )
        tool_args = {"action": "reschedule", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "CONFIRMATION_REQUIRED"


# =============================================================================
# 6. Reschedule flow — gate blocks when no pending_new_slot
# =============================================================================


class TestRescheduleGateNoSlot:
    """
    _pre_tool_call blocks manage_appointments(reschedule) when pending_new_slot is empty.
    """

    @pytest.mark.asyncio
    async def test_reschedule_blocked_when_no_new_slot(self):
        """
        pending_confirmation=True + type='reschedule' but pending_new_slot={}
        → manage_appointments(reschedule) blocked with NO_NEW_SLOT.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="reschedule",
            pending_confirmation=True,
            pending_confirmation_type="reschedule",
            selected_appointment_id="appt-uuid-001",
            pending_new_slot={},  # empty slot
        )
        tool_args = {"action": "reschedule", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert isinstance(result, ToolCallRejection)
        assert result.error_code == "NO_NEW_SLOT"

    @pytest.mark.asyncio
    async def test_reschedule_allowed_with_confirmation_and_slot(self):
        """
        pending_confirmation=True + type='reschedule' + pending_new_slot set
        → manage_appointments(reschedule) is allowed.
        """
        mode = make_mode()
        mode._ctx = AppointmentContext(
            action="reschedule",
            pending_confirmation=True,
            pending_confirmation_type="reschedule",
            selected_appointment_id="appt-uuid-001",
            pending_new_slot={"full_datetime": "2026-04-01T10:00:00+01:00"},
        )
        tool_args = {"action": "reschedule", "appointment_id": "appt-uuid-001"}

        result = await mode._pre_tool_call("manage_appointments", tool_args)

        assert not isinstance(result, ToolCallRejection)


# =============================================================================
# 7. 48h escalation — within_window=True → ESCALATION
# =============================================================================


class TestWithinWindowEscalation:
    """When tool returns within_window=True, mode should transition to ESCALATION."""

    @pytest.mark.asyncio
    async def test_cancel_within_window_escalates(self):
        """
        cancel_appointment returns within_window=True → _build_response transitions to ESCALATION.
        """
        mode = make_mode("Tu cita está dentro de las 48 horas.")
        state = make_state(
            user_message="cancelar",
            mode_context={
                "action": "cancel",
                "selected_appointment_id": "appt-uuid-001",
                "selected_appointment_snapshot": {
                    "date_display": "viernes 4 de abril",
                    "time_display": "10:00",
                    "stylist_name": "Ana",
                },
                "pending_confirmation": True,
                "pending_confirmation_type": "cancel",
            },
        )
        intent = make_intent("cancel")

        # Tool result: within_window=True
        loop_result = AgenticLoopResult(
            response_text="Tu cita está dentro de las 48 horas.",
            tool_results={
                "manage_appointments": [
                    {"action": "cancel", "within_window": True, "hours_until": 20}
                ]
            },
        )

        with patch.object(mode, "_invoke_create_agent", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = loop_result
            with patch.object(mode, "_build_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                result = await mode.handle(state, intent)

        assert result.get("current_mode") == "ESCALATION"
        assert result.get("last_node") == "appointment_management"

    @pytest.mark.asyncio
    async def test_reschedule_within_window_escalates(self):
        """
        reschedule_appointment returns within_window=True → ESCALATION.
        """
        mode = make_mode("Reagendado dentro del límite.")
        state = make_state(
            user_message="reagendar",
            mode_context={
                "action": "reschedule",
                "selected_appointment_id": "appt-uuid-001",
                "selected_appointment_snapshot": {
                    "date_display": "martes 1 de abril",
                    "time_display": "11:00",
                },
                "pending_confirmation": True,
                "pending_confirmation_type": "reschedule",
                "pending_new_slot": {"full_datetime": "2026-04-05T10:00:00+01:00"},
            },
        )
        intent = make_intent("reschedule")

        loop_result = AgenticLoopResult(
            response_text="Dentro de 48h.",
            tool_results={
                "manage_appointments": [
                    {"action": "reschedule", "within_window": True, "hours_until": 15}
                ]
            },
        )

        with patch.object(mode, "_invoke_create_agent", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = loop_result
            with patch.object(mode, "_build_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                result = await mode.handle(state, intent)

        assert result.get("current_mode") == "ESCALATION"


# =============================================================================
# 8. Completion — success=True → action_completed → GENERAL
# =============================================================================


class TestActionCompletion:
    """When tool returns success=True, mode should transition to GENERAL."""

    @pytest.mark.asyncio
    async def test_cancel_success_transitions_to_general(self):
        """
        cancel_appointment returns success=True → ctx.action_completed=True → GENERAL.
        """
        mode = make_mode("Tu cita fue cancelada exitosamente.")
        state = make_state(
            user_message="si, confirmo",
            mode_context={
                "action": "cancel",
                "selected_appointment_id": "appt-uuid-001",
                "selected_appointment_snapshot": {"date_display": "jueves 3 de abril"},
                "pending_confirmation": True,
                "pending_confirmation_type": "cancel",
            },
        )
        intent = make_intent("cancel")

        loop_result = AgenticLoopResult(
            response_text="Tu cita fue cancelada exitosamente.",
            tool_results={
                "manage_appointments": [
                    {"action": "cancel", "success": True, "appointment_id": "appt-uuid-001"}
                ]
            },
        )

        with patch.object(mode, "_invoke_create_agent", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = loop_result
            with patch.object(mode, "_build_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                result = await mode.handle(state, intent)

        assert result.get("current_mode") == "GENERAL"
        assert result.get("last_node") == "appointment_management"

    @pytest.mark.asyncio
    async def test_reschedule_success_transitions_to_general(self):
        """
        reschedule_appointment returns success=True → GENERAL.
        """
        mode = make_mode("Tu cita fue reagendada.")
        state = make_state(
            user_message="sí",
            mode_context={
                "action": "reschedule",
                "selected_appointment_id": "appt-uuid-001",
                "selected_appointment_snapshot": {"date_display": "lunes 7 de abril"},
                "pending_confirmation": True,
                "pending_confirmation_type": "reschedule",
                "pending_new_slot": {"full_datetime": "2026-04-07T10:00:00+01:00"},
            },
        )
        intent = make_intent("reschedule")

        loop_result = AgenticLoopResult(
            response_text="Tu cita fue reagendada exitosamente.",
            tool_results={"manage_appointments": [{"action": "reschedule", "success": True}]},
        )

        with patch.object(mode, "_invoke_create_agent", new_callable=AsyncMock) as mock_loop:
            mock_loop.return_value = loop_result
            with patch.object(mode, "_build_messages", new_callable=AsyncMock) as mock_msgs:
                mock_msgs.return_value = []
                result = await mode.handle(state, intent)

        assert result.get("current_mode") == "GENERAL"


# =============================================================================
# 9. Selection pre-resolver
# =============================================================================


class TestAppointmentSelectionPreResolver:
    """_resolve_appointment_selection sets selected_appointment_id from user number."""

    def test_user_sends_number_selects_correct_appointment(self):
        """
        user_message="2", appointments_list has 2 items → selected_appointment_id = index 2.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            appointments_list=[
                {"id": "appt-001", "date_display": "lunes"},
                {"id": "appt-002", "date_display": "martes"},
            ]
        )

        mode._resolve_appointment_selection(ctx, "2")

        assert ctx.selected_appointment_id == "appt-002"
        assert ctx.selected_appointment_snapshot.get("id") == "appt-002"

    def test_user_sends_number_1_selects_first(self):
        """
        user_message="1" → selected_appointment_id = index 1 (first item).
        """
        mode = make_mode()
        ctx = AppointmentContext(
            appointments_list=[
                {"id": "appt-111", "date_display": "miércoles"},
                {"id": "appt-222", "date_display": "jueves"},
            ]
        )

        mode._resolve_appointment_selection(ctx, "1")

        assert ctx.selected_appointment_id == "appt-111"

    def test_no_selection_when_no_appointments_list(self):
        """
        When appointments_list is empty, no selection is made.
        """
        mode = make_mode()
        ctx = AppointmentContext(appointments_list=[])

        mode._resolve_appointment_selection(ctx, "1")

        assert ctx.selected_appointment_id == ""

    def test_no_selection_when_already_selected(self):
        """
        When selected_appointment_id is already set, it's not overwritten.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            selected_appointment_id="already-selected",
            appointments_list=[
                {"id": "appt-001"},
                {"id": "appt-002"},
            ],
        )

        mode._resolve_appointment_selection(ctx, "2")

        assert ctx.selected_appointment_id == "already-selected"

    def test_out_of_range_number_does_not_select(self):
        """
        Number out of range → no selection made.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            appointments_list=[
                {"id": "appt-001"},
            ]
        )

        mode._resolve_appointment_selection(ctx, "5")

        assert ctx.selected_appointment_id == ""


# =============================================================================
# 10. Confirmation pre-resolver
# =============================================================================


class TestConfirmationPreResolver:
    """_resolve_confirmation_state sets/clears pending_confirmation based on user affirmation."""

    def test_si_sets_pending_confirmation(self):
        """
        user_message="sí", pending_confirmation=False, action="cancel",
        selected_appointment_id set → pending_confirmation=True.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=False,
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "sí")

        assert ctx.pending_confirmation is True
        assert ctx.pending_confirmation_type == "cancel"

    def test_dale_sets_pending_confirmation(self):
        """'dale' is an affirmative phrase → pending_confirmation=True."""
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=False,
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "dale")

        assert ctx.pending_confirmation is True

    def test_no_resets_pending_confirmation(self):
        """
        user_message="no", pending_confirmation=True → pending_confirmation reset to False.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=True,
            pending_confirmation_type="cancel",
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "no")

        assert ctx.pending_confirmation is False
        assert ctx.pending_confirmation_type == ""

    def test_no_confirmation_without_selected_appointment(self):
        """
        Even if user says "sí", without selected_appointment_id pending_confirmation stays False.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=False,
            selected_appointment_id="",  # not selected yet
        )

        mode._resolve_confirmation_state(ctx, "sí")

        assert ctx.pending_confirmation is False

    def test_affirmation_with_reschedule_requires_pending_new_slot(self):
        """
        For reschedule, affirmation only works if pending_new_slot is also set.
        """
        mode = make_mode()
        ctx = AppointmentContext(
            action="reschedule",
            pending_confirmation=False,
            selected_appointment_id="appt-001",
            pending_new_slot={},  # no slot set
        )

        mode._resolve_confirmation_state(ctx, "sí")

        assert ctx.pending_confirmation is False

    def test_empty_message_does_nothing(self):
        """Empty user message should not change confirmation state."""
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=False,
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "")

        assert ctx.pending_confirmation is False


# =============================================================================
# 11. Negative pre-resolver
# =============================================================================


class TestNegativePreResolver:
    """_resolve_confirmation_state resets pending_confirmation on negation."""

    def test_mejor_no_resets_pending_confirmation(self):
        """'mejor no' → pending_confirmation reset."""
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=True,
            pending_confirmation_type="cancel",
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "mejor no")

        assert ctx.pending_confirmation is False
        assert ctx.pending_confirmation_type == ""

    def test_no_quiero_resets_pending_confirmation(self):
        """'no quiero' → pending_confirmation reset."""
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=True,
            pending_confirmation_type="cancel",
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "no quiero")

        assert ctx.pending_confirmation is False

    def test_si_when_already_pending_keeps_it_true(self):
        """
        When pending_confirmation is already True and user says "sí",
        it stays True (they're re-confirming).
        """
        mode = make_mode()
        ctx = AppointmentContext(
            action="cancel",
            pending_confirmation=True,
            pending_confirmation_type="cancel",
            selected_appointment_id="appt-001",
        )

        mode._resolve_confirmation_state(ctx, "sí")

        assert ctx.pending_confirmation is True


# =============================================================================
# 12. Action detection from intent
# =============================================================================


class TestActionResolution:
    """_resolve_action_from_intent detects cancel/reschedule/query from intent string."""

    def test_cancel_intent_sets_cancel_action(self):
        mode = make_mode()
        ctx = AppointmentContext()
        intent = make_intent("cancel")

        mode._resolve_action_from_intent(ctx, intent, "quiero cancelar")

        assert ctx.action == "cancel"

    def test_reschedule_intent_sets_reschedule_action(self):
        mode = make_mode()
        ctx = AppointmentContext()
        intent = make_intent("reschedule")

        mode._resolve_action_from_intent(ctx, intent, "reagendar")

        assert ctx.action == "reschedule"

    def test_check_appointments_intent_sets_query_action(self):
        mode = make_mode()
        ctx = AppointmentContext()
        intent = make_intent("check_appointments")

        mode._resolve_action_from_intent(ctx, intent, "cuándo tengo turno")

        assert ctx.action == "query"

    def test_existing_action_preserved(self):
        """Once action is set, it is not overwritten."""
        mode = make_mode()
        ctx = AppointmentContext(action="cancel")
        intent = make_intent("reschedule")

        mode._resolve_action_from_intent(ctx, intent, "reagendar")

        assert ctx.action == "cancel"  # Not changed

    def test_user_message_fallback_detects_cancel(self):
        """If intent doesn't contain cancel keyword, user message is checked."""
        mode = make_mode()
        ctx = AppointmentContext()
        intent = make_intent("ambiguous")

        mode._resolve_action_from_intent(ctx, intent, "quiero cancelar mi turno")

        assert ctx.action == "cancel"


# =============================================================================
# 13. Natural language appointment selection (WS-3)
# =============================================================================


class TestAppointmentNaturalSelection:
    """WS-3: Natural language appointment selection via _resolve_appointment_selection."""

    def _make_ctx_with_appointments(self) -> AppointmentContext:
        ctx = AppointmentContext()
        ctx.appointments_list = [
            {
                "id": "aaa",
                "stylist_name": "Ana",
                "date": "viernes 11",
                "time": "10:00",
                "start_time": "2026-04-11T10:00",
            },
            {
                "id": "bbb",
                "stylist_name": "Pilar",
                "date": "lunes 14",
                "time": "16:30",
                "start_time": "2026-04-14T16:30",
            },
        ]
        return ctx

    def test_digit_selection(self):
        """Backward compat: '1' selects appointments[0]."""
        mode = make_mode()
        ctx = self._make_ctx_with_appointments()

        mode._resolve_appointment_selection(ctx, "1")

        assert ctx.selected_appointment_id == "aaa"

    def test_ordinal_la_primera(self):
        """'la primera' → appointments[0] (first appointment)."""
        mode = make_mode()
        ctx = self._make_ctx_with_appointments()

        mode._resolve_appointment_selection(ctx, "la primera")

        assert ctx.selected_appointment_id == "aaa"

    def test_ordinal_la_segunda(self):
        """'la segunda' → appointments[1]."""
        mode = make_mode()
        ctx = self._make_ctx_with_appointments()

        mode._resolve_appointment_selection(ctx, "la segunda")

        assert ctx.selected_appointment_id == "bbb"

    def test_no_selection_on_empty_message(self):
        """Empty message → no selection made."""
        mode = make_mode()
        ctx = self._make_ctx_with_appointments()

        mode._resolve_appointment_selection(ctx, "")

        assert ctx.selected_appointment_id == ""

    def test_snapshot_populated_on_selection(self):
        """When appointment is selected, selected_appointment_snapshot is also populated."""
        mode = make_mode()
        ctx = self._make_ctx_with_appointments()

        mode._resolve_appointment_selection(ctx, "2")

        assert ctx.selected_appointment_snapshot.get("id") == "bbb"
        assert ctx.selected_appointment_snapshot.get("stylist_name") == "Pilar"
