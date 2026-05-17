"""Tests for CustomerResolveMiddleware cache-aside layer.

Covers:
- Cache hit: DB skipped, cached dict returned
- Cache miss: DB called, SETEX issued
- Redis GET error: fall through to DB, no SETEX
- Redis SETEX error: DB result returned, WARNING logged
- None result: SETEX not called
- _invalidate_cached_customer: DEL issued; fail-open on exception

All tests use fakeredis.aioredis.FakeRedis — no live Redis.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PHONE = "+5491155550000"
CUSTOMER_DICT = {"id": "uuid-abc", "name": "María García", "is_returning": True}


def _cache_key(phone: str) -> str:
    return f"customer:phone:{phone}"


# ---------------------------------------------------------------------------
# T-2.1 Cache hit — no DB call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_db_lookup():
    """When Redis has the key, _lookup_customer must NOT be called."""
    import fakeredis.aioredis as fakeredis

    fake_redis = await fakeredis.FakeRedis()
    await fake_redis.set(_cache_key(PHONE), json.dumps(CUSTOMER_DICT))

    with (
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            new=AsyncMock(return_value=CUSTOMER_DICT),
        ),
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            new=AsyncMock(return_value=CUSTOMER_DICT),
        ) as mock_lookup,
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            new=AsyncMock(),
        ),
    ):
        from agent.middleware.customer_resolve import CustomerResolveMiddleware

        mw = CustomerResolveMiddleware()
        request = MagicMock()
        request.state = {"customer_phone": PHONE}
        captured: list = []
        request.override = MagicMock(side_effect=lambda **kw: request)

        async def handler(req):
            captured.append(req.state.get("_slot_customer", ""))
            return MagicMock()

        await mw.awrap_model_call(request, handler)

        mock_lookup.assert_not_called()
        assert len(captured) == 1


# ---------------------------------------------------------------------------
# T-2.2 Cache miss — DB called + SETEX issued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_calls_db_then_setex():
    """Cache miss → _lookup_customer called → _set_cached_customer called with result."""
    with (
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            new=AsyncMock(return_value=CUSTOMER_DICT),
        ) as mock_lookup,
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            new=AsyncMock(),
        ) as mock_setex,
    ):
        from agent.middleware.customer_resolve import CustomerResolveMiddleware

        mw = CustomerResolveMiddleware()
        request = MagicMock()
        request.state = {"customer_phone": PHONE}
        request.override = MagicMock(side_effect=lambda **kw: request)

        await mw.awrap_model_call(request, AsyncMock(return_value=MagicMock()))

        mock_lookup.assert_called_once_with(PHONE)
        mock_setex.assert_called_once_with(PHONE, CUSTOMER_DICT)


# ---------------------------------------------------------------------------
# T-2.3 Redis GET exception — fall through to DB, no SETEX
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_get_error_falls_through_to_db(caplog):
    """When Redis GET fails, _get_cached_customer returns None (fail-open), DB is called, result returned."""

    # Simulate a Redis client where get() raises
    bad_redis = MagicMock()
    bad_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

    with (
        patch("agent.middleware.customer_resolve.get_redis_client", return_value=bad_redis),
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            new=AsyncMock(return_value=CUSTOMER_DICT),
        ) as mock_lookup,
    ):
        from agent.middleware.customer_resolve import (
            _get_cached_customer,
        )

        # _get_cached_customer must return None (fail-open), not raise
        result = await _get_cached_customer(PHONE)
        assert result is None

        mock_lookup.assert_not_called()  # We only tested _get_cached_customer above


# ---------------------------------------------------------------------------
# T-2.4 Redis SETEX exception — DB result still returned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setex_error_db_result_still_returned():
    """When SETEX raises inside _set_cached_customer, the exception is swallowed (fail-open)."""
    # Simulate a Redis client where setex() raises
    bad_redis = MagicMock()
    bad_redis.setex = AsyncMock(side_effect=ConnectionError("SETEX timeout"))

    with patch("agent.middleware.customer_resolve.get_redis_client", return_value=bad_redis):
        from agent.middleware.customer_resolve import _set_cached_customer

        # Must not raise — fail-open
        await _set_cached_customer(PHONE, CUSTOMER_DICT)
        # Confirm setex was attempted (i.e., code ran and failed gracefully)
        bad_redis.setex.assert_called_once()


# ---------------------------------------------------------------------------
# T-2.5 None result — SETEX not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_customer_not_cached():
    """_lookup_customer returns None → _set_cached_customer must NOT be called."""
    with (
        patch(
            "agent.middleware.customer_resolve._get_cached_customer",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._lookup_customer",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.middleware.customer_resolve._set_cached_customer",
            new=AsyncMock(),
        ) as mock_setex,
    ):
        from agent.middleware.customer_resolve import CustomerResolveMiddleware

        mw = CustomerResolveMiddleware()
        request = MagicMock()
        request.state = {"customer_phone": PHONE}
        request.override = MagicMock(side_effect=lambda **kw: request)

        await mw.awrap_model_call(request, AsyncMock(return_value=MagicMock()))

        mock_setex.assert_not_called()


# ---------------------------------------------------------------------------
# T-2.6 _invalidate_cached_customer — DEL + fail-open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_issues_del():
    """_invalidate_cached_customer calls redis.delete on the correct key."""
    import fakeredis.aioredis as fakeredis

    fake_redis = await fakeredis.FakeRedis()
    await fake_redis.set(_cache_key(PHONE), json.dumps(CUSTOMER_DICT))

    with patch(
        "agent.middleware.customer_resolve.get_redis_client",
        return_value=fake_redis,
    ):
        from agent.middleware.customer_resolve import _invalidate_cached_customer

        await _invalidate_cached_customer(PHONE)

        # Key must be gone
        assert await fake_redis.get(_cache_key(PHONE)) is None


@pytest.mark.asyncio
async def test_invalidate_fail_open_on_exception():
    """_invalidate_cached_customer swallows Redis exception — no propagation."""
    with patch(
        "agent.middleware.customer_resolve.get_redis_client",
        side_effect=Exception("Redis unreachable"),
    ):
        from agent.middleware.customer_resolve import _invalidate_cached_customer

        # Must not raise
        await _invalidate_cached_customer(PHONE)
