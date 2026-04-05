"""
Test suite for loader.py assembly order and dynamic context handling.

Verifies:
- build_layered_messages returns tuple[list, int]
- Dynamic context is the last SystemMessage
- dynamic_context_override parameter replaces default _build_simple_dynamic_context
- build_step_context and _STEP_VISIBLE_FIELDS are gone (simplified architecture)
- catalog_builder is importable (catalog now in prompt, not per-tool)
"""

import inspect

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent.prompts.loader import build_layered_messages
from agent.state.schemas import ConversationState


@pytest.mark.asyncio
async def test_build_layered_messages_returns_tuple_with_index():
    """build_layered_messages returns (messages, dynamic_context_index)."""
    state: ConversationState = {
        "customer_phone": "1234567890",
        "mode_context": {},
        "messages": [],
        "conversation_summary": None,
    }
    mode_context = {}

    with patch("agent.prompts.loader.get_system_prompt", new_callable=AsyncMock) as mock_system:
        mock_system.return_value = "System prompt"

        messages, index = await build_layered_messages(
            state=state,
            mode_context=mode_context,
            mode_name="BOOKING",
            include_history=False,
        )

        # Verify return type
        assert isinstance(messages, list), "Messages should be a list"
        assert isinstance(index, int), "Index should be an integer"

        # Index should point to the last SystemMessage
        assert index < len(messages), f"Index {index} out of range"
        assert isinstance(messages[index], SystemMessage), f"Message at index {index} should be SystemMessage"


@pytest.mark.asyncio
async def test_dynamic_context_is_last_system_message():
    """Dynamic context (after history) is the last SystemMessage."""
    state: ConversationState = {
        "customer_phone": "1234567890",
        "mode_context": {},
        "messages": [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¿En qué puedo ayudarte?"},
        ],
        "conversation_summary": None,
    }
    mode_context = {}

    with patch("agent.prompts.loader.get_system_prompt", new_callable=AsyncMock) as mock_system:
        mock_system.return_value = "System prompt"

        messages, index = await build_layered_messages(
            state=state,
            mode_context=mode_context,
            mode_name="BOOKING",
            include_history=True,
        )

        # Message at index should be a SystemMessage
        assert isinstance(messages[index], SystemMessage)

        # All messages after index should NOT be SystemMessage (should be history)
        for i in range(index + 1, len(messages)):
            msg = messages[i]
            assert isinstance(msg, (HumanMessage, AIMessage)), (
                f"Message at index {i} should be HumanMessage or AIMessage, not {type(msg)}"
            )


@pytest.mark.asyncio
async def test_dynamic_context_override_replaces_build_step_context():
    """dynamic_context_override parameter replaces default build_step_context()."""
    state: ConversationState = {
        "customer_phone": "1234567890",
        "mode_context": {"service_name": "Corte"},
        "messages": [],
        "conversation_summary": None,
    }
    mode_context = {"service_name": "Corte"}

    custom_override = "<custom>Override content here</custom>"

    with patch("agent.prompts.loader.get_system_prompt", new_callable=AsyncMock) as mock_system:
        mock_system.return_value = "System prompt"

        messages, index = await build_layered_messages(
            state=state,
            mode_context=mode_context,
            mode_name="BOOKING",
            dynamic_context_override=custom_override,
            include_history=False,
        )

        # The dynamic context message (at index) should contain the override
        dynamic_context_msg = messages[index]
        assert isinstance(dynamic_context_msg, SystemMessage)
        assert custom_override in dynamic_context_msg.content, (
            f"Override not found in dynamic context. Got: {dynamic_context_msg.content[:100]}"
        )


@pytest.mark.asyncio
async def test_message_order_shared_mode_dynamic_history():
    """Messages follow order: shared system, mode overlay, dynamic context, history."""
    state: ConversationState = {
        "customer_phone": "1234567890",
        "mode_context": {},
        "messages": [
            {"role": "user", "content": "User msg"},
        ],
        "conversation_summary": None,
    }
    mode_context = {}

    with patch("agent.prompts.loader.get_system_prompt", new_callable=AsyncMock) as mock_system:
        mock_system.return_value = "SHARED_SYSTEM"
        with patch("agent.prompts.loader.load_mode_overlay") as mock_overlay:
            mock_overlay.return_value = "MODE_OVERLAY"

            messages, index = await build_layered_messages(
                state=state,
                mode_context=mode_context,
                mode_name="BOOKING",
                include_history=True,
            )

            # Verify order: shared (0), mode (1), history (2), dynamic context LAST (per recency spec)
            assert "SHARED_SYSTEM" in messages[0].content
            assert "MODE_OVERLAY" in messages[1].content
            # Dynamic context is LAST for maximum recency per lost-in-the-middle research
            assert index == len(messages) - 1  # Dynamic IS the last message
            assert isinstance(messages[index], SystemMessage)  # Last message is dynamic context


# ============================================================================
# T-37: Architecture validation tests — simplified loader
# ============================================================================


def test_no_build_step_context():
    """build_step_context is gone — replaced by _build_simple_dynamic_context."""
    import agent.prompts.loader as loader_module

    assert not hasattr(loader_module, "build_step_context"), (
        "build_step_context should be removed — use _build_simple_dynamic_context instead"
    )
    source = inspect.getsource(loader_module)
    assert "build_step_context" not in source, (
        "build_step_context string should not appear in loader.py source"
    )


def test_no_step_visible_fields():
    """_STEP_VISIBLE_FIELDS is gone — step-driven context was removed."""
    import agent.prompts.loader as loader_module

    assert not hasattr(loader_module, "_STEP_VISIBLE_FIELDS"), (
        "_STEP_VISIBLE_FIELDS should be removed — step visibility is no longer tracked"
    )
    source = inspect.getsource(loader_module)
    assert "_STEP_VISIBLE_FIELDS" not in source, (
        "_STEP_VISIBLE_FIELDS string should not appear in loader.py source"
    )


def test_catalog_builder_importable():
    """build_catalog_markdown is importable — catalog is now injected into prompt."""
    from agent.prompts.catalog_builder import build_catalog_markdown

    assert callable(build_catalog_markdown), (
        "build_catalog_markdown must be a callable — it builds the service catalog for the prompt"
    )
