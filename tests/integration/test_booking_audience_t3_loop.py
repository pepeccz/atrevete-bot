"""
Integration test for T3 audience resolution wiring in BookingModeNode.handle().

C6.4 — T3 wiring: synthetic state delivery after audience hint extracted.

TDD cycle: this test MUST FAIL before C6.4.2 implementation.
Covers R3, S1.

Scenario:
- Turn 1: user said "quiero un corte" → booking_context has _audience_ambiguity set
           with variants=["Corte Señora","Corte Caballero"], last_services=["Corte"]
- Turn 2: user sends "Señora!" → BookingModeNode.handle() extracts hint "adult_female",
           pops _audience_ambiguity, then:
           a) resolves "Corte Señora" via _pick_variant_by_hint
           b) updates last_services to ["Corte Señora"]
           c) calls deliver_state_update → [AIMessage, ToolMessage] synthetic pair
           d) injects synthetic pair into create_agent transcript
           e) assert no _audience_ambiguity in result booking_context
           f) assert last_services == ["Corte Señora"] in result booking_context
           g) assert telemetry log with delivered=True, context_label="audience-t3"
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent.modes.booking_mode import BookingModeNode
from agent.state.schemas import create_initial_state


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_scripted_agent(reply: str = "Perfecto, un corte para señora. ¿Qué estilista prefieres?") -> MagicMock:
    """Create a scripted agent that records the transcript it received."""
    captured_transcript: list = []

    async def _ainvoke(input_: dict, *args, **kwargs) -> dict:
        messages = list(input_.get("messages", []))
        captured_transcript.extend(messages)
        messages.append(AIMessage(content=reply))
        return {"messages": messages}

    agent_mock = MagicMock()
    agent_mock.ainvoke = _ainvoke
    agent_mock._captured_transcript = captured_transcript
    return agent_mock


def _make_node() -> BookingModeNode:
    """Create a BookingModeNode with mocked dependencies."""
    with patch("agent.modes.booking_mode.BaseModeNode.__init__", return_value=None):
        node = BookingModeNode.__new__(BookingModeNode)

    node.llm = MagicMock()
    node.llm.bind_tools = MagicMock(return_value=node.llm)
    node._cached_stylists_by_category = {}
    node._cached_service_names = {}
    node._booking_context = {}
    node._mode_context = {}
    node._current_state = {}
    return node


def _make_turn2_state(
    user_message: str = "Señora!",
    booking_context: dict[str, Any] | None = None,
) -> dict:
    """Build the Turn-2 state that arrives to handle()."""
    state = create_initial_state("t3-test-001", "+34600000001")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Test Cliente"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = booking_context or {}
    state["mode_context"] = {}
    # Messages include prior Turn-1 exchange + Turn-2 user message
    state["messages"] = [
        {"role": "user", "content": "quiero un corte"},
        {
            "role": "assistant",
            "content": "¿El corte es para señora o caballero?",
        },
        {"role": "user", "content": user_message},
    ]
    return state


# Post-Turn-1 booking_context — _audience_ambiguity is set, no hint yet
_TURN1_BOOKING_CONTEXT: dict[str, Any] = {
    "last_services": ["Corte"],
    "_audience_ambiguity": {
        "family": "Corte",
        "variants": ["Corte Señora", "Corte Caballero"],
    },
    # service_audience_hint absent → triggers extraction on Turn 2
}


# ---------------------------------------------------------------------------
# C6.4 — T3 tests
# ---------------------------------------------------------------------------


@pytest.fixture
def _common_patches():
    with (
        patch(
            "agent.modes.booking_mode.BookingModeNode._load_stylists_by_category",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._load_service_names",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agent.modes.booking_mode.build_layered_messages",
            new_callable=AsyncMock,
            return_value=([HumanMessage(content="system stub")], 0),
        ),
        patch(
            "agent.modes.booking_mode.get_booking_config",
            new_callable=AsyncMock,
            return_value=MagicMock(tool_choice_policy=MagicMock(value="never_force")),
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._maybe_prepend_intro",
            side_effect=lambda text, state: (text, False),
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._sanitize_response",
            side_effect=lambda text: text,
        ),
        patch(
            "agent.modes.booking_mode.BookingModeNode._resolve_service_category",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "agent.modes.booking_mode.write_customer_memories",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        yield


class TestT3AudienceResolutionWiring:
    """C6.4: T3 wiring — synthetic delivery after audience hint extracted on Turn 2."""

    async def test_last_services_updated_to_resolved_variant(self, _common_patches) -> None:
        """R3, S1: last_services must be updated to the resolved full variant name."""
        node = _make_node()
        state = _make_turn2_state(booking_context=dict(_TURN1_BOOKING_CONTEXT))
        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        ctx = result.get("booking_context", {})
        assert ctx.get("last_services") == ["Corte Señora"], (
            f"Expected last_services=['Corte Señora'] after T3 resolution, "
            f"got {ctx.get('last_services')!r}. "
            "FAILS before C6.4.2 implementation."
        )

    async def test_audience_ambiguity_cleared(self, _common_patches) -> None:
        """R3, S1: _audience_ambiguity must be absent after T3 resolution."""
        node = _make_node()
        state = _make_turn2_state(booking_context=dict(_TURN1_BOOKING_CONTEXT))
        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        ctx = result.get("booking_context", {})
        assert "_audience_ambiguity" not in ctx, (
            f"_audience_ambiguity must be cleared after T3 resolution, "
            f"but it's still present: {ctx.get('_audience_ambiguity')!r}"
        )

    async def test_synthetic_messages_injected_in_transcript(self, _common_patches, caplog) -> None:
        """R3, S1: Transcript passed to create_agent must contain synthetic AIMessage + ToolMessage."""
        node = _make_node()
        state = _make_turn2_state(booking_context=dict(_TURN1_BOOKING_CONTEXT))

        captured_transcripts: list = []

        async def _capture_ainvoke(input_: dict, *args, **kwargs) -> dict:
            captured_transcripts.extend(input_.get("messages", []))
            msgs = list(input_.get("messages", []))
            msgs.append(AIMessage(content="Perfecto, un corte para señora."))
            return {"messages": msgs}

        agent_mock = MagicMock()
        agent_mock.ainvoke = _capture_ainvoke

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
                result = await node.handle(state, intent=None)

        # Find synthetic AIMessage in transcript
        synthetic_ai_msgs = [
            m for m in captured_transcripts
            if isinstance(m, AIMessage)
            and m.content == ""
            and m.tool_calls
            and m.tool_calls[0].get("name") == "update_booking"
            and m.tool_calls[0].get("id", "").startswith("synth-")
        ]
        assert synthetic_ai_msgs, (
            f"Expected synthetic AIMessage (content='', tool_calls=[update_booking(...)]) "
            f"in transcript. Captured {len(captured_transcripts)} messages: "
            f"{[type(m).__name__ for m in captured_transcripts]}. "
            "FAILS before C6.4.2 implementation."
        )

        # Find corresponding ToolMessage
        synth_id = synthetic_ai_msgs[0].tool_calls[0]["id"]
        synthetic_tool_msgs = [
            m for m in captured_transcripts
            if isinstance(m, ToolMessage) and m.tool_call_id == synth_id
        ]
        assert synthetic_tool_msgs, (
            f"Expected synthetic ToolMessage with tool_call_id={synth_id!r} in transcript"
        )

    async def test_synthetic_toolmessage_reflects_resolved_state(self, _common_patches) -> None:
        """S1: ToolMessage content reflects resolved booking state (services: ['Corte Señora'])."""
        node = _make_node()
        state = _make_turn2_state(booking_context=dict(_TURN1_BOOKING_CONTEXT))

        captured: list = []

        async def _capture_ainvoke(input_: dict, *args, **kwargs) -> dict:
            captured.extend(input_.get("messages", []))
            msgs = list(input_.get("messages", []))
            msgs.append(AIMessage(content="Perfecto."))
            return {"messages": msgs}

        agent_mock = MagicMock()
        agent_mock.ainvoke = _capture_ainvoke

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            await node.handle(state, intent=None)

        # Find synthetic ToolMessage
        synth_tool = next(
            (m for m in captured if isinstance(m, ToolMessage) and m.tool_call_id.startswith("synth-")),
            None,
        )
        assert synth_tool is not None, "Synthetic ToolMessage not found in transcript"

        content = json.loads(synth_tool.content)
        # The content must show "Corte Señora" as collected service
        collected_str = " ".join(content.get("collected", []))
        assert "Corte Señora" in collected_str, (
            f"Expected 'Corte Señora' in ToolMessage collected. Got: {content!r}"
        )
        # next_step must NOT say "Audiencia ambigua" (that was the T3 bug)
        next_step = content.get("next_step", "")
        assert "Audiencia ambigua" not in next_step, (
            f"next_step must not say 'Audiencia ambigua' after resolution. Got: {next_step!r}"
        )

    async def test_telemetry_emitted_with_delivered_true(self, _common_patches, caplog) -> None:
        """R5: booking.synthetic_state_delivery telemetry emitted with delivered=True."""
        node = _make_node()
        state = _make_turn2_state(booking_context=dict(_TURN1_BOOKING_CONTEXT))
        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
                await node.handle(state, intent=None)

        telemetry = [r for r in caplog.records if "synthetic_state_delivery" in r.message]
        assert telemetry, (
            f"Expected 'booking.synthetic_state_delivery' log. "
            f"Records: {[r.message for r in caplog.records]}"
        )
        record = telemetry[0]
        assert getattr(record, "delivered", None) is True
        assert getattr(record, "context_label", None) == "audience-t3"

    async def test_no_synthetic_delivery_when_no_ambiguity(self, _common_patches, caplog) -> None:
        """R3: When no _audience_ambiguity, no synthetic messages delivered."""
        node = _make_node()
        # Context without ambiguity
        clean_ctx = {
            "last_services": ["Corte Señora"],
            "service_audience_hint": "adult_female",
        }
        state = _make_turn2_state(user_message="Para las once", booking_context=clean_ctx)

        captured: list = []

        async def _capture_ainvoke(input_: dict, *args, **kwargs) -> dict:
            captured.extend(input_.get("messages", []))
            msgs = list(input_.get("messages", []))
            msgs.append(AIMessage(content="Perfecto."))
            return {"messages": msgs}

        agent_mock = MagicMock()
        agent_mock.ainvoke = _capture_ainvoke

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            with caplog.at_level(logging.INFO, logger="agent.core.state_delivery"):
                await node.handle(state, intent=None)

        # No synthetic messages should appear
        synth_msgs = [
            m for m in captured
            if isinstance(m, AIMessage) and m.content == "" and m.tool_calls
            and m.tool_calls[0].get("id", "").startswith("synth-")
        ]
        assert not synth_msgs, (
            f"Expected no synthetic messages when no _audience_ambiguity, got {synth_msgs!r}"
        )
