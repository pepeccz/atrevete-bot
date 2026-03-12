"""
Unit tests for router_node() in agent/graphs/conversation_flow.py — v6.0.

Tests all 8 routing rules without making real LLM or DB calls.
IntentRouter is mocked via patch("agent.graphs.conversation_flow._get_intent_router").

Coverage:
- Rule 1: escalation_triggered=True → always ESCALATION
- Rule 2: error_count >= 3 → ESCALATION (auto-escalation)
- Rule 3: is_first_interaction=True → GREETING
- Rule 3b: customer_name is None → GREETING
- Rule 4: intent=escalate → ESCALATION
- Rule 5: current_mode=BOOKING, intent not cancel/reject → stay BOOKING
- Rule 6: intent=book → BOOKING
- Rule 7: intent=greet (and not in BOOKING) → GREETING
- Rule 8: everything else → GENERAL
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

    # ── Rule 3: is_first_interaction=True ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule3_first_interaction_routes_to_greeting(self):
        """Rule 3: is_first_interaction=True → GREETING."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name="Ana",
            is_first_interaction=True,
            escalation_triggered=False,
            error_count=0,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("book")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        # Short-circuits before intent classification
        mock_get_router.return_value.classify.assert_not_called()

    # ── Rule 3b: customer_name is None ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule3b_customer_name_none_routes_to_greeting(self):
        """Rule 3b: customer_name=None → GREETING (new customer, name unknown)."""
        from agent.graphs.conversation_flow import router_node

        state = _make_state(
            current_mode="GREETING",
            customer_name=None,
            is_first_interaction=False,
            error_count=0,
            escalation_triggered=False,
        )

        with patch("agent.graphs.conversation_flow._get_intent_router") as mock_get_router:
            mock_get_router.return_value = _make_mock_router("ask_info")
            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        mock_get_router.return_value.classify.assert_not_called()

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
