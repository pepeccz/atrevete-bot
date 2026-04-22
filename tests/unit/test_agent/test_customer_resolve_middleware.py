"""T2.1 RED — CustomerResolveMiddleware injects phone-only ## Cliente block when DB miss.

When _lookup_customer returns None but state.customer_phone is set, the middleware
MUST inject a '## Cliente\n- Teléfono: {phone}' block into the system prompt.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_request(state: dict, system_content: str = "base system"):
    """Build a minimal ModelRequest mock with a working override()."""
    from langchain_core.messages import SystemMessage

    req = MagicMock()
    req.state = state
    req.system_message = SystemMessage(content=system_content)
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


@pytest.mark.asyncio
async def test_injects_phone_when_db_miss():
    """When _lookup_customer returns None and phone is set, inject phone-only ## Cliente block."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    phone = "+34123456789"
    state = {
        "customer_phone": phone,
        "customer_id": None,
        "customer_name": None,
        "messages": [],
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    received_requests = []

    async def handler(req):
        received_requests.append(req)
        return MagicMock()

    with (
        patch_lookup(return_value=None) as mock_lookup,
    ):
        await middleware.awrap_model_call(request, handler)
        mock_lookup.assert_called_once_with(phone)

    assert len(received_requests) == 1, "handler must be called exactly once"
    passed_req = received_requests[0]
    system_content = passed_req.system_message.content

    assert "## Cliente" in system_content, (
        "System prompt must contain '## Cliente' block for new customers"
    )
    assert f"Teléfono: {phone}" in system_content, (
        f"System prompt must contain 'Teléfono: {phone}'"
    )


@pytest.mark.asyncio
async def test_does_not_inject_phone_block_when_phone_absent():
    """When phone is absent, middleware passes through without injecting ## Cliente."""
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    state = {
        "customer_phone": "",
        "customer_id": None,
        "customer_name": None,
        "messages": [],
    }
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    received_requests = []

    async def handler(req):
        received_requests.append(req)
        return MagicMock()

    with patch_lookup(return_value=None):
        await middleware.awrap_model_call(request, handler)

    passed_req = received_requests[0]
    system_content = passed_req.system_message.content
    assert "## Cliente" not in system_content, (
        "## Cliente block must NOT be injected when phone is absent"
    )


# ---------------------------------------------------------------------------
# Helper — thin wrapper around unittest.mock.patch to keep tests readable
# ---------------------------------------------------------------------------

from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def patch_lookup(return_value):
    with patch(
        "agent.middleware.customer_resolve._lookup_customer",
        new_callable=AsyncMock,
        return_value=return_value,
    ) as m:
        yield m
