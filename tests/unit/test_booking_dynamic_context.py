"""
Test suite for booking_mode.py dynamic context XML tags.

Verifies:
- <available_stylists> tag present in dynamic context output
- <offered_slots> tag present in dynamic context output
- _build_messages() delegates to build_layered_messages (mock-based)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from langchain_core.messages import SystemMessage

from agent.modes.booking_mode import BookingMode
from agent.modes.booking_context import BookingContext
from agent.state.schemas import ConversationState


class TestBookingDynamicContextXMLTags:
    """Verify XML tag presence in booking dynamic context."""

    def test_available_stylists_tag_in_dynamic_context(self):
        """<available_stylists> tag present when stylists are available."""
        ctx = BookingContext()
        ctx.prefetched_stylists = [
            {"name": "María", "next_slot_summary": "Mañana 10:00"},
            {"name": "Laura", "next_slot_summary": "Hoy 16:00"},
        ]

        state: ConversationState = {
            "customer_phone": "1234567890",
            "mode_context": {},
            "messages": [],
            "conversation_summary": None,
        }

        dynamic_context = BookingMode._build_dynamic_context(state, ctx)

        assert "<available_stylists>" in dynamic_context, "Missing <available_stylists> opening tag"
        assert "</available_stylists>" in dynamic_context, "Missing <available_stylists> closing tag"

    def test_offered_slots_tag_in_dynamic_context(self):
        """<offered_slots> tag present when slots are offered."""
        ctx = BookingContext()
        ctx.offered_slots = [
            {
                "slot_index": 0,
                "datetime_str": "2026-03-27 10:00",
                "slot_summary": "Mañana 10:00",
            },
            {
                "slot_index": 1,
                "datetime_str": "2026-03-27 11:00",
                "slot_summary": "Mañana 11:00",
            },
        ]

        state: ConversationState = {
            "customer_phone": "1234567890",
            "mode_context": {},
            "messages": [],
            "conversation_summary": None,
        }

        dynamic_context = BookingMode._build_dynamic_context(state, ctx)

        assert "<offered_slots>" in dynamic_context, "Missing <offered_slots> opening tag"
        assert "</offered_slots>" in dynamic_context, "Missing <offered_slots> closing tag"

    def test_collected_data_tag_in_dynamic_context(self):
        """<collected_data> tag present with data structure."""
        ctx = BookingContext()
        ctx.service_name = "Corte"
        ctx.stylist_name = "María"

        state: ConversationState = {
            "customer_phone": "1234567890",
            "mode_context": {},
            "messages": [],
            "conversation_summary": None,
        }

        dynamic_context = BookingMode._build_dynamic_context(state, ctx)

        assert "<collected_data>" in dynamic_context, "Missing <collected_data> tag"
        assert "</collected_data>" in dynamic_context, "Missing </collected_data> tag"

    def test_missing_data_tag_in_dynamic_context(self):
        """<missing_data> tag present with data structure."""
        ctx = BookingContext()
        # Missing service, stylist, name, etc.

        state: ConversationState = {
            "customer_phone": "1234567890",
            "mode_context": {},
            "messages": [],
            "conversation_summary": None,
        }

        dynamic_context = BookingMode._build_dynamic_context(state, ctx)

        assert "<missing_data>" in dynamic_context, "Missing <missing_data> tag"
        assert "</missing_data>" in dynamic_context, "Missing </missing_data> tag"


class TestBookingBuildMessagesDelegation:
    """Verify _build_messages() delegates to build_layered_messages()."""

    @pytest.mark.asyncio
    async def test_build_messages_calls_build_layered_messages(self):
        """_build_messages() should delegate to build_layered_messages()."""
        mode = BookingMode()
        ctx = BookingContext()

        state: ConversationState = {
            "customer_phone": "1234567890",
            "mode_context": {},
            "messages": [],
            "conversation_summary": None,
        }

        with patch("agent.modes.booking_mode.build_layered_messages", new_callable=AsyncMock) as mock_build:
            # Mock return: (messages, index)
            mock_messages = [
                SystemMessage(content="System"),
                SystemMessage(content="Mode"),
                SystemMessage(content="Dynamic"),
            ]
            mock_build.return_value = (mock_messages, 2)

            result = await mode._build_messages(state, ctx)

            # Verify delegation
            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]

            assert "state" in call_kwargs
            assert "mode_context" in call_kwargs
            assert "mode_name" in call_kwargs
            assert call_kwargs["mode_name"] == "BOOKING"
            assert "dynamic_context_override" in call_kwargs
            assert "include_history" in call_kwargs
            assert "history_limit" in call_kwargs

            # Verify result
            assert result == mock_messages
