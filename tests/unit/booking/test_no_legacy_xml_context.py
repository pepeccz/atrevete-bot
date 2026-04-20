"""
B.1.1 [RED] — Verify that no legacy XML tags are injected into LLM messages.

After Phase B.1, _build_dynamic_context() must be removed and the LLM must receive
ZERO <booking_context>, <flow_hint>, <audience_ambiguity> etc. XML blocks.

Expected failure on master: AssertionError — legacy XML tag <booking_context> found
in SystemMessage content produced by _build_dynamic_context().
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(booking_context: dict | None = None) -> dict:
    """Build a minimal ConversationState dict for testing."""
    return {
        "conversation_id": "test-conv-1",
        "messages": [{"role": "user", "content": "quiero cortarme el pelo", "timestamp": ""}],
        "current_mode": "BOOKING",
        "booking_context": booking_context or {"last_services": ["Corte largo"]},
        "mode_context": {},
        "customer_phone": "+34600000001",
        "conversation_summary": "",
        "customer_memories": None,
        "total_message_count": 1,
        "customer_name": None,
    }


# ---------------------------------------------------------------------------
# B.1.1 test
# ---------------------------------------------------------------------------


class TestNoLegacyXmlInLLMMessages:
    """Assert that _build_dynamic_context() XML is NOT present in messages sent to the LLM."""

    def test_system_messages_contain_no_xml(self):
        """Drive a booking turn and assert no legacy XML tags appear in messages.

        RED on master: _build_dynamic_context() produces <booking_context>...</booking_context>
        which gets injected as a SystemMessage. assert_no_legacy_xml_tags must catch this.

        GREEN after B.1.6: _build_dynamic_context() is removed; only [grounding]
        HumanMessage from BookingGroundingMiddleware carries context.
        """
        from tests.conftest import assert_no_legacy_xml_tags

        # Import BookingModeNode — must succeed on master too
        from agent.modes.booking_mode import BookingModeNode

        node = BookingModeNode.__new__(BookingModeNode)

        state = _make_state()
        mode_context = dict(state.get("booking_context") or {})

        # Patch build_layered_messages to capture the messages it would build
        # AND check the dynamic_context_override argument that booking_mode passes.
        captured_override: list[str | None] = []

        async def _mock_build_layered(state, mode_context, mode_name=None,
                                      dynamic_context_override=None, **kwargs):
            captured_override.append(dynamic_context_override)
            # Return two dummy messages with the override as a SystemMessage
            from langchain_core.messages import SystemMessage
            msgs = [SystemMessage(content="base system prompt")]
            if dynamic_context_override:
                msgs.append(SystemMessage(content=dynamic_context_override))
            return msgs, len(msgs) - 1

        with patch("agent.modes.booking_mode.build_layered_messages", side_effect=_mock_build_layered):
            import asyncio

            async def _run():
                return await node._build_messages(state, mode_context)

            messages = asyncio.get_event_loop().run_until_complete(_run())

        # The captured_override MUST be empty (None) after B.1.6 is applied.
        # On master, it contains the full _build_dynamic_context output with XML tags.
        # If dynamic_context_override was non-None and contains XML → the assertion below fails RED.
        from langchain_core.messages import BaseMessage

        all_messages_content: list = []
        for msg in messages:
            if hasattr(msg, "content") and isinstance(msg.content, str):
                all_messages_content.append(msg)

        # This assertion fails RED on master because _build_dynamic_context injects XML
        assert_no_legacy_xml_tags(all_messages_content)

    def test_build_dynamic_context_does_not_exist(self):
        """Assert that BookingModeNode no longer has a _build_dynamic_context method.

        RED on master (method exists), GREEN after B.1.6 (method deleted).
        """
        from agent.modes.booking_mode import BookingModeNode

        assert not hasattr(BookingModeNode, "_build_dynamic_context"), (
            "BookingModeNode still has _build_dynamic_context — "
            "this method must be removed in Phase B.1"
        )
