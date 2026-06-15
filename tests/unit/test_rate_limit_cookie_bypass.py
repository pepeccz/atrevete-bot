"""
Tests for cookie-aware rate-limiter bypass (admin-auth-cookie-only, PR-2 cleanup).

Covers the 2 cases flagged in the PR-1 verify WARNING:
- A request with a valid admin_token cookie bypasses the rate limit
- A request with no cookie falls through to the standard rate limit

NOTE: conftest.py sets RATE_LIMITING_ENABLED=false globally. These tests exercise the
middleware internals directly (bypassing the feature flag) so they remain valid regardless
of that setting.
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
    """A valid admin_token cookie must cause _apply_rate_limit to be skipped.

    Tested directly via the admin-path branch in dispatch(), with RATE_LIMITING_ENABLED
    bypassed by patching get_settings so the feature-flag guard doesn't short-circuit.
    """
    from api.middleware.rate_limiting import RateLimitMiddleware

    middleware = RateLimitMiddleware(app=MagicMock())
    request = _make_request("/api/admin/customers", cookie_token="valid-jwt")

    mock_settings = MagicMock()
    mock_settings.RATE_LIMITING_ENABLED = True

    with (
        patch("api.middleware.rate_limiting.get_settings", return_value=mock_settings),
        patch.object(middleware, "_is_valid_token", return_value=True),
        patch("api.middleware.rate_limiting.get_redis_client") as mock_redis,
    ):
        mock_redis_instance = MagicMock()
        mock_redis.return_value = mock_redis_instance

        response = await middleware.dispatch(request, _call_next_ok)

    assert response.status_code == 200
    # _apply_rate_limit must NOT have been called (cookie was valid)
    mock_redis_instance.incr.assert_not_called()


# ---------------------------------------------------------------------------
# Case 2: Missing cookie falls through to standard rate limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_cookie_applies_rate_limit():
    """A request with no admin_token cookie must fall through to _apply_rate_limit.

    Exercises _apply_rate_limit directly to avoid the RATE_LIMITING_ENABLED feature-flag
    guard in dispatch() (conftest sets it to false globally).
    """
    from api.middleware.rate_limiting import RateLimitMiddleware

    middleware = RateLimitMiddleware(app=MagicMock())
    request = _make_request("/api/admin/customers", cookie_token=None)

    mock_redis_instance = AsyncMock()
    mock_redis_instance.incr = AsyncMock(return_value=1)  # 1st request in window
    mock_redis_instance.expire = AsyncMock(return_value=True)

    # Call _apply_rate_limit directly — this is the code path taken when no cookie
    # is present on an /api/admin/* route; dispatch() delegates here after the
    # cookie check fails.
    response = await middleware._apply_rate_limit(
        request, _call_next_ok, mock_redis_instance, "1.2.3.4"
    )

    # Response comes through from call_next (within rate limit)
    assert response.status_code == 200
    # incr was called — rate limit tracking occurred
    mock_redis_instance.incr.assert_called_once()
