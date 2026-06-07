"""Policy fields extension tests for CustomerResolveMiddleware (T23-T24).

Tests cover:
- T23: _lookup_customer returns dict with policy_accepted_at and policy_version keys
- T24: <customer> block renders three policy states correctly:
    1. Accepted at current version → "aceptada v{X} el {dd/mm/yyyy}"
    2. Accepted at stale version → "aceptada v{stored} el {dd/mm/yyyy} (versión obsoleta)"
    3. Never accepted (None) → "no aceptada"

Refs: Spec §3, S-7 / Design §5.1-5.2 / Tasks T23-T24
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# T23 — _lookup_customer returns policy fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_customer_returns_policy_fields():
    """T23: _lookup_customer returns dict with policy_accepted_at and policy_version.

    Both fields must be present when the customer has accepted and when they haven't.
    Spec §3 / Design §5.1
    """
    from agent.middleware.customer_resolve import _lookup_customer

    accepted_at = datetime.now(UTC) - timedelta(days=3)

    customer_mock = MagicMock()
    customer_mock.id = uuid4()
    customer_mock.name = "Ana García"
    customer_mock.phone = "+34611000001"
    customer_mock.notes = None
    customer_mock.policy_accepted_at = accepted_at
    customer_mock.policy_version = "1.0"

    appt_mock = MagicMock()  # has appointment → is_returning=True

    scalars_customer = MagicMock()
    scalars_customer.first.return_value = customer_mock

    scalars_appt = MagicMock()
    scalars_appt.first.return_value = appt_mock

    result_customer = MagicMock()
    result_customer.scalars.return_value = scalars_customer

    result_appt = MagicMock()
    result_appt.scalars.return_value = scalars_appt

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result_customer, result_appt])

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("database.connection.get_async_session", return_value=ctx):
        result = await _lookup_customer("+34611000001")

    assert result is not None, "Expected dict, got None"
    assert "policy_accepted_at" in result, (
        f"Expected 'policy_accepted_at' in result dict, got keys: {list(result.keys())}"
    )
    assert "policy_version" in result, (
        f"Expected 'policy_version' in result dict, got keys: {list(result.keys())}"
    )
    assert result["policy_accepted_at"] == accepted_at, (
        f"Expected policy_accepted_at={accepted_at}, got: {result['policy_accepted_at']}"
    )
    assert result["policy_version"] == "1.0", (
        f"Expected policy_version='1.0', got: {result['policy_version']}"
    )


@pytest.mark.asyncio
async def test_lookup_customer_returns_policy_fields_when_none():
    """T23b: _lookup_customer returns policy fields even when never accepted (None).

    Spec §3 / Design §5.1
    """
    from agent.middleware.customer_resolve import _lookup_customer

    customer_mock = MagicMock()
    customer_mock.id = uuid4()
    customer_mock.name = "Carlos Ruiz"
    customer_mock.phone = "+34611000002"
    customer_mock.notes = None
    customer_mock.policy_accepted_at = None  # never accepted
    customer_mock.policy_version = None

    scalars_customer = MagicMock()
    scalars_customer.first.return_value = customer_mock

    scalars_appt = MagicMock()
    scalars_appt.first.return_value = None  # no appointments

    result_customer = MagicMock()
    result_customer.scalars.return_value = scalars_customer

    result_appt = MagicMock()
    result_appt.scalars.return_value = scalars_appt

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result_customer, result_appt])

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("database.connection.get_async_session", return_value=ctx):
        result = await _lookup_customer("+34611000002")

    assert result is not None
    assert "policy_accepted_at" in result
    assert "policy_version" in result
    assert result["policy_accepted_at"] is None
    assert result["policy_version"] is None


# ---------------------------------------------------------------------------
# T24 — <customer> block three states
# ---------------------------------------------------------------------------


def _make_request(state: dict):
    """Build a minimal ModelRequest mock."""
    req = MagicMock()
    req.state = state

    captured = {}

    def override(**kwargs):
        captured.update(kwargs)
        new_req = MagicMock()
        new_req.state = {**state, **kwargs.get("state", {})}
        new_req.override = MagicMock(return_value=new_req)
        new_req.captured = captured
        return new_req

    req.override = MagicMock(side_effect=override)
    req.captured = captured
    return req


def _make_response():
    resp = MagicMock()
    resp.content = "ok"
    return resp


@pytest.mark.asyncio
async def test_customer_block_accepted_current_version():
    """T24a: customer accepted current policy version → block shows 'aceptada v{X} el {date}'.

    Design §5.2
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    accepted_at = datetime(2026, 5, 15, 10, 0, 0, tzinfo=UTC)

    customer_data = {
        "id": uuid4(),
        "name": "María López",
        "is_returning": True,
        "notes": None,
        "policy_accepted_at": accepted_at,
        "policy_version": "1.0",
    }

    state = {"customer_phone": "+34611000003", "customer_id": None, "customer_name": None}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_slot = {}

    async def handler(req):
        injected_slot["slot"] = req.state.get("_slot_customer", "")
        return _make_response()

    def _get_settings_mock():
        s = MagicMock()
        s.POLICY_VERSION = "1.0"
        return s

    with (
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            AsyncMock(return_value=customer_data),
        ),
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            AsyncMock(),
        ),
        patch(
            "agent.services.customer_memory_service.read_customer_memories",
            AsyncMock(return_value=None),
        ),
        patch("agent.middleware.customer_resolve.get_settings", side_effect=_get_settings_mock),
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_slot.get("slot", "")
    assert "Política privacidad:" in slot, f"Expected policy line in <customer> block: {slot}"
    assert "aceptada" in slot, f"Expected 'aceptada' in policy line: {slot}"
    assert "v1.0" in slot, f"Expected version 'v1.0' in policy line: {slot}"
    # Date should be formatted dd/mm/yyyy
    assert "15/05/2026" in slot, f"Expected date '15/05/2026' in policy line: {slot}"
    assert "obsoleta" not in slot, f"Should NOT show 'obsoleta' for current version: {slot}"


@pytest.mark.asyncio
async def test_customer_block_accepted_stale_version():
    """T24b: customer accepted stale policy version → block shows 'aceptada v{old} ... (versión obsoleta)'.

    Design §5.2
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    accepted_at = datetime(2026, 1, 10, 10, 0, 0, tzinfo=UTC)

    customer_data = {
        "id": uuid4(),
        "name": "Pedro Torres",
        "is_returning": True,
        "notes": None,
        "policy_accepted_at": accepted_at,
        "policy_version": "0.9",  # stale
    }

    state = {"customer_phone": "+34611000004", "customer_id": None, "customer_name": None}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_slot = {}

    async def handler(req):
        injected_slot["slot"] = req.state.get("_slot_customer", "")
        return _make_response()

    def _get_settings_mock():
        s = MagicMock()
        s.POLICY_VERSION = "1.0"
        return s

    with (
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            AsyncMock(return_value=customer_data),
        ),
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            AsyncMock(),
        ),
        patch(
            "agent.services.customer_memory_service.read_customer_memories",
            AsyncMock(return_value=None),
        ),
        patch("agent.middleware.customer_resolve.get_settings", side_effect=_get_settings_mock),
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_slot.get("slot", "")
    assert "Política privacidad:" in slot, f"Expected policy line in <customer> block: {slot}"
    assert "aceptada" in slot, f"Expected 'aceptada' in policy line: {slot}"
    assert "v0.9" in slot, f"Expected stored version 'v0.9' in policy line: {slot}"
    assert "obsoleta" in slot, f"Expected 'obsoleta' for stale version: {slot}"


@pytest.mark.asyncio
async def test_customer_block_never_accepted():
    """T24c: customer never accepted policy → block shows 'no aceptada'.

    Design §5.2
    """
    from agent.middleware.customer_resolve import CustomerResolveMiddleware

    customer_data = {
        "id": uuid4(),
        "name": "Laura Sanz",
        "is_returning": False,
        "notes": None,
        "policy_accepted_at": None,
        "policy_version": None,
    }

    state = {"customer_phone": "+34611000005", "customer_id": None, "customer_name": None}
    middleware = CustomerResolveMiddleware()
    request = _make_request(state=state)

    injected_slot = {}

    async def handler(req):
        injected_slot["slot"] = req.state.get("_slot_customer", "")
        return _make_response()

    def _get_settings_mock():
        s = MagicMock()
        s.POLICY_VERSION = "1.0"
        return s

    with (
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            AsyncMock(return_value=customer_data),
        ),
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            AsyncMock(),
        ),
        patch(
            "agent.services.customer_memory_service.read_customer_memories",
            AsyncMock(return_value=None),
        ),
        patch("agent.middleware.customer_resolve.get_settings", side_effect=_get_settings_mock),
    ):
        await middleware.awrap_model_call(request, handler)

    slot = injected_slot.get("slot", "")
    assert "Política privacidad:" in slot, f"Expected policy line in <customer> block: {slot}"
    assert "no aceptada" in slot, f"Expected 'no aceptada' in policy line: {slot}"
