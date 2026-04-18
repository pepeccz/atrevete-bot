"""Unit tests for ``StatusLineMiddleware`` — TDD RED→GREEN cycle.

Tests (8):
    T1.1  test_inject_when_flag_enabled          — HumanMessage con prefix "[estado] " inyectado
    T1.3a test_no_dedup_first_call               — primer call sin [estado] previo → append
    T1.3b test_dedup_multi_step                  — segundo call con [estado] previo → replace, no acumula
    T1.3c test_dedup_exact_one_estado_after_loop — 3 model calls → exactamente 1 [estado] al final
    REQ-STATUS-LINE-4  test_cap_600_chars        — content ≤ 600 chars (invariante)
    REQ-STATUS-LINE-5  test_mode_guard           — mode distinto → request sin modificar
    REQ-STATUS-LINE-6  test_observability_logs   — log DEBUG con campos requeridos
    Scenario-7  test_empty_booking_context_no_exception — state vacío no lanza

STRICT TDD: estos tests deben FALLAR (ImportError / AttributeError) antes de que exista
agent/middleware/status_line.py.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from langchain.agents.middleware.types import ModelRequest

# -- Subject Under Test (falla hasta que exista el archivo) ------------------
from agent.middleware.status_line import StatusLineMiddleware  # RED trigger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PREFIX = "[estado] "


def _make_state(
    mode: str = "BOOKING",
    services: list | None = None,
    stylist: str | None = None,
    add_more_asked: bool = False,
) -> dict:
    """Build a minimal ConversationState-like dict for tests."""
    bc: dict = {}
    if services is not None:
        bc["last_services"] = services
    if stylist:
        bc["last_stylist"] = stylist
    if add_more_asked:
        bc["add_more_asked"] = True
    return {
        "current_mode": mode,
        "booking_context": bc,
        "customer_first_name": "Ana",
    }


def _make_request(messages: list | None = None) -> ModelRequest:
    """Build a minimal ModelRequest."""
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=model)
    return ModelRequest(
        model=model,
        messages=messages or [],
        tools=[],
        state={"messages": []},
    )


def _sync_passthrough(request: ModelRequest) -> ModelRequest:
    """Sync handler that returns the (possibly mutated) request."""
    return request


async def _async_passthrough(request: ModelRequest) -> ModelRequest:
    """Async handler that returns the request unchanged."""
    return request


# ---------------------------------------------------------------------------
# T1.1 — RED trigger (classe no existe todavía)
# ---------------------------------------------------------------------------


class TestT11InjectWhenFlagEnabled:
    """T1.1 — inject_when_flag_enabled: debe inyectar HumanMessage con prefix '[estado] '."""

    def test_inject_returns_human_message_with_prefix(self, monkeypatch):
        """awrap_model_call inyecta HumanMessage cuyo content empieza con '[estado] '."""
        state = _make_state(mode="BOOKING", services=["Cortar"])
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        request = _make_request(messages=[HumanMessage(content="Hola")])
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )

        # Hay al menos un mensaje con el prefix
        estado_msgs = [
            m
            for m in result.messages
            if isinstance(m, HumanMessage)
            and isinstance(m.content, str)
            and m.content.startswith(_PREFIX)
        ]
        assert len(estado_msgs) >= 1, (
            f"Expected at least 1 HumanMessage with prefix '{_PREFIX}', "
            f"got messages: {[type(m).__name__ + ':' + str(m.content)[:60] for m in result.messages]}"
        )

    def test_inject_sync_parity(self, monkeypatch):
        """wrap_model_call (sync) inyecta de igual manera que awrap_model_call."""
        state = _make_state(mode="BOOKING", services=["Cortar"])
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        request = _make_request(messages=[HumanMessage(content="Hola")])
        result = mw.wrap_model_call(request, _sync_passthrough)

        estado_msgs = [
            m
            for m in result.messages
            if isinstance(m, HumanMessage)
            and isinstance(m.content, str)
            and m.content.startswith(_PREFIX)
        ]
        assert len(estado_msgs) >= 1, "sync wrap_model_call debe inyectar igual que async"


# ---------------------------------------------------------------------------
# T1.3 — Dedup multi-step
# ---------------------------------------------------------------------------


class TestT13DedupMultiStep:
    """T1.3 — dedup: replace, no acumulación."""

    def test_no_dedup_first_call(self):
        """Sin [estado] previo → se hace append (no replace, no dedup)."""
        state = _make_state(mode="BOOKING", services=["Cortar"])
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        original_msgs = [HumanMessage(content="quiero cortarme el pelo")]
        request = _make_request(messages=original_msgs)
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )

        # El mensaje original debe seguir presente
        non_estado = [
            m
            for m in result.messages
            if isinstance(m, HumanMessage) and not m.content.startswith(_PREFIX)
        ]
        assert len(non_estado) == 1, "El HumanMessage original debe conservarse"

        estado_msgs = [
            m
            for m in result.messages
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX)
        ]
        assert len(estado_msgs) == 1, "Debe haber exactamente 1 [estado] tras primer call"

    def test_dedup_multi_step_replaces_old_estado(self):
        """Dos awrap_model_call sucesivos con state diferente → exactamente 1 [estado] al final.

        Scenario 2 del spec: dedup=True en el segundo call.
        """
        # State en el primer call: sin estilista
        state_step1 = _make_state(mode="BOOKING", services=["Cortar"], stylist=None)
        mw1 = StatusLineMiddleware(get_state_fn=lambda: state_step1, mode_name="BOOKING")

        request_step1 = _make_request(messages=[HumanMessage(content="quiero cortarme")])
        result_step1 = asyncio.get_event_loop().run_until_complete(
            mw1.awrap_model_call(request_step1, _async_passthrough)
        )

        # Verificar que el step1 produjo exactamente 1 [estado]
        estados_step1 = [
            m
            for m in result_step1.messages
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX)
        ]
        assert len(estados_step1) == 1

        # State en el segundo call: con estilista ya asignada (simulando update_booking mid-loop)
        state_step2 = _make_state(mode="BOOKING", services=["Cortar"], stylist="Marta")
        mw2 = StatusLineMiddleware(get_state_fn=lambda: state_step2, mode_name="BOOKING")

        # El transcript ya contiene el [estado] del step1
        request_step2 = _make_request(messages=result_step1.messages)
        result_step2 = asyncio.get_event_loop().run_until_complete(
            mw2.awrap_model_call(request_step2, _async_passthrough)
        )

        # Debe haber exactamente 1 [estado] (el viejo fue reemplazado)
        estados_final = [
            m
            for m in result_step2.messages
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX)
        ]
        assert len(estados_final) == 1, (
            f"Expected exactly 1 [estado] after dedup, got {len(estados_final)}: "
            f"{[m.content[:80] for m in estados_final]}"
        )

        # El nuevo [estado] debe reflejar el state actualizado (Marta)
        assert "Marta" in estados_final[0].content, (
            f"El [estado] debe reflejar la estilista actualizada (Marta), "
            f"got: {estados_final[0].content}"
        )

    def test_dedup_exact_one_estado_after_3_model_calls(self):
        """3 model calls sucesivos → exactamente 1 [estado] al final del transcript."""
        msgs = [HumanMessage(content="quiero cortarme el pelo")]

        for i in range(3):
            state = _make_state(mode="BOOKING", services=[f"Cortar_v{i}"])
            mw = StatusLineMiddleware(get_state_fn=lambda s=state: s, mode_name="BOOKING")
            request = _make_request(messages=msgs)
            result = asyncio.get_event_loop().run_until_complete(
                mw.awrap_model_call(request, _async_passthrough)
            )
            msgs = result.messages  # pasar el transcript al siguiente step

        # Exactamente 1 [estado]
        estados = [
            m
            for m in msgs
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX)
        ]
        assert len(estados) == 1, (
            f"After 3 calls, expected exactly 1 [estado], got {len(estados)}: "
            f"{[m.content[:80] for m in estados]}"
        )


# ---------------------------------------------------------------------------
# REQ-STATUS-LINE-4 — Cap de 600 caracteres
# ---------------------------------------------------------------------------


class TestCapChars:
    def test_status_line_content_le_600_chars(self):
        """Content del HumanMessage [estado] no supera los 600 chars (invariante MAX_CONTENT_CHARS)."""
        # State "gordo" con listas largas
        state = _make_state(
            mode="BOOKING",
            services=[f"Servicio_{i}" for i in range(30)],
            stylist="Estilista con un nombre muy largo que podría exceder el budget",
        )
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")
        request = _make_request(messages=[HumanMessage(content="hola")])
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )

        for m in result.messages:
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX):
                assert len(m.content) <= 600, (
                    f"Content exceeds 600 chars: {len(m.content)}"
                )


# ---------------------------------------------------------------------------
# REQ-STATUS-LINE-5 — Mode guard
# ---------------------------------------------------------------------------


class TestModeGuard:
    def test_other_mode_request_unchanged(self):
        """Si state.current_mode != mode_name, el request pasa sin modificar."""
        # Mode GENERAL pero middleware instanciado con "BOOKING"
        state = _make_state(mode="GENERAL", services=["Cortar"])
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        original_msgs = [HumanMessage(content="¿cuánto cuesta?")]
        request = _make_request(messages=original_msgs)
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )

        # No debe haber ningún [estado]
        estado_msgs = [
            m
            for m in result.messages
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX)
        ]
        assert len(estado_msgs) == 0, (
            "Mode guard debe impedir inyección cuando current_mode != mode_name"
        )

    def test_booking_mode_activates_injection(self):
        """Mode BOOKING sí inyecta."""
        state = _make_state(mode="BOOKING")
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        request = _make_request(messages=[HumanMessage(content="hola")])
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )

        estado_msgs = [
            m
            for m in result.messages
            if isinstance(m, HumanMessage) and m.content.startswith(_PREFIX)
        ]
        assert len(estado_msgs) == 1


# ---------------------------------------------------------------------------
# REQ-STATUS-LINE-6 — Observabilidad (logs)
# ---------------------------------------------------------------------------


class TestObservabilityLogs:
    def test_debug_log_emitted_on_inject(self, caplog):
        """Debe emitirse un log DEBUG con campos status_line.* al inyectar."""
        state = _make_state(mode="BOOKING", services=["Cortar"])
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        request = _make_request(messages=[HumanMessage(content="hola")])

        with caplog.at_level(logging.DEBUG, logger="agent.middleware.status_line"):
            asyncio.get_event_loop().run_until_complete(
                mw.awrap_model_call(request, _async_passthrough)
            )

        # Debe haber al menos 1 registro de log en el nivel DEBUG del módulo correcto
        debug_records = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "status_line" in r.getMessage().lower()
        ]
        assert len(debug_records) >= 1, (
            f"Expected at least 1 DEBUG log with 'status_line', "
            f"got records: {[r.getMessage() for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# Scenario 7 — State vacío no lanza excepción
# ---------------------------------------------------------------------------


class TestEmptyStateNoException:
    def test_empty_booking_context_no_exception(self):
        """State con booking_context vacío no lanza ninguna excepción."""
        state: dict = {"current_mode": "BOOKING", "booking_context": {}}
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        request = _make_request(messages=[HumanMessage(content="hola")])
        # No debe lanzar
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )
        assert result is not None

    def test_none_booking_context_no_exception(self):
        """State con booking_context=None no lanza excepción."""
        state: dict = {"current_mode": "BOOKING", "booking_context": None}
        mw = StatusLineMiddleware(get_state_fn=lambda: state, mode_name="BOOKING")

        request = _make_request(messages=[HumanMessage(content="hola")])
        result = asyncio.get_event_loop().run_until_complete(
            mw.awrap_model_call(request, _async_passthrough)
        )
        assert result is not None
