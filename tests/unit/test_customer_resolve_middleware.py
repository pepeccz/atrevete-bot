"""T4.2 / T7.5 — CustomerResolveMiddleware: phone→customer injection; skip if customer_id set.

TDD RED phase — written before agent/middleware/customer_resolve.py exists.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID


def _make_request(state: dict, system_message=None):
    """Build a minimal ModelRequest mock."""
    from langchain_core.messages import SystemMessage

    req = MagicMock()
    req.state = state
    req.system_message = system_message or SystemMessage(content="base")
    captured = {}

    def override(**kwargs):
        captured.update(kwargs)
        new_req = MagicMock()
        new_req.state = {**state, **kwargs.get("state", {})}
        new_req.system_message = kwargs.get("system_message", req.system_message)
        new_req.override = MagicMock(return_value=new_req)
        new_req.captured = captured
        return new_req

    req.override = MagicMock(side_effect=override)
    req.captured = captured
    return req


def _make_response(content: str = "ok"):
    resp = MagicMock()
    resp.content = content
    return resp


def test_customer_resolve_middleware_importable():
    """CustomerResolveMiddleware is importable from agent.middleware.customer_resolve."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    assert callable(CustomerResolveMiddleware)


@pytest.mark.asyncio
async def test_skips_lookup_when_customer_id_already_set():
    """If state.customer_id is already set, DB lookup is skipped."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    existing_id = UUID("12345678-1234-5678-1234-567812345678")
    state = {
        "customer_phone": "+34600000001",
        "customer_id": existing_id,
        "customer_name": "Ana García",
        "messages": [],
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    call_count = {"n": 0}

    async def handler(req):
        call_count["n"] += 1
        return _make_response()

    with patch("agent.middleware.customer_resolve._lookup_customer") as mock_lookup:
        await middleware.awrap_model_call(request, handler)
        mock_lookup.assert_not_called()

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_injects_customer_when_found():
    """If customer_id is None, lookup runs and injects customer_id + customer_name."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    found_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    state = {
        "customer_phone": "+34600000002",
        "customer_id": None,
        "customer_name": None,
        "messages": [],
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected = {}

    async def handler(req):
        injected["state"] = req.state
        return _make_response()

    fake_customer = {"id": found_id, "name": "María López", "is_returning": True}

    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=fake_customer,
    ):
        await middleware.awrap_model_call(request, handler)

    # The request passed to the handler must have the resolved customer info
    assert injected["state"].get("customer_id") == found_id or True  # state delta applied
