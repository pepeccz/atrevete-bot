"""
Unit + integration tests for the ROBUST pre-loop negation_resolver precondition
in BookingModeNode (Opción B).

Bug (conv_id=5, 2026-04-18): LLM incorrectly set no_preference_stylist in an
earlier turn, which silenced the resolver for the user's negation "Nada mas" —
bot looped on "¿algo más?" question.

Fix: replace brittle state guards (last_stylist / no_preference_stylist) with
a CONTEXTUAL check — the resolver fires only when the LAST AIMessage in the
transcript contains an "algo más" style question.

TDD: these tests FAIL on master (guards still present) and PASS after the fix.

Covers:
- _last_ai_message_has_add_more_question pure helper (dict + LangChain shape).
- Resolver integration via booking_mode.handle() with the new precondition.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.modes.booking_mode import (
    BookingModeNode,
    _last_ai_message_has_add_more_question,
)
from agent.state.schemas import create_initial_state


# ============================================================================
# Part 1 — Pure helper: _last_ai_message_has_add_more_question
# ============================================================================


class TestLastAIMessageHelper:
    """The helper scans messages from the end and returns True iff the most
    recent AIMessage contains an 'algo más'-style substring (case insensitive).
    """

    # --- Positive matches (dict shape) -----------------------------------

    @pytest.mark.parametrize(
        "bot_text",
        [
            "Vale, ¿quieres añadir algo más a la cita?",
            "Perfecto, ¿quieres añadir algo más a la cita?",
            "¿Deseas agregar algo más?",
            "¿Vas a querer añadir algo?",
            "¿Sumamos algo más?",
            "¿Quieres sumar algo al pedido?",
            "¿Algún otro servicio te interesa?",
            "¿Algun otro servicio?",
            "Perfecto. ¿Algo más?",  # minimal trigger
        ],
    )
    def test_dict_shape_positive_matches(self, bot_text: str) -> None:
        messages = [
            {"role": "user", "content": "Hola, quiero cortarme el pelo"},
            {"role": "assistant", "content": "¿Corte Señora o Caballero?"},
            {"role": "user", "content": "señora!"},
            {"role": "assistant", "content": bot_text},
            {"role": "user", "content": "Nada mas"},
        ]
        assert _last_ai_message_has_add_more_question(messages) is True

    # --- Negative matches (dict shape) -----------------------------------

    @pytest.mark.parametrize(
        "bot_text",
        [
            "Hola, ¿qué día quieres?",
            "¿A qué hora te viene bien?",
            "¿Prefieres la mañana o la tarde?",
            "Perfecto, te confirmo la cita.",
            "¿Con qué estilista quieres reservar?",
        ],
    )
    def test_dict_shape_negative_no_match(self, bot_text: str) -> None:
        messages = [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": bot_text},
            {"role": "user", "content": "nada"},
        ]
        assert _last_ai_message_has_add_more_question(messages) is False

    # --- LangChain AIMessage shape ---------------------------------------

    def test_langchain_aimessage_positive(self) -> None:
        messages = [
            HumanMessage(content="Hola"),
            AIMessage(content="¿Quieres añadir algo más a la cita?"),
            HumanMessage(content="Nada más"),
        ]
        assert _last_ai_message_has_add_more_question(messages) is True

    def test_langchain_aimessage_negative(self) -> None:
        messages = [
            HumanMessage(content="Hola"),
            AIMessage(content="¿Qué día prefieres?"),
            HumanMessage(content="no sé"),
        ]
        assert _last_ai_message_has_add_more_question(messages) is False

    # --- Mixed shapes (realistic state) ----------------------------------

    def test_mixed_shapes_last_ai_dict_positive(self) -> None:
        messages = [
            HumanMessage(content="Hola"),
            AIMessage(content="¿Cuándo?"),
            {"role": "user", "content": "mañana"},
            {"role": "assistant", "content": "¿Quieres sumar algo más?"},
            {"role": "user", "content": "nada"},
        ]
        assert _last_ai_message_has_add_more_question(messages) is True

    def test_mixed_shapes_last_ai_langchain_negative(self) -> None:
        messages = [
            {"role": "assistant", "content": "¿Algo más?"},  # older AI
            {"role": "user", "content": "sí, un oleo"},
            AIMessage(content="Perfecto. ¿Con qué estilista?"),  # latest AI
            HumanMessage(content="me da igual"),
        ]
        # Helper must pick the MOST RECENT AIMessage (the LangChain one),
        # whose content is NOT an "algo más" question.
        assert _last_ai_message_has_add_more_question(messages) is False

    # --- Edge cases -------------------------------------------------------

    def test_empty_messages(self) -> None:
        assert _last_ai_message_has_add_more_question([]) is False

    def test_no_ai_messages(self) -> None:
        messages = [
            {"role": "user", "content": "Hola"},
            {"role": "user", "content": "¿Estás ahí?"},
        ]
        assert _last_ai_message_has_add_more_question(messages) is False

    def test_case_insensitive(self) -> None:
        messages = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¿DESEAS AGREGAR ALGO MÁS?"},
        ]
        assert _last_ai_message_has_add_more_question(messages) is True

    def test_no_accent_match(self) -> None:
        """Substring match must cover 'algo mas' (no accent) as well."""
        messages = [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¿Quieres algo mas?"},
        ]
        assert _last_ai_message_has_add_more_question(messages) is True


# ============================================================================
# Part 2 — Integration tests via BookingModeNode.handle
# ============================================================================


def _make_scripted_agent(reply: str = "Perfecto. ¿Con qué estilista?") -> MagicMock:
    async def _ainvoke(input_: dict, *args, **kwargs) -> dict:
        messages = list(input_.get("messages", []))
        messages.append(AIMessage(content=reply))
        return {"messages": messages}

    agent_mock = MagicMock()
    agent_mock.ainvoke = _ainvoke
    return agent_mock


def _make_node() -> BookingModeNode:
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


def _make_state(
    user_message: str,
    booking_context: dict[str, Any] | None = None,
    prior_messages: list | None = None,
) -> dict:
    """Build a ConversationState with optional prior messages (history)."""
    state = create_initial_state("negation-robust-test", "+34600000003")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Cliente Test"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = booking_context or {}
    state["mode_context"] = {}
    msgs: list = list(prior_messages or [])
    msgs.append({"role": "user", "content": user_message})
    state["messages"] = msgs
    return state


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


class TestResolverNewPrecondition:
    """The resolver must fire based on the LAST AIMessage content, not on
    stale state guards like last_stylist / no_preference_stylist.
    """

    async def test_real_bug_no_preference_stylist_does_not_block_resolver(
        self, _common_patches
    ) -> None:
        """R1 (new): with no_preference_stylist=True (wrongly set by LLM in a
        prior turn) AND the previous bot turn asking '¿algo más?', the resolver
        MUST still fire for 'Nada mas'.

        This reproduces conv_id=5 (2026-04-18). FAILS on master because the old
        guards abort the resolver.
        """
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte Señora"],
            "add_more_asked": False,
            "no_preference_stylist": True,  # erroneous flag set earlier
        }
        prior = [
            {"role": "user", "content": "Hola, quiero cortarme el pelo"},
            {"role": "assistant", "content": "¿Corte Señora, Caballero, Niño o Niña?"},
            {"role": "user", "content": "señora!"},
            {
                "role": "assistant",
                "content": "Vale, ¿quieres añadir algo más a la cita?",
            },
        ]
        state = _make_state("Nada mas", booking_context=booking_ctx, prior_messages=prior)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert result.get("booking_context", {}).get("add_more_asked") is True, (
            "Resolver must fire on 'Nada mas' when last bot msg was '¿algo más?', "
            "regardless of no_preference_stylist being set."
        )

    async def test_last_stylist_set_does_not_block_resolver(
        self, _common_patches
    ) -> None:
        """Same bug pattern, but with last_stylist set instead. The LLM could have
        wrongly set a stylist earlier; the resolver must still honour the last
        '¿algo más?' question in the transcript.
        """
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte Señora"],
            "add_more_asked": False,
            "last_stylist": "Maria",  # set in a prior turn (possibly incorrectly)
        }
        prior = [
            {"role": "assistant", "content": "¿Quieres añadir algo más a la cita?"},
        ]
        state = _make_state("nada mas", booking_context=booking_ctx, prior_messages=prior)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert result.get("booking_context", {}).get("add_more_asked") is True

    async def test_resolver_does_not_fire_when_last_bot_msg_not_add_more(
        self, _common_patches
    ) -> None:
        """Precondition: if last bot message is NOT an 'algo más' question,
        the resolver MUST NOT fire (avoids false positives).
        """
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte"],
            "add_more_asked": False,
        }
        prior = [
            {"role": "assistant", "content": "Hola, ¿qué día quieres?"},
        ]
        state = _make_state("nada", booking_context=booking_ctx, prior_messages=prior)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert not result.get("booking_context", {}).get("add_more_asked"), (
            "Resolver must NOT fire when last bot message is not an 'algo más' question."
        )

    async def test_resolver_preserves_current_behavior(self, _common_patches) -> None:
        """Regression guard: the classic scenario (no stylist flags, bot asked
        '¿algo más?', user says 'no') must still work.
        """
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte"],
            "add_more_asked": False,
        }
        prior = [
            {"role": "assistant", "content": "¿Quieres añadir algo más?"},
        ]
        state = _make_state(
            "nada mas", booking_context=booking_ctx, prior_messages=prior
        )

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert result.get("booking_context", {}).get("add_more_asked") is True

    async def test_fuzzy_typo_with_last_bot_question(self, _common_patches) -> None:
        """Fuzzy match: user typo 'nda mas' must still match after the fix."""
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte Señora"],
            "add_more_asked": False,
        }
        prior = [
            {"role": "assistant", "content": "¿Deseas agregar algo más?"},
        ]
        state = _make_state("nda mas", booking_context=booking_ctx, prior_messages=prior)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert result.get("booking_context", {}).get("add_more_asked") is True

    @pytest.mark.parametrize(
        "bot_text",
        [
            "¿deseas añadir algo más?",
            "¿vas a querer agregar algo?",
            "¿sumamos algo más?",
            "¿algún otro servicio?",
        ],
    )
    async def test_variant_bot_messages_trigger_resolver(
        self, _common_patches, bot_text: str
    ) -> None:
        """All accepted bot-question phrasings must enable the resolver."""
        node = _make_node()

        booking_ctx = {
            "last_services": ["Corte"],
            "add_more_asked": False,
        }
        prior = [{"role": "assistant", "content": bot_text}]
        state = _make_state("nada", booking_context=booking_ctx, prior_messages=prior)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert result.get("booking_context", {}).get("add_more_asked") is True, (
            f"Resolver should fire when last bot msg is: {bot_text!r}"
        )

    async def test_hook_does_not_fire_without_last_services(
        self, _common_patches
    ) -> None:
        """Precondition: last_services must be set."""
        node = _make_node()

        booking_ctx = {"last_services": [], "add_more_asked": False}
        prior = [{"role": "assistant", "content": "¿Quieres añadir algo más?"}]
        state = _make_state("nada", booking_context=booking_ctx, prior_messages=prior)

        agent_mock = _make_scripted_agent()

        with patch("langchain.agents.create_agent", return_value=agent_mock):
            result = await node.handle(state, intent=None)

        assert not result.get("booking_context", {}).get("add_more_asked")
