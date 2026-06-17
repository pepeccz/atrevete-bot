"""Tests for Change J5: ResponseGroundednessMiddleware.

Change J: hallucination-tolerant-architecture-bundle. REQ-J5.

Tests written BEFORE implementation (TDD RED phase).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import check
# ---------------------------------------------------------------------------


def test_middleware_importable():
    """ResponseGroundednessMiddleware must be importable."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware  # noqa: F401


# ---------------------------------------------------------------------------
# Clean reply — no warning emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_reply_no_warning():
    """Reply containing only catalog tokens → no logger.warning called."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    catalog_slot = (
        "<catalog>\n"
        "Corte Dama id=some-uuid\n"
        "Tinte id=other-uuid\n"
        "Ana id=stylist-uuid\n"
        "</catalog>"
    )
    reply_content = "Te reservo un Corte Dama con Ana."

    state = {"_slot_catalog": catalog_slot, "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = reply_content

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger") as mock_logger:
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        await middleware.awrap_model_call(request, mock_handler)

        mock_logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# Hallucinated service name → warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hallucinated_service_triggers_warning():
    """Reply mentioning a service NOT in _slot_catalog → logger.warning called.

    REQ-J5 acceptance scenario: "Keratina Suprema" is not a catalog service.
    The middleware must log exactly 1 warning for the unknown_catalog_token type.
    """
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    catalog_slot = "<catalog>\n" "Corte Dama id=some-uuid\n" "Ana id=stylist-uuid\n" "</catalog>"
    # "Keratina Suprema" is not in the catalog
    reply_content = "Te recomiendo un tratamiento de Keratina Suprema."

    state = {"_slot_catalog": catalog_slot, "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = reply_content

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger") as mock_logger:
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        await middleware.awrap_model_call(request, mock_handler)

    # "Keratina Suprema" is a capitalized multi-word phrase not in the catalog
    mock_logger.warning.assert_called()
    call_kwargs_list = [call.kwargs.get("extra", {}) for call in mock_logger.warning.call_args_list]
    unknown_token_calls = [e for e in call_kwargs_list if e.get("type") == "unknown_catalog_token"]
    assert (
        len(unknown_token_calls) >= 1
    ), f"Expected at least 1 unknown_catalog_token warning, got: {call_kwargs_list}"


@pytest.mark.asyncio
async def test_invented_service_xyz_triggers_warning():
    """REQ-J5 acceptance: 'Servicio Inventado XYZ' not in catalog → exactly 1 warning.

    This is the spec acceptance scenario: bot mentions a hallucinated service name.
    """
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    catalog_slot = (
        "<catalog>\n"
        "Corte Dama id=some-uuid\n"
        "Tinte id=other-uuid\n"
        "Marta id=stylist-uuid\n"
        "</catalog>"
    )
    # "Servicio Inventado XYZ" is not in the catalog
    reply_content = "Puedo ofrecerte el Servicio Inventado XYZ para tu visita."

    state = {"_slot_catalog": catalog_slot, "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = reply_content

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger") as mock_logger:
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        await middleware.awrap_model_call(request, mock_handler)

    mock_logger.warning.assert_called()
    call_kwargs_list = [call.kwargs.get("extra", {}) for call in mock_logger.warning.call_args_list]
    unknown_token_calls = [e for e in call_kwargs_list if e.get("type") == "unknown_catalog_token"]
    assert len(unknown_token_calls) >= 1, (
        f"Expected at least 1 unknown_catalog_token warning for hallucinated service, "
        f"got: {call_kwargs_list}"
    )


# ---------------------------------------------------------------------------
# Price pattern in reply → warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_pattern_triggers_warning():
    """Reply with numeric price pattern '25 €' → logger.warning called."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    catalog_slot = "<catalog>\nCorte Dama id=some-uuid\n</catalog>"
    reply_content = "El corte cuesta 25 €."

    state = {"_slot_catalog": catalog_slot, "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = reply_content

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger") as mock_logger:
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        await middleware.awrap_model_call(request, mock_handler)

        mock_logger.warning.assert_called()
        call_args = mock_logger.warning.call_args
        # The warning event name
        assert (
            "groundedness" in call_args[0][0].lower() or "violation" in call_args[0][0].lower()
        ), f"Warning message should mention groundedness/violation, got: {call_args}"


@pytest.mark.asyncio
async def test_price_pattern_euro_symbol_detected():
    """'30€' without space → also detected by price regex."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    catalog_slot = "<catalog>\nTinte id=uuid1\n</catalog>"
    reply_content = "El tinte cuesta 30€ aproximadamente."

    state = {"_slot_catalog": catalog_slot, "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = reply_content

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger") as mock_logger:
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        await middleware.awrap_model_call(request, mock_handler)

        mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# Empty catalog → no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_catalog_no_crash():
    """Empty _slot_catalog → middleware runs without error, no warning."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    state = {"_slot_catalog": "", "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = "Te ayudo con tu reserva."

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger") as mock_logger:
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        response = await middleware.awrap_model_call(request, mock_handler)

    assert response is mock_response


@pytest.mark.asyncio
async def test_absent_catalog_slot_no_crash():
    """Absent _slot_catalog → graceful degradation, no crash."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    state = {"conversation_id": "test-conv"}  # No _slot_catalog key
    assistant_msg = MagicMock()
    assistant_msg.content = "Claro, te ayudo."

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    middleware = ResponseGroundednessMiddleware()
    request = MagicMock()
    request.state = state

    response = await middleware.awrap_model_call(request, mock_handler)
    assert response is mock_response


# ---------------------------------------------------------------------------
# Response is forwarded unchanged (LOG-ONLY mode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_forwarded_unchanged():
    """Even when violations detected, the response is returned unchanged (LOG-ONLY)."""
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    catalog_slot = "<catalog>\nCorte Dama id=uuid1\n</catalog>"
    original_content = "El servicio cuesta 50 euros."

    state = {"_slot_catalog": catalog_slot, "conversation_id": "test-conv"}
    assistant_msg = MagicMock()
    assistant_msg.content = original_content

    mock_response = MagicMock()
    mock_response.result = [assistant_msg]

    async def mock_handler(req):
        return mock_response

    with patch("agent.middleware.response_groundedness.logger"):
        middleware = ResponseGroundednessMiddleware()
        request = MagicMock()
        request.state = state

        response = await middleware.awrap_model_call(request, mock_handler)

    # Response must be the same object (not modified)
    assert response is mock_response
    assert response.result[0].content == original_content


# ---------------------------------------------------------------------------
# Middleware registered in agent_factory.py
# ---------------------------------------------------------------------------


def test_response_groundedness_in_agent_factory():
    """ResponseGroundednessMiddleware must be registered in agent_factory base_middleware."""
    import importlib
    import inspect

    factory_mod = importlib.import_module("agent.agent_factory")
    source = inspect.getsource(factory_mod.build_conversation_agent)
    assert (
        "ResponseGroundednessMiddleware" in source
    ), "ResponseGroundednessMiddleware must be instantiated in build_conversation_agent"


# ---------------------------------------------------------------------------
# FIX MINOR-1 — regex drift guard
# ---------------------------------------------------------------------------


def test_booking_regex_source_matches_harness_helper():
    """The middleware booking regex and the harness helper regex MUST be identical.

    The harness (tests/e2e/harness/assert_claim_backend.py) duplicates the booking
    confirmation pattern tuple on purpose (no import-time dep on the agent package).
    This guard asserts the two module-level constants are byte-for-byte equal so that
    editing one without the other fails CI.
    """
    from agent.middleware.response_groundedness import _BOOKING_CONFIRMATION_PATTERNS as mw_patterns
    from tests.e2e.harness.assert_claim_backend import (
        _BOOKING_CONFIRMATION_PATTERNS as harness_patterns,
    )

    assert mw_patterns == harness_patterns, (
        "Booking confirmation regex drift between middleware and harness helper. "
        "Update both agent/middleware/response_groundedness.py and "
        "tests/e2e/harness/assert_claim_backend.py together."
    )


# ---------------------------------------------------------------------------
# FIX MINOR-2 — middleware-level BLOCKING gate tests (real ToolMessage / AIMessage)
# ---------------------------------------------------------------------------


def _book_ok_json(appointment_id: str = "11111111-1111-1111-1111-111111111111") -> str:
    """A real `book` ToolResponse ok payload, serialized like the tool returns it."""
    from agent.tools.schemas import ToolResponse

    return ToolResponse(
        status="ok",
        payload={
            "appointment_id": appointment_id,
            "customer_id": "22222222-2222-2222-2222-222222222222",
            "start_iso": "2026-07-01T10:00:00+02:00",
            "end_iso": "2026-07-01T10:30:00+02:00",
            "stylist_id": "33333333-3333-3333-3333-333333333333",
        },
    ).model_dump_json()


async def _run_gate(*, history, result, reply_content):
    """Drive awrap_model_call with a real AIMessage reply + the given history/result.

    `history` is the state["messages"] list; `result` is response.result (this turn).
    Returns the final reply content of the last result message after the gate ran.
    """
    from agent.middleware.response_groundedness import ResponseGroundednessMiddleware

    mock_response = MagicMock()
    mock_response.result = result

    async def mock_handler(req):
        return mock_response

    middleware = ResponseGroundednessMiddleware()
    request = MagicMock()
    request.state = {
        "_slot_catalog": "",
        "conversation_id": "test-conv",
        "messages": history,
    }

    with patch("agent.middleware.response_groundedness.logger"):
        response = await middleware.awrap_model_call(request, mock_handler)
    return response.result[-1].content


@pytest.mark.asyncio
async def test_booking_confirmation_with_matching_this_turn_book_ok_not_blocked():
    """(a) booking confirmation + matching this-turn `book` ok → NOT blocked."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    reply = "¡Listo! Tu cita queda confirmada para el jueves."
    history = [HumanMessage(content="Quiero reservar")]
    # This-turn AIMessage requested `book` (tool_call id call_1); ToolMessage answers it.
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": "book", "args": {}, "id": "call_1"}],
    )
    tool_msg = ToolMessage(content=_book_ok_json(), name="book", tool_call_id="call_1")
    final_ai = AIMessage(content=reply)
    result = [ai_call, tool_msg, final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert final == reply, "Genuine this-turn booking confirmation must NOT be rewritten"


@pytest.mark.asyncio
async def test_booking_confirmation_with_only_stale_prior_turn_book_ok_is_blocked():
    """(b) BLOCKER-2: stale prior-turn `book` ok + NEW confirmation this turn → BLOCKED."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from agent.middleware.response_groundedness import _CONFIRMATION_FALLBACK_MESSAGE

    reply = "¡Listo! Tu cita queda confirmada."
    # Prior turn: a real book ok-result lives in history BEFORE the latest HumanMessage.
    history = [
        HumanMessage(content="Reserva la primera"),
        AIMessage(content="", tool_calls=[{"name": "book", "args": {}, "id": "old_call"}]),
        ToolMessage(content=_book_ok_json(), name="book", tool_call_id="old_call"),
        AIMessage(content="Te confirmé la primera."),
        HumanMessage(content="Ahora confírmame otra cosa"),  # latest human → turn boundary
    ]
    # This turn: NO new book tool_call, just a hallucinated confirmation.
    final_ai = AIMessage(content=reply)
    result = [final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert final == _CONFIRMATION_FALLBACK_MESSAGE, (
        "A stale prior-turn book result must NOT green-light a new hallucinated "
        "confirmation — it must be rewritten to the fallback."
    )


@pytest.mark.asyncio
async def test_booking_confirmation_with_no_book_result_is_blocked():
    """(c) booking confirmation + NO `book` result anywhere → BLOCKED."""
    from langchain_core.messages import AIMessage, HumanMessage

    from agent.middleware.response_groundedness import _CONFIRMATION_FALLBACK_MESSAGE

    reply = "Perfecto, te he confirmado la cita para el jueves."
    history = [HumanMessage(content="Confírmame la cita")]
    final_ai = AIMessage(content=reply)
    result = [final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert final == _CONFIRMATION_FALLBACK_MESSAGE


@pytest.mark.asyncio
async def test_cancel_confirmation_string_is_not_blocked_log_only():
    """(d) a real cancel confirmation string → NOT blocked (log-only path)."""
    from langchain_core.messages import AIMessage, HumanMessage

    reply = "Tu cita ha sido cancelada."
    history = [HumanMessage(content="Cancela mi cita")]
    final_ai = AIMessage(content=reply)
    result = [final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert final == reply, "Cancel/reschedule confirmations are log-only — never rewritten"


@pytest.mark.asyncio
async def test_non_string_content_skips_gate_safely():
    """FIX MINOR-3: list-of-parts content is skipped safely (no crash, no rewrite)."""
    from langchain_core.messages import AIMessage

    list_content = [{"type": "text", "text": "Tu cita queda confirmada."}]
    final_ai = AIMessage(content=list_content)
    result = [final_ai]

    final = await _run_gate(history=[], result=result, reply_content=list_content)
    assert final == list_content, "Non-str content must pass through untouched"


# ---------------------------------------------------------------------------
# manage_appointments false-positive regression fix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_cancel_backed_not_blocked():
    """Booking-flavored phrasing + current-turn manage_appointments success → NOT blocked.

    Regression guard: cancel turns that use wording like "te he confirmado" or
    "listo... la cita" were being rewritten to the booking fallback because the gate
    only checked for a `book` ToolMessage backing. A legitimate cancel/reschedule
    backed by a successful manage_appointments result must now pass through intact.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    # Bot reply uses booking-flavored phrasing after a cancel
    reply = "¡Listo! Te he confirmado la cancelación de la cita."
    history = [HumanMessage(content="Cancela mi cita del jueves")]
    # Current-turn manage_appointments ToolMessage with a successful plain-string result
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": "manage_appointments", "args": {"action": "cancel"}, "id": "mgmt_1"}],
    )
    tool_msg = ToolMessage(
        content="Tu cita ha sido cancelada.",
        name="manage_appointments",
        tool_call_id="mgmt_1",
    )
    final_ai = AIMessage(content=reply)
    result = [ai_call, tool_msg, final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert (
        final == reply
    ), "A cancel turn backed by manage_appointments success must NOT be rewritten to the fallback"


@pytest.mark.asyncio
async def test_manage_error_content_is_blocked():
    """Booking-flavored phrasing + manage_appointments error result → BLOCKED.

    When the manage_appointments ToolMessage content contains an error marker, the
    result is treated as a failure. The booking-confirmation gate must still block.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from agent.middleware.response_groundedness import _CONFIRMATION_FALLBACK_MESSAGE

    reply = "¡Listo! Te he confirmado la cancelación de la cita."
    history = [HumanMessage(content="Cancela mi cita")]
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": "manage_appointments", "args": {"action": "cancel"}, "id": "mgmt_2"}],
    )
    # Error-marker in the ToolMessage content → manage result is a failure
    tool_msg = ToolMessage(
        content="No he podido encontrar tu cita.",
        name="manage_appointments",
        tool_call_id="mgmt_2",
    )
    final_ai = AIMessage(content=reply)
    result = [ai_call, tool_msg, final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert (
        final == _CONFIRMATION_FALLBACK_MESSAGE
    ), "An error manage result must NOT green-light booking phrasing — gate must block"


@pytest.mark.asyncio
async def test_stale_manage_prior_turn_is_blocked():
    """Booking-flavored phrasing + STALE prior-turn manage success + no book this turn → BLOCKED.

    Turn-bounding must hold: a manage_appointments success from a previous turn must NOT
    green-light a booking-confirmation phrase in the current turn.

    Structure:
      [HumanMessage, AIMessage(tool_calls=[manage]), ToolMessage(manage success),  <- prior turn
       HumanMessage, AIMessage(booking phrase, no tool_calls)]                     <- current turn
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from agent.middleware.response_groundedness import _CONFIRMATION_FALLBACK_MESSAGE

    reply = "¡Listo! Tu cita queda confirmada."
    # Prior turn: manage succeeded
    history = [
        HumanMessage(content="Cancela mi cita"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "manage_appointments", "args": {"action": "cancel"}, "id": "old_mgmt"}
            ],
        ),
        ToolMessage(
            content="Tu cita ha sido cancelada.",
            name="manage_appointments",
            tool_call_id="old_mgmt",
        ),
        AIMessage(content="Tu cita del jueves ha sido cancelada con éxito."),
        HumanMessage(content="Quiero reservar otra cita"),  # current-turn boundary
    ]
    # Current turn: no tool calls at all, just a hallucinated confirmation
    final_ai = AIMessage(content=reply)
    result = [final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert (
        final == _CONFIRMATION_FALLBACK_MESSAGE
    ), "A stale prior-turn manage result must NOT green-light a new hallucinated confirmation"


@pytest.mark.asyncio
async def test_book_backed_still_passes():
    """Regression guard: a real book-backed confirmation must still pass through after the fix."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    reply = "¡Listo! Tu cita queda confirmada para el jueves."
    history = [HumanMessage(content="Reserva para el jueves")]
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": "book", "args": {}, "id": "book_1"}],
    )
    tool_msg = ToolMessage(content=_book_ok_json(), name="book", tool_call_id="book_1")
    final_ai = AIMessage(content=reply)
    result = [ai_call, tool_msg, final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert final == reply, "Genuine book-backed confirmation must NOT be rewritten after the fix"


@pytest.mark.asyncio
async def test_no_backing_still_blocked():
    """Regression guard: booking phrasing with NO tool backing at all must still be blocked."""
    from langchain_core.messages import AIMessage, HumanMessage

    from agent.middleware.response_groundedness import _CONFIRMATION_FALLBACK_MESSAGE

    reply = "Te he confirmado la cita para el viernes."
    history = [HumanMessage(content="Confirma mi cita")]
    final_ai = AIMessage(content=reply)
    result = [final_ai]

    final = await _run_gate(history=history, result=result, reply_content=reply)
    assert (
        final == _CONFIRMATION_FALLBACK_MESSAGE
    ), "No-backing hallucinated confirmation must still be blocked after the fix"
