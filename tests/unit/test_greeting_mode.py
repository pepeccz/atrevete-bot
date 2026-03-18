"""
Unit tests for agent/modes/greeting_mode.py — GreetingMode (customer-name-handling refactor).

Coverage:
- Anti-loop guarantee: customer_name already set → immediate GENERAL transition (name-free)
- New customer flow: create customer silently with pending_whatsapp_name → GENERAL
- New customer without sender_name: create customer without name → GENERAL
- Name-free responses: NO customer name appears in any response
- No name extraction: _heuristic_extract and _extract_name are REMOVED

All LLM calls are mocked — tests do NOT require a real LLM.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.modes.greeting_mode import (
    GreetingMode,
    _WELCOME_NEW,
    _WELCOME_RETURNING,
)
from agent.routing.intent_router import IntentResult
from agent.state.schemas import create_initial_state


# =============================================================================
# Helpers
# =============================================================================


def make_intent(intent: str = "greet", confidence: float = 0.9) -> IntentResult:
    return IntentResult(intent=intent, confidence=confidence, raw_input="test", mode_hint="GREETING")


def make_mock_llm(response_content: str = "¡Hola! ¿En qué puedo ayudarte?") -> AsyncMock:
    """Build a mock LLM that returns a simple content string."""
    mock = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = response_content
    mock.ainvoke = AsyncMock(return_value=mock_response)
    mock.bind_tools = MagicMock(return_value=mock)
    return mock


def make_greeting_mode(llm_response: str = "¡Hola! ¿En qué puedo ayudarte?") -> GreetingMode:
    mock_llm = make_mock_llm(llm_response)
    return GreetingMode(tools=[], llm_client=mock_llm)


# =============================================================================
# Anti-loop guarantee (returning customer)
# =============================================================================


class TestGreetingModeReturningCustomer:
    """
    Verify the anti-loop guarantee:
    If customer_name is already set in state, GreetingMode MUST
    transition to GENERAL immediately with a NAME-FREE greeting.
    """

    @pytest.mark.asyncio
    async def test_customer_name_set_transitions_to_general(self):
        """Core anti-loop: customer_name present → current_mode becomes GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Juan"

        result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_returning_customer_greeting_does_not_contain_name(self):
        """Returning customer greeting must NOT contain the customer's name."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "María"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "María" not in combined_content

    @pytest.mark.asyncio
    async def test_returning_customer_does_not_ask_for_name(self):
        """No message should ask for name when customer is known."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Carlos"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "¿Con quién" not in combined_content
        assert "nombre" not in combined_content.lower()
        assert "llamas" not in combined_content.lower()

    @pytest.mark.asyncio
    async def test_returning_customer_sets_previous_mode(self):
        """Mode transition should record GREETING as previous_mode."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Ana"
        state["current_mode"] = "GREETING"

        result = await mode.handle(state, make_intent())

        assert result.get("previous_mode") == "GREETING"

    @pytest.mark.asyncio
    async def test_returning_customer_clears_user_message(self):
        """user_message must be set to None after processing."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-001", "+34612345678")
        state["customer_name"] = "Pedro"

        result = await mode.handle(state, make_intent())

        assert result.get("user_message") is None


# =============================================================================
# New customer flow (with pending_whatsapp_name)
# =============================================================================


class TestGreetingModeNewCustomer:
    """Tests for new customer flow: silent creation with sender_name."""

    @pytest.mark.asyncio
    async def test_new_customer_creates_customer_with_sender_name(self):
        """New customer with pending_whatsapp_name → create customer silently."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "María García"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-001", "first_name": "María García", "phone": "+34612345678"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        # Customer should be created
        mock_mc.ainvoke.assert_called_once()
        call_args = mock_mc.ainvoke.call_args[0][0]
        assert call_args["action"] == "create"
        assert call_args["data"]["first_name"] == "María García"

        # customer_name should be set in state
        assert result.get("customer_name") == "María García"
        assert result.get("customer_id") == "cust-uuid-001"

    @pytest.mark.asyncio
    async def test_new_customer_transitions_to_general(self):
        """New customer flow must transition to GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Pedro"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-002", "first_name": "Pedro"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_new_customer_response_does_not_contain_name(self):
        """New customer greeting must NOT contain the sender's name."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-002", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "María"
        state["messages"] = [
            {"role": "user", "content": "buenas tardes", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-003", "first_name": "María"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "María" not in combined_content


# =============================================================================
# New customer without sender_name
# =============================================================================


class TestGreetingModeNewCustomerNoName:
    """Tests for new customer without sender_name (pending_whatsapp_name is None)."""

    @pytest.mark.asyncio
    async def test_new_customer_without_name_creates_customer(self):
        """Customer created with first_name=None when sender_name is None."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-004"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        # Should still create customer (without name)
        mock_mc.ainvoke.assert_called_once()
        call_args = mock_mc.ainvoke.call_args[0][0]
        assert call_args["action"] == "create"
        # data dict should NOT have first_name key when name is None
        assert "first_name" not in call_args.get("data", {})

    @pytest.mark.asyncio
    async def test_new_customer_without_name_transitions_to_general(self):
        """New customer without name must still transition to GENERAL."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-005"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        assert result["current_mode"] == "GENERAL"

    @pytest.mark.asyncio
    async def test_new_customer_without_name_does_not_ask_for_name(self):
        """Must NOT ask for the customer's name."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-003", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = None
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-006"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        assert "nombre" not in combined_content.lower()
        assert "llamas" not in combined_content.lower()
        assert "¿Con quién" not in combined_content


# =============================================================================
# Name extraction removed
# =============================================================================


class TestGreetingModeNoNameExtraction:
    """Verify that all name extraction methods have been removed."""

    def test_no_heuristic_extract_method(self):
        """_heuristic_extract method must not exist."""
        mode = make_greeting_mode()
        assert not hasattr(mode, "_heuristic_extract")

    def test_no_extract_name_method(self):
        """_extract_name method must not exist."""
        mode = make_greeting_mode()
        assert not hasattr(mode, "_extract_name")

    def test_no_is_valid_name_function(self):
        """_is_valid_name function must not exist in module."""
        import agent.modes.greeting_mode as gm
        assert not hasattr(gm, "_is_valid_name")

    def test_no_non_name_words_constant(self):
        """_NON_NAME_WORDS constant must not exist in module."""
        import agent.modes.greeting_mode as gm
        assert not hasattr(gm, "_NON_NAME_WORDS")

    def test_no_filler_words_constant(self):
        """_FILLER_WORDS constant must not exist in module."""
        import agent.modes.greeting_mode as gm
        assert not hasattr(gm, "_FILLER_WORDS")


# =============================================================================
# Customer creation failure handling
# =============================================================================


class TestGreetingModeCustomerCreationFailure:
    """Tests for when customer creation fails."""

    @pytest.mark.asyncio
    async def test_customer_creation_failure_still_sends_greeting(self):
        """Even if customer creation fails, greeting response should be sent."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-004", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Ana"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(side_effect=Exception("DB connection error"))
            result = await mode.handle(state, make_intent())

        # Should still transition to GENERAL with a greeting
        assert result["current_mode"] == "GENERAL"
        messages = result.get("messages", [])
        assert len(messages) >= 1

    @pytest.mark.asyncio
    async def test_no_phone_skips_customer_creation(self):
        """When customer_phone is empty, skip DB creation."""
        mode = make_greeting_mode()
        state = create_initial_state("conv-005", "")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Pedro"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock()
            result = await mode.handle(state, make_intent())

        # manage_customer should NOT be called when phone is empty
        mock_mc.ainvoke.assert_not_called()
        # Should still transition to GENERAL
        assert result["current_mode"] == "GENERAL"


# =============================================================================
# LLM response validation (name leak prevention)
# =============================================================================


class TestGreetingModeLLMNameLeakPrevention:
    """Tests that LLM responses containing customer names are rejected."""

    @pytest.mark.asyncio
    async def test_llm_response_with_name_falls_back_to_template(self):
        """If LLM leaks customer name in response, fall back to safe template."""
        # LLM returns a response that contains the customer name
        mode = make_greeting_mode(llm_response="¡Hola de nuevo, María! ¿En qué puedo ayudarte?")
        state = create_initial_state("conv-006", "+34612345678")
        state["customer_name"] = "María"

        result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        # Name must NOT appear even if LLM tried to use it
        assert "María" not in combined_content

    @pytest.mark.asyncio
    async def test_llm_response_asking_for_name_falls_back_to_template(self):
        """If LLM asks for name in response, fall back to safe template."""
        mode = make_greeting_mode(llm_response="¡Hola! ¿Cómo te llamas?")
        state = create_initial_state("conv-007", "+34612345678")
        state["customer_name"] = None
        state["pending_whatsapp_name"] = "Pedro"
        state["messages"] = [
            {"role": "user", "content": "hola", "timestamp": "2026-03-18T10:00:00+01:00"}
        ]

        mock_result = {"id": "cust-uuid-007"}
        with patch("agent.modes.greeting_mode.manage_customer") as mock_mc:
            mock_mc.ainvoke = AsyncMock(return_value=mock_result)
            result = await mode.handle(state, make_intent())

        messages = result.get("messages", [])
        combined_content = " ".join(m.get("content", "") for m in messages)
        # Must NOT ask for name
        assert "llamas" not in combined_content.lower()
