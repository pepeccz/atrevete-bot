"""
Tests for cookie-aware rate-limiter bypass (admin-auth-cookie-only, PR-2 cleanup).

Covers the 2 cases flagged in the PR-1 verify WARNING:
- A request with a valid admin_token cookie bypasses the rate limit
- A request with no cookie falls through to the standard rate limit
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(path: str, cookie_token: str | None = None) -> MagicMock:
    """Build a minimal Starlette-like Request mock for an admin route."""
    request = MagicMock()
    request.url.path = path
    request.client = MagicMock()
    request.client.host = "1.2.3.4"
    request.headers = {}

    # Simulate cookies dict
    cookies: dict[str, str] = {}
    if cookie_token is not None:
        cookies["admin_token"] = cookie_token
    request.cookies = cookies

    return request


async def _call_next_ok(request):
    """Dummy call_next returning a 200."""
    resp = MagicMock()
    resp.status_code = 200
    return resp


# ---------------------------------------------------------------------------
# Case 1: Valid cookie bypasses rate limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_cookie_bypasses_rate_limit():
    """A request with a structurally valid admin_token cookie must skip rate limiting."""
    from api.middleware.rate_limiting import RateLimitMiddleware

    middleware = RateLimitMiddleware(app=MagicMock())
    request = _make_request("/api/admin/customers", cookie_token="valid-jwt")

    # Patch _is_valid_token to return True and Redis to be irrelevant
    with (
        patch.object(middleware, "_is_valid_token", return_value=True),
        patch("api.middleware.rate_limiting.get_redis_client") as mock_redis,
    ):
        # Redis should NOT be called for rate limiting when cookie is valid
        mock_redis_instance = MagicMock()
        mock_redis.return_value = mock_redis_instance

        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200
    # _apply_rate_limit must NOT have been called (no Redis interaction for rate counting)
    mock_redis_instance.incr.assert_not_called()


# ---------------------------------------------------------------------------
# Case 2: Missing cookie falls through to standard rate limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_cookie_applies_rate_limit():
    """A request with no admin_token cookie must fall through to standard rate limiting."""
    from api.middleware.rate_limiting import RateLimitMiddleware

    middleware = RateLimitMiddleware(app=MagicMock())
    request = _make_request("/api/admin/customers", cookie_token=None)

    with patch("api.middleware.rate_limiting.get_redis_client") as mock_redis:
        # _apply_rate_limit calls redis_client.incr(key) directly (no pipeline)
        mock_redis_instance = AsyncMock()
        mock_redis_instance.incr = AsyncMock(return_value=1)  # 1st request in window
        mock_redis_instance.expire = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_instance

        response = await middleware.dispatch(request, _call_next_ok)

    # Response comes through from call_next (within rate limit)
    assert response.status_code == 200
    # incr was called — rate limit tracking occurred
    mock_redis_instance.incr.assert_called_once()
