"""
Unit tests for router_node() in agent/graphs/conversation_flow.py — v6.0.

Tests all 8 routing rules without making real LLM or DB calls.
IntentRouter is mocked via patch("agent.graphs.conversation_flow._get_intent_router").

Coverage:
- Rule 1: escalation_triggered=True → always ESCALATION
- Rule 2: error_count >= 3 → ESCALATION (auto-escalation)
- Rule 3: pending greeting subflow stays in GREETING
- Rule 4a: first-turn/unknown-customer book intent → BOOKING
- Rule 4b: first-turn/unknown-customer non-book intent → GREETING
- Rule 5: intent=escalate → ESCALATION
- Rule 6: current_mode=BOOKING, intent not cancel/reject → stay BOOKING
- Rule 7: intent=book → BOOKING
- Rule 8: intent=greet (and not in BOOKING) → GREETING
- Rule 9: everything else → GENERAL
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# ============================================================================
# Helpers
# ============================================================================


def _make_state(
    current_mode: str = "GENERAL",
    customer_name: str | None = "Ana",
    is_first_interaction: bool = False,
    error_count: int = 0,
    escalation_triggered: bool = False,
    user_message: str = "Hola",
) -> dict:
    """Build a minimal ConversationState for router_node tests."""
    state = create_initial_state("conv-test-001", "+34600000001")
    state["current_mode"] = current_mode
    state["customer_name"] = customer_name
    state["is_first_interaction"] = is_first_interaction
    state["error_count"] = error_count
    state["escalation_triggered"] = escalation_triggered
    # Add a user message to the messages list so router_node can find it
    state["messages"] = [{"role": "user", "content": user_message, "timestamp": "2026-01-01T00:00:00"}]
    state["user_message"] = user_message
    return state


def _make_mock_router(intent: str, confidence: float = 0.9) -> MagicMock:
    """Create a mock IntentRouter that returns the given intent."""
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


# ============================================================================
# Tests
# ============================================================================


class TestRouterNodeRules:
    """Tests for all 8 routing rules in router_node()."""

    # ── Rule 1: escalation_triggered=True ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule1_escalation_triggered_routes_to_escalation(self):
        """Rule 1: If escalation_triggered is True, always go to ESCALATION."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            escalation_triggered=True,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"
        # Intent router should NOT be called — rule 1 short-circuits
        mock_get_router.return_value.classify.assert_not_called()

    @pytest.mark.asyncio
    async def test_rule1_escalation_triggered_overrides_all_other_signals(self):
        """Rule 1 takes priority even if is_first_interaction=False and name is set."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Carlos",
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=True,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"

    # ── Rule 2: error_count >= 3 ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule2_error_count_3_triggers_auto_escalation(self):
        """Rule 2: error_count >= 3 → auto-escalation to ESCALATION."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            customer_name="Carlos",
            is_first_interaction=False,
            error_count=3,
            escalation_triggered=False,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"
        mock_get_router.return_value.classify.assert_not_called()

    @pytest.mark.asyncio
    async def test_rule2_error_count_above_threshold_escalates(self):
        """Rule 2: error_count > 3 also escalates."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            customer_name="Pedro",
            is_first_interaction=False,
            error_count=5,
            escalation_triggered=False,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"

    @pytest.mark.asyncio
    async def test_rule2_error_count_2_does_not_escalate(self):
        """Rule 2: error_count=2 is below threshold — does NOT auto-escalate."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            customer_name="Ana",
            is_first_interaction=False,
            error_count=2,
            escalation_triggered=False,
            user_message="quiero una cita",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] != "ESCALATION"

    # ── Rule 4a/4b: first turn / unknown customer ─────────────────────────────

    @pytest.mark.asyncio
    async def test_rule4a_first_interaction_booking_routes_to_booking(self):
        """First interaction with booking intent should bypass GREETING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            escalation_triggered=False,
            error_count=0,
            user_message="Hola, quiero agendar una cita",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"
        assert result["mode_context"]["is_first_interaction"] is True
        assert result["mode_context"]["last_intent"] == "book"
        mock_get_router.return_value.classify.assert_called_once()

    # ── Rule 4b: first turn / unknown customer fallback to GREETING ───────────

    @pytest.mark.asyncio
    async def test_rule4b_first_interaction_non_booking_routes_to_greeting(self):
        """First interaction without booking intent should preserve GREETING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            error_count=0,
            escalation_triggered=False,
            user_message="Hola, buenos dias",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("greet")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["last_intent"] == "greet"
        mock_get_router.return_value.classify.assert_called_once()

    @pytest.mark.asyncio
    async def test_rule4b_customer_name_none_non_booking_routes_to_greeting(self):
        """Unknown customer outside BOOKING still goes to GREETING after classification."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name=None,
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
            user_message="Necesito saber horarios",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["last_intent"] == "ask_info"
        mock_get_router.return_value.classify.assert_called_once()

    @pytest.mark.asyncio
    async def test_rule3_pending_greeting_subflow_classifies_and_stays_in_greeting(self):
        """Pending GREETING context must keep ownership of confirmation replies."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=False,
            user_message="sí",
        )
        state["mode_context"] = {
            "greeting_step": "confirm_suggested_name",
            "suggested_name": "Pepe",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("confirm")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["greeting_step"] == "confirm_suggested_name"
        assert result["mode_context"]["last_intent"] == "confirm"
        mock_get_router.return_value.classify.assert_called_once()

    @pytest.mark.asyncio
    async def test_rule4b_first_turn_classification_error_falls_back_to_greeting(self):
        """Classification failures on first turn must fail closed to GREETING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            error_count=0,
            escalation_triggered=False,
            user_message="Hola",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value.classify = AsyncMock(side_effect=Exception("LLM timeout"))
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["last_intent"] == "ambiguous"
        assert result["mode_context"]["last_intent_confidence"] == 0.0

    # ── Rule 4: intent=escalate ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule4_escalate_intent_routes_to_escalation(self):
        """Rule 4: intent=escalate → ESCALATION."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="quiero hablar con una persona",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("escalate")
            result = await router_node(state)

        assert result["current_mode"] == "ESCALATION"

    # ── Rule 5: current_mode=BOOKING, intent not cancel/reject ────────────────

    @pytest.mark.asyncio
    async def test_rule5_booking_mode_stays_in_booking_on_confirm(self):
        """Rule 5: In BOOKING mode with confirm intent → stay in BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Pedro",
            is_first_interaction=False,
            error_count=0,
            user_message="sí, confirmo",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("confirm")
            result = await router_node(state)

        # Mode should still be BOOKING (either set or not changed — the node returns
        # mode_context update without changing current_mode when staying in BOOKING)
        # When staying in BOOKING, router_node doesn't set current_mode in result
        # but the state's current_mode remains BOOKING via reducer
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    @pytest.mark.asyncio
    async def test_rule5_booking_mode_stays_in_booking_on_ambiguous(self):
        """Rule 5: In BOOKING with ambiguous intent → stay in BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="el martes estaría bien",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ambiguous")
            result = await router_node(state)

        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    # ── Rule 6: intent=book ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule6_book_intent_routes_to_booking(self):
        """Rule 6: intent=book → BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="quiero reservar una cita",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"

    # ── Rule 7: intent=greet (not in BOOKING) ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule7_greet_intent_from_general_routes_to_greeting(self):
        """Rule 7: greet intent when not in BOOKING → GREETING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="hola de nuevo",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("greet")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"

    @pytest.mark.asyncio
    async def test_rule7_greet_intent_in_booking_stays_in_booking(self):
        """Rule 7 exception: greet in BOOKING → Rule 5 takes over, stay in BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="hola",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("greet")
            result = await router_node(state)

        # Rule 5 applies first: BOOKING mode + not cancel/reject → stay BOOKING
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    # ── Rule 8: everything else → GENERAL ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule8_ask_info_routes_to_general(self):
        """Rule 8: ask_info intent → GENERAL."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="cuánto cuesta el corte de pelo",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # For ask_info in GENERAL: target_mode == current_mode → no mode update returned
        # router_node returns mode_context update only (no current_mode key)
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "GENERAL"

    @pytest.mark.asyncio
    async def test_rule8_ambiguous_routes_to_general(self):
        """Rule 8: ambiguous intent → GENERAL (default fallback)."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="mmm no sé",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ambiguous", confidence=0.3)
            result = await router_node(state)

        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "GENERAL"

    @pytest.mark.asyncio
    async def test_rule8_confirm_outside_booking_routes_to_general(self):
        """Rule 8: confirm intent when NOT in BOOKING → GENERAL."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            error_count=0,
            user_message="sí, exacto",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("confirm")
            result = await router_node(state)

        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "GENERAL"

    # ── Result structure sanity checks ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_router_node_always_sets_last_node(self):
        """router_node must always include last_node='router' in result."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            customer_name="Ana",
            is_first_interaction=False,
            escalation_triggered=True,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router"):
            result = await router_node(state)

        assert result.get("last_node") == "router"

    @pytest.mark.asyncio
    async def test_router_node_result_is_dict(self):
        """router_node must return a dict (partial state update)."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            customer_name="Ana",
            is_first_interaction=False,
            user_message="quiero reservar",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert isinstance(result, dict)


# ============================================================================
# Regression tests — Bug 1B: Router Rule 4 mid-booking guard
# ============================================================================


class TestRule4MidBookingGuard:
    """
    Regression tests for Bug 1B fix.

    Before fix: Rule 4 fired for ANY state where customer_name=None,
    interrupting mid-booking turns and sending the user back to GREETING.

    After fix: Rule 4 only fires if NOT already in BOOKING mode.
    """

    @pytest.mark.asyncio
    async def test_rule4_does_not_fire_when_in_booking_mode(self):
        """
        BUG-1B REGRESSION: Rule 4 must NOT route to GREETING when in BOOKING with
        customer_name=None (anonymous guest mid-booking scenario).

        Old (buggy) behavior: `not customer_name` alone (without mode guard)
        would trigger GREETING, interrupting mid-booking turns.

        New (correct) behavior: the guard `current_mode != "BOOKING"` protects
        against this so mid-booking turns with unknown customer are not interrupted.

        Note: is_first_interaction=False is used here since in a real mid-booking
        scenario the user has already interacted (first turn was the booking intent).
        """
        from agent.graphs.conversation_flow import router_node

        # Exact bug condition: BOOKING mode + no customer name + NOT first interaction
        state = _make_state(
            current_mode="BOOKING",
            customer_name=None,
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
            user_message="quiero corte caballero",
        )
        # booking step already set — mid-booking scenario
        state["mode_context"] = {
            "booking_step": "service_selection",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        # Must NOT have routed to GREETING
        returned_mode = result.get("current_mode")
        assert returned_mode != "GREETING", (
            "Bug 1B regression: router interrupted mid-booking turn and sent to GREETING"
        )

    @pytest.mark.asyncio
    async def test_rule4_does_not_fire_when_booking_customer_name_none(self):
        """
        BUG-1B REGRESSION: customer_name=None in BOOKING mode (e.g. anonymous guest
        flow) must not trigger Rule 4. The is_first_interaction=False variant.
        """
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name=None,
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
            user_message="corte de pelo para caballero",
        )
        state["mode_context"] = {
            "booking_step": "slot_selection",
            "service_name": "Corte Caballero",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("confirm")
            result = await router_node(state)

        returned_mode = result.get("current_mode")
        assert returned_mode != "GREETING", (
            "Bug 1B regression: customer_name=None in BOOKING caused GREETING redirect"
        )

    @pytest.mark.asyncio
    async def test_rule4_fires_for_genuinely_new_customer(self):
        """
        Rule 4 still correctly fires for a brand-new customer outside BOOKING.

        is_first_interaction=True AND current_mode=GREETING → must route to GREETING.
        """
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            error_count=0,
            escalation_triggered=False,
            user_message="hola",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("greet")
            result = await router_node(state)

        assert result.get("current_mode") == "GREETING"

    @pytest.mark.asyncio
    async def test_rule4_fires_for_general_mode_customer_name_none(self):
        """
        Rule 4 still fires when customer_name=None and NOT in BOOKING mode.

        current_mode=GENERAL + customer_name=None → redirect to GREETING (correct).
        """
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name=None,
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
            user_message="hola",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        assert result.get("current_mode") == "GREETING"


# ============================================================================
# Regression tests — Bug 1C: Router Rule 7 no __reset__ in BOOKING
# ============================================================================


class TestRule7NoResetInBooking:
    """
    Regression tests for Bug 1C fix.

    Before fix: Rule 7 (book intent) always called transition_mode() which
    sends __reset__=True, wiping mode_context even when already in BOOKING.

    After fix: When already in BOOKING + book intent, Rule 7 returns the
    same shape as Rule 6 (no __reset__), preserving booking_step and other
    mid-booking context.
    """

    @pytest.mark.asyncio
    async def test_rule7_does_not_reset_mode_context_when_in_booking(self):
        """
        BUG-1C REGRESSION: book intent while already in BOOKING must NOT reset
        mode_context (which would wipe booking_step, service_name, etc.).

        Before fix: transition_mode() sent __reset__=True → all booking context lost.
        After fix: same as Rule 6 shape → mode_context preserved via merge_dicts.
        """
        from agent.graphs.conversation_flow import router_node

        booking_context = {
            "booking_step": "slot_selection",
            "service_name": "Corte Caballero",
            "service_id": "svc-caballero-001",
        }

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Pedro",
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
            user_message="quiero reservar",
        )
        state["mode_context"] = booking_context

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        # The router must NOT return __reset__=True in mode_context
        returned_mc = result.get("mode_context", {})
        assert not returned_mc.get("__reset__"), (
            "Bug 1C regression: __reset__=True found in mode_context — "
            "booking context would be wiped"
        )

        # booking_step and service_name must be preserved in the result
        # (router returns only intent_data update, not the full context,
        # so we check there's no __reset__ and no active wipe)
        assert "__reset__" not in returned_mc

    @pytest.mark.asyncio
    async def test_rule7_book_intent_from_booking_does_not_change_mode(self):
        """
        BUG-1C REGRESSION: book intent while in BOOKING must not change current_mode.

        The result should either omit current_mode (stays via state reducer)
        or explicitly set it to BOOKING — never transition_mode shape.
        """
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Maria",
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
            user_message="sí, quiero reservar una cita",
        )
        state["mode_context"] = {
            "booking_step": "stylist_selection",
            "service_name": "Mechas",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        # Mode must stay BOOKING (either None/omitted or explicitly BOOKING)
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING", (
            f"Bug 1C regression: book intent in BOOKING changed mode to {returned_mode!r}"
        )

        # Critically: must not carry __reset__ which would wipe service_name, booking_step
        returned_mc = result.get("mode_context", {})
        assert "__reset__" not in returned_mc


class TestBookingDigressions:
    """Coverage for BOOKING -> GENERAL digressions and BOOKING re-entry restore."""

    @pytest.mark.asyncio
    async def test_ask_info_digression_preserves_booking_draft(self):
        """Phase 2 (booking-flow-resilience): with active booking_step, unrelated
        ask_info stays in BOOKING via inertia guard. Only exit phrases leave."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            is_first_interaction=False,
            user_message="que productos usan para el alisado",
        )
        state["mode_context"] = {
            "booking_step": "slot_selection",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Maria",
            "selected_slot": {"start_time": "2026-03-20T10:00:00+01:00"},
            "slot_summary": "20/03 10:00",
            "notes": None,
            "pending_cancel_context": None,
            "candidate_services": [{"id": "svc-1", "name": "Cortar"}],
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Booking inertia: stays in BOOKING (no exit phrase)
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    @pytest.mark.asyncio
    async def test_book_reentry_restores_saved_booking_draft(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Ana",
            is_first_interaction=False,
            user_message="dale, volvamos con el turno",
        )
        state["draft_contexts"] = {
            "BOOKING": {
                "booking_step": "stylist_selection",
                "service_id": "svc-1",
                "service_name": "Cortar",
                "stylist_id": "sty-1",
                "stylist_name": "Maria",
            }
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"
        assert result["mode_context"]["booking_step"] == "stylist_selection"
        assert result["mode_context"]["service_id"] == "svc-1"
        assert result["mode_context"]["stylist_id"] == "sty-1"
        assert result["mode_context"]["last_intent"] == "book"

    @pytest.mark.asyncio
    async def test_general_recommendation_confirmation_carries_service_into_booking(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Luis",
            is_first_interaction=False,
            user_message="1",
        )
        state["mode_context"] = {
            "last_intent": "ask_info",
            "general_booking_handoff": {
                "resolved_service": {
                    "id": "svc-caballero",
                    "name": "Corte Caballero",
                    "category": "Peluquería",
                    "duration_minutes": 30,
                    "family": "haircut",
                }
            },
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"
        assert result["mode_context"]["service_id"] == "svc-caballero"
        assert result["mode_context"]["service_name"] == "Corte Caballero"
        assert result["mode_context"]["service_duration_minutes"] == 30
        assert result["mode_context"]["last_intent"] == "book"


class TestFirstTurnRouterExamples:
    """Concrete first-turn routing examples for the routing fix."""

    @pytest.mark.asyncio
    async def test_first_turn_quiero_agendar_routes_to_booking(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            user_message="quiero agendar",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_first_turn_hola_routes_to_greeting(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            user_message="hola",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("greet")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["last_intent"] == "greet"

    @pytest.mark.asyncio
    async def test_first_turn_cancelar_cita_currently_falls_back_to_greeting(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            user_message="cancelar cita",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("cancel")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["last_intent"] == "cancel"

    @pytest.mark.asyncio
    async def test_first_turn_ambiguous_routes_to_greeting_safe_default(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            user_message="mmm",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ambiguous", confidence=0.2)
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["last_intent"] == "ambiguous"

    @pytest.mark.asyncio
    async def test_first_turn_quiero_reservar_routes_to_booking(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=True,
            user_message="quiero reservar",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_returning_customer_agendar_routes_to_booking(self):
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GENERAL",
            customer_name="Carlos",
            is_first_interaction=False,
            user_message="agendar",
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "BOOKING"


# ============================================================================
# Tests for _is_booking_related_query() helper
# ============================================================================


class TestIsBookingRelatedQuery:
    """Unit tests for the _is_booking_related_query() helper."""

    def test_cuales_tienes_disponibles_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("Cuáles tienes disponibles?") is True

    def test_que_estilistas_hay_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Qué estilistas hay?") is True

    def test_que_horarios_teneis_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Qué horarios tenéis?") is True

    def test_cuanto_cuesta_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Cuánto cuesta el corte?") is True

    def test_cuando_hay_hueco_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Cuándo hay hueco?") is True

    def test_manana_por_la_tarde_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Hay algo mañana por la tarde?") is True

    def test_donde_estais_is_not_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Dónde estáis?") is False

    def test_teneis_parking_is_not_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Tenéis parking?") is False

    def test_empty_string_is_not_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("") is False

    def test_cuanto_dura_is_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("¿Cuánto dura el corte?") is True

    def test_que_productos_usan_is_not_booking_related(self):
        from agent.graphs.conversation_flow import _is_booking_related_query

        assert _is_booking_related_query("que productos usan para el alisado") is False


# ============================================================================
# Tests for Rule 6 booking-related guard — stays in BOOKING or digresses
# ============================================================================


class TestRule6BookingRelatedGuard:
    """Tests for Rule 6 booking-related ask_info guard."""

    @pytest.mark.asyncio
    async def test_rule6_booking_related_ask_info_stays_in_booking(self):
        """ask_info about stylists during BOOKING should stay in BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            is_first_interaction=False,
            user_message="¿Qué estilistas hay disponibles?",
        )
        state["mode_context"] = {
            "booking_step": "stylist_selection",
            "service_id": "svc-1",
            "service_name": "Cortar",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Must stay in BOOKING (no current_mode change or explicitly BOOKING)
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING", (
            f"Booking-related ask_info should stay in BOOKING, got {returned_mode!r}"
        )
        assert result["mode_context"]["last_intent"] == "ask_info"
        # Must NOT have draft_contexts (no digression happened)
        assert "draft_contexts" not in result

    @pytest.mark.asyncio
    async def test_rule6_horarios_during_booking_stays_in_booking(self):
        """ask_info about schedules during BOOKING stays in BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Carlos",
            is_first_interaction=False,
            user_message="¿Qué horarios tenéis mañana?",
        )
        state["mode_context"] = {
            "booking_step": "slot_selection",
            "service_id": "svc-2",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"
        assert "draft_contexts" not in result

    @pytest.mark.asyncio
    async def test_rule6_precio_during_booking_stays_in_booking(self):
        """ask_info about price during BOOKING stays in BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Maria",
            is_first_interaction=False,
            user_message="¿Cuánto cuesta el corte?",
        )
        state["mode_context"] = {
            "booking_step": "service_selection",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    @pytest.mark.asyncio
    async def test_rule6_unrelated_ask_info_with_active_booking_stays_via_inertia(self):
        """Phase 2: ask_info about unrelated topic + active booking_step → stays BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            is_first_interaction=False,
            user_message="¿Dónde estáis ubicados?",
        )
        state["mode_context"] = {
            "booking_step": "slot_selection",
            "service_id": "svc-1",
            "service_name": "Cortar",
            "stylist_id": "sty-1",
            "stylist_name": "Maria",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Booking inertia keeps user in BOOKING
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    @pytest.mark.asyncio
    async def test_rule6_product_question_with_active_booking_stays_via_inertia(self):
        """Phase 2: ask_info about products + active booking_step → stays BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Ana",
            is_first_interaction=False,
            user_message="que productos usan para el alisado",
        )
        state["mode_context"] = {
            "booking_step": "slot_selection",
            "service_id": "svc-1",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Booking inertia keeps user in BOOKING
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"

    @pytest.mark.asyncio
    async def test_rule6_teneis_parking_with_active_booking_stays_via_inertia(self):
        """Phase 2: ask_info about parking + active booking_step → stays BOOKING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="BOOKING",
            customer_name="Pedro",
            is_first_interaction=False,
            user_message="¿Tenéis parking?",
        )
        state["mode_context"] = {
            "booking_step": "service_selection",
        }

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        # Booking inertia keeps user in BOOKING
        returned_mode = result.get("current_mode")
        assert returned_mode is None or returned_mode == "BOOKING"
