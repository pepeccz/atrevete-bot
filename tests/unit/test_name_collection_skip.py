"""
Unit tests for name-collection-skip: Ensure nameless first-interaction
customers are routed through GREETING regardless of intent, the token
filter is conditional, and the _pre_tool_call gate blocks book() without
a real customer name.

Covers REQ-NCS-1 through REQ-NCS-7 and Scenarios S1-S4.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.state.schemas import create_initial_state


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_state(
    *,
    customer_name: str | None = None,
    is_first_interaction: bool = True,
    current_mode: str = "GREETING",
    user_message: str = "Hola quiero una cita para corte",
    pending_whatsapp_name: str | None = None,
    mode_context: dict | None = None,
) -> dict:
    state = create_initial_state("conv-ncs-test", "+34600000111")
    state["customer_name"] = customer_name
    state["is_first_interaction"] = is_first_interaction
    state["current_mode"] = current_mode
    state["pending_whatsapp_name"] = pending_whatsapp_name
    state["messages"] = [
        {"role": "user", "content": user_message, "timestamp": "2026-03-24T10:00:00"}
    ]
    state["mode_context"] = mode_context or {}
    return state


def _make_intent_result(intent: str = "book", confidence: float = 0.9):
    from agent.routing.intent_router import IntentResult

    return IntentResult(
        intent=intent,
        confidence=confidence,
        raw_input="test",
        mode_hint=None,
    )


# ── T8: Router Tests (REQ-NCS-1, NCS-2, NCS-7) ─────────────────────────────


class TestRouterRule4:
    """Rule 4: nameless first-interaction customers route to GREETING."""

    @pytest.mark.asyncio
    async def test_book_intent_routes_to_greeting_when_nameless(self):
        """S1: intent=book, nameless first interaction → GREETING (REQ-NCS-1)."""
        state = _make_state(
            customer_name=None,
            is_first_interaction=True,
            current_mode="GENERAL",
            user_message="Quiero reservar un corte",
        )
        mock_router = AsyncMock()
        mock_router.classify = AsyncMock(return_value=_make_intent_result("book"))

        with patch(
            "agent.graphs.conversation_flow._get_intent_router",
            return_value=mock_router,
        ):
            from agent.graphs.conversation_flow import router_node

            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["deferred_intent"] == "book"

    @pytest.mark.asyncio
    async def test_greet_intent_routes_to_greeting_when_nameless(self):
        """Pure greet still routes to GREETING (regression check)."""
        state = _make_state(
            customer_name=None,
            is_first_interaction=True,
            current_mode="GENERAL",
            user_message="Hola!",
        )
        mock_router = AsyncMock()
        mock_router.classify = AsyncMock(return_value=_make_intent_result("greet"))

        with patch(
            "agent.graphs.conversation_flow._get_intent_router",
            return_value=mock_router,
        ):
            from agent.graphs.conversation_flow import router_node

            result = await router_node(state)

        assert result["current_mode"] == "GREETING"
        assert result["mode_context"]["deferred_intent"] == "greet"

    @pytest.mark.asyncio
    async def test_returning_customer_skips_rule4(self):
        """S4: returning customer with name → Rule 4 is skipped (REQ-NCS-7)."""
        state = _make_state(
            customer_name="Laura",
            is_first_interaction=False,
            current_mode="GENERAL",
            user_message="Quiero una cita",
        )
        mock_router = AsyncMock()
        mock_router.classify = AsyncMock(return_value=_make_intent_result("book"))

        with patch(
            "agent.graphs.conversation_flow._get_intent_router",
            return_value=mock_router,
        ):
            from agent.graphs.conversation_flow import router_node

            result = await router_node(state)

        # Should go to BOOKING (Rule 8), NOT GREETING
        assert result["current_mode"] == "BOOKING"

    @pytest.mark.asyncio
    async def test_deferred_intent_set_in_mode_context(self):
        """T2: deferred_intent is present in greeting context (REQ-NCS-2)."""
        state = _make_state(
            customer_name=None,
            is_first_interaction=True,
            current_mode="GENERAL",
            user_message="Necesito un corte y color",
        )
        mock_router = AsyncMock()
        mock_router.classify = AsyncMock(return_value=_make_intent_result("book", 0.95))

        with patch(
            "agent.graphs.conversation_flow._get_intent_router",
            return_value=mock_router,
        ):
            from agent.graphs.conversation_flow import router_node

            result = await router_node(state)

        ctx = result["mode_context"]
        assert "deferred_intent" in ctx
        assert ctx["deferred_intent"] == "book"
        assert ctx["last_intent"] == "book"


# ── T9: Token Filter Tests (REQ-NCS-4) ──────────────────────────────────────


class TestTokenFilter:
    """greeting_mode.py token filter conditionality."""

    def _make_mode(self):
        from agent.modes.greeting_mode import GreetingMode

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock()
        return GreetingMode(tools=[], llm_client=mock_llm)

    @pytest.mark.asyncio
    async def test_allows_name_ask_when_no_name_source(self):
        """S1: No name source → LLM CAN ask for name (REQ-NCS-4)."""
        mode = self._make_mode()
        state = _make_state(
            customer_name=None,
            pending_whatsapp_name=None,
            user_message="Hola quiero reservar",
        )
        state["mode_context"]["last_intent"] = "book"

        response = "¡Hola! ¿A nombre de quién agendo? 😊"

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=True),
            patch.object(
                mode, "_build_layered_messages", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(mode, "_call_llm", new_callable=AsyncMock) as mock_call,
            patch.object(mode, "_extract_response_text", return_value=response),
        ):
            mock_msg = MagicMock()
            mock_msg.content = response
            mock_call.return_value = mock_msg

            result = await mode._render_layered_response(
                state=state,
                mode_context=state["mode_context"],
                step_name="greeting",
                fallback_response="¡Hola! ¿En qué puedo ayudarte?",
            )

        # Should NOT be replaced by fallback — name question is allowed
        assert "nombre" in result.lower() or "agendo" in result.lower()
        assert result != "¡Hola! ¿En qué puedo ayudarte?"

    @pytest.mark.asyncio
    async def test_rejects_name_ask_when_name_source_exists(self):
        """S2: Name source exists → LLM MUST NOT ask for name (REQ-NCS-7)."""
        mode = self._make_mode()
        state = _make_state(
            customer_name=None,
            pending_whatsapp_name="María",
            user_message="Hola quiero reservar",
        )
        state["mode_context"]["last_intent"] = "book"

        response = "¡Hola! ¿Cómo te llamas?"
        fallback = "¡Hola! ¿En qué puedo ayudarte?"

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=True),
            patch.object(
                mode, "_build_layered_messages", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(mode, "_call_llm", new_callable=AsyncMock) as mock_call,
            patch.object(mode, "_extract_response_text", return_value=response),
        ):
            mock_msg = MagicMock()
            mock_msg.content = response
            mock_call.return_value = mock_msg

            result = await mode._render_layered_response(
                state=state,
                mode_context=state["mode_context"],
                step_name="greeting",
                fallback_response=fallback,
            )

        # Should be replaced by fallback
        assert result == fallback

    @pytest.mark.asyncio
    async def test_rejects_name_ask_when_customer_name_exists(self):
        """Name already in customer_name → fallback (REQ-NCS-7)."""
        mode = self._make_mode()
        state = _make_state(
            customer_name="Laura",
            pending_whatsapp_name=None,
            user_message="Hola!",
        )

        response = "¡Hola! ¿Cuál es tu nombre?"
        fallback = "¡Hola! ¿En qué puedo ayudarte?"

        with (
            patch.object(mode, "_use_optimized_prompts", return_value=True),
            patch.object(
                mode, "_build_layered_messages", new_callable=AsyncMock, return_value=[]
            ),
            patch.object(mode, "_call_llm", new_callable=AsyncMock) as mock_call,
            patch.object(mode, "_extract_response_text", return_value=response),
        ):
            mock_msg = MagicMock()
            mock_msg.content = response
            mock_call.return_value = mock_msg

            result = await mode._render_layered_response(
                state=state,
                mode_context=state["mode_context"],
                step_name="greeting",
                fallback_response=fallback,
            )

        assert result == fallback


# ── T10: _pre_tool_call Gate Tests (REQ-NCS-5, NCS-6) ───────────────────────


class TestPreToolCallGate:
    """booking_mode_v7 _pre_tool_call rejects book() without real name."""

    def _make_booking_mode(self):
        from agent.modes.booking_mode_v7 import BookingModeV7

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock()
        return BookingModeV7(tools=[], llm_client=mock_llm)

    def _make_ctx(self, customer_name=None, customer_id=None):
        from agent.modes.booking_context_v7 import BookingContextV7

        return BookingContextV7(
            customer_name=customer_name,
            customer_id=customer_id,
        )

    @pytest.mark.asyncio
    async def test_rejects_book_when_customer_name_none(self):
        """S3: customer_name=None → sentinel error (REQ-NCS-5)."""
        mode = self._make_booking_mode()
        mode._ctx = self._make_ctx(customer_name=None, customer_id="cust-123")

        result = await mode._pre_tool_call("book", {"slot_index": 1})

        assert "ERROR:pregunta_el_nombre_del_cliente_primero" in result["customer_id"]

    @pytest.mark.asyncio
    async def test_rejects_book_when_customer_name_is_cliente(self):
        """S3: customer_name='Cliente' → sentinel error (REQ-NCS-5)."""
        mode = self._make_booking_mode()
        mode._ctx = self._make_ctx(customer_name="Cliente", customer_id="cust-123")

        result = await mode._pre_tool_call("book", {"slot_index": 1})

        assert "ERROR:pregunta_el_nombre_del_cliente_primero" in result["customer_id"]

    @pytest.mark.asyncio
    async def test_allows_book_when_customer_name_real(self):
        """S4: customer_name='Laura' → allowed through (REQ-NCS-5 inverse)."""
        mode = self._make_booking_mode()
        mode._ctx = self._make_ctx(customer_name="Laura", customer_id="cust-456")

        result = await mode._pre_tool_call("book", {"slot_index": 1})

        # Should NOT contain the sentinel
        assert result.get("customer_id") != "ERROR:pregunta_el_nombre_del_cliente_primero"

    @pytest.mark.asyncio
    async def test_allows_non_book_tools_regardless_of_name(self):
        """REQ-NCS-6: non-book tools pass through regardless."""
        mode = self._make_booking_mode()
        mode._ctx = self._make_ctx(customer_name=None, customer_id=None)

        result = await mode._pre_tool_call("check_availability", {"date": "2026-03-25"})

        # Should return unchanged args (non-book tools bypass _pre_tool_call)
        assert result == {"date": "2026-03-25"}
