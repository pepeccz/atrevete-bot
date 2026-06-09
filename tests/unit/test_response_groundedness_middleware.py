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
