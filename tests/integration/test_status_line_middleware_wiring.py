"""Integration tests for StatusLineMiddleware wiring in BookingModeNode (T1.5).

Two subtests:
  (a) flag=False → behavior actual intacto (regression guard).
      StatusLineMiddleware NO aparece en el stack de create_agent.
  (b) flag=True  → StatusLineMiddleware en el stack, en posición 1 (post-DynamicTools).
      _inject produce HumanMessage [estado] con 'add_more_asked' cuando el flag está seteado.

Nota: el bug del loop add_more_asked solo se manifiesta con LLM live (OpenRouter
prefix cache). En este test usamos un agente stubbed — asertamos sobre el estructural:
  - que StatusLineMiddleware EXISTE en el stack cuando flag=True.
  - que NO EXISTE cuando flag=False.
  - que _inject produce el content correcto (add_more_asked en flags).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.modes.booking_mode import BookingModeNode
from agent.state.schemas import create_initial_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    user_message: str,
    booking_context: dict[str, Any] | None = None,
) -> dict:
    state = create_initial_state("status-line-wiring-test", "+34600000099")
    state["user_message"] = user_message
    state["current_mode"] = "BOOKING"
    state["customer_name"] = "Cliente Test"
    state["is_first_interaction"] = False
    state["error_count"] = 0
    state["escalation_triggered"] = False
    state["ai_disclosure_sent"] = True
    state["booking_context"] = booking_context or {}
    state["mode_context"] = {}
    state["messages"] = [{"role": "user", "content": user_message}]
    return state


_PREFIX = "[estado] "


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


# ---------------------------------------------------------------------------
# Middleware capture factory — inspects the middleware list passed to create_agent
# ---------------------------------------------------------------------------


class _MiddlewareCapture:
    """Captura el middleware list pasado a create_agent."""

    def __init__(self, reply: str = "Perfecto.") -> None:
        self.captured_middleware: list | None = None
        self._reply = reply

    def make_agent_factory(self):
        """Retorna un callable que reemplaza create_agent y captura el middleware."""
        capture = self

        def _create_agent(model, tools, system_prompt="", middleware=None, **kwargs):
            capture.captured_middleware = list(middleware or [])

            async def _ainvoke(input_: dict, *args, **kw) -> dict:
                msgs = list(input_.get("messages", []))
                msgs.append(AIMessage(content=capture._reply))
                return {"messages": msgs}

            agent_mock = MagicMock()
            agent_mock.ainvoke = _ainvoke
            return agent_mock

        return _create_agent


# ---------------------------------------------------------------------------
# Common patches fixture
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
            return_value=MagicMock(
                tool_choice_policy=MagicMock(value="never_force")
            ),
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


# ---------------------------------------------------------------------------
# T1.5a — Regression guard (flag=False)
# ---------------------------------------------------------------------------


class TestStatusLineWiringFlagOff:
    """flag=False → StatusLineMiddleware NO en el stack (behavior actual intacto)."""

    async def test_not_in_stack_when_flag_off(self, _common_patches) -> None:
        """ENABLE_STATUS_LINE_MIDDLEWARE=False → StatusLineMiddleware NO en el stack."""
        node = _make_node()
        mc = _MiddlewareCapture()

        state = _make_state(
            "nada más",
            booking_context={"last_services": ["Corte Señora"], "add_more_asked": True},
        )

        with (
            patch("langchain.agents.create_agent", side_effect=mc.make_agent_factory()),
            patch(
                "shared.config.get_settings",
                return_value=MagicMock(ENABLE_STATUS_LINE_MIDDLEWARE=False),
            ),
        ):
            await node.handle(state, intent=None)

        assert mc.captured_middleware is not None, "create_agent no fue llamado"
        mw_types = [type(m).__name__ for m in mc.captured_middleware]
        assert "StatusLineMiddleware" not in mw_types, (
            f"flag=False: StatusLineMiddleware NO debe estar en el stack. "
            f"Stack actual: {mw_types}"
        )


# ---------------------------------------------------------------------------
# T1.5b — Structural guard (flag=True)
# ---------------------------------------------------------------------------


class TestStatusLineWiringFlagOn:
    """flag=True → StatusLineMiddleware en el stack en posición 1."""

    async def test_status_line_middleware_in_stack_when_flag_on(
        self, _common_patches
    ) -> None:
        """ENABLE_STATUS_LINE_MIDDLEWARE=True → StatusLineMiddleware en el stack posición 1."""
        from agent.middleware.status_line import StatusLineMiddleware

        node = _make_node()
        mc = _MiddlewareCapture()

        booking_ctx = {"last_services": ["Corte Señora"], "add_more_asked": True}
        state = _make_state("nada más", booking_context=booking_ctx)
        node._current_state = state

        with (
            patch("langchain.agents.create_agent", side_effect=mc.make_agent_factory()),
            patch(
                "shared.config.get_settings",
                return_value=MagicMock(ENABLE_STATUS_LINE_MIDDLEWARE=True),
            ),
        ):
            await node.handle(state, intent=None)

        assert mc.captured_middleware is not None, "create_agent no fue llamado"

        mw_types = [type(m).__name__ for m in mc.captured_middleware]
        assert "StatusLineMiddleware" in mw_types, (
            f"StatusLineMiddleware debe estar en el stack cuando flag=True. "
            f"Stack actual: {mw_types}"
        )

        # Posición: después de DynamicTools (index 0), en index 1
        sl_idx = mw_types.index("StatusLineMiddleware")
        assert sl_idx == 1, (
            f"StatusLineMiddleware debe estar en posición 1 (después de DynamicTools). "
            f"Stack: {mw_types}"
        )

    async def test_inject_produces_add_more_asked_in_flags(
        self, _common_patches
    ) -> None:
        """flag=True + add_more_asked=True → _inject produce [estado] con 'add_more_asked'.

        Verifica directamente que el middleware instanciado produce el HumanMessage correcto,
        sin depender del comportamiento interno de create_agent.
        Este es el assert estructural principal que verifica que el bug no se reproduce:
        el LLM recibirá 'flags=add_more_asked' → no debería re-preguntar "¿algo más?".
        """
        from agent.middleware.status_line import StatusLineMiddleware
        from langchain.agents.middleware.types import ModelRequest

        booking_ctx = {"last_services": ["Corte Señora"], "add_more_asked": True}
        state = _make_state("nada más", booking_context=booking_ctx)
        state["current_mode"] = "BOOKING"

        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        model_mock = MagicMock()
        model_mock.bind_tools = MagicMock(return_value=model_mock)
        request = ModelRequest(
            model=model_mock,
            messages=[HumanMessage(content="nada más")],
            tools=[],
            state={"messages": []},
        )
        injected = mw._inject(request)

        estado_msgs = [
            m
            for m in injected.messages
            if isinstance(m, HumanMessage)
            and isinstance(m.content, str)
            and m.content.startswith(_PREFIX)
        ]
        assert len(estado_msgs) == 1, (
            f"_inject debe producir exactamente 1 HumanMessage [estado]. "
            f"Got: {[m.content[:80] for m in estado_msgs]}"
        )
        assert "add_more_asked" in estado_msgs[0].content, (
            f"El [estado] debe contener 'add_more_asked' cuando booking_context tiene ese flag. "
            f"Content: {estado_msgs[0].content!r}"
        )
