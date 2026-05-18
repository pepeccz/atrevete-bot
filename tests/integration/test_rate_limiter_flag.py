"""T-01 smoke test: RATE_LIMITING_ENABLED=false bypasses the middleware.

When the flag is False any endpoint (other than those that require Redis) must
return a non-429 response, regardless of how many times the same IP hits it.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_rate_limiter_disabled_passes_through(monkeypatch):
    """GIVEN RATE_LIMITING_ENABLED=false, WHEN hitting any endpoint, THEN no 429."""
    # Ensure the flag is off — conftest already sets it, but be explicit here.
    monkeypatch.setenv("RATE_LIMITING_ENABLED", "false")

    # Invalidate the lru_cache so the new env value is picked up.
    from shared.config import get_settings
    get_settings.cache_clear()

    from api.middleware.rate_limiting import RateLimitMiddleware

    received: list = []

    async def fake_next(request):
        from starlette.responses import Response
        return Response(content="ok", status_code=200)

    middleware = RateLimitMiddleware(app=None)

    # Simulate a request object with .url.path and .client.host
    from unittest.mock import MagicMock
    request = MagicMock()
    request.url.path = "/api/admin/conversations"
    request.client.host = "1.2.3.4"
    request.headers.get.return_value = None
    request.cookies.get.return_value = None

    response = await middleware.dispatch(request, fake_next)
    assert response.status_code != 429

    # Restore settings cache for subsequent tests
    get_settings.cache_clear()
