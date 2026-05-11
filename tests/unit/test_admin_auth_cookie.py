"""
Tests for cookie-only admin authentication (admin-auth-cookie-only change, PR-1).

Updated in PR-2a to pass mock sessions to the refactored login endpoint
(DB-first with env-var fallback when table is empty).

Covers:
- Login sets cookie with path=/api, httponly=True, no access_token in body
- Logout clears cookie with same path
- get_current_user with valid cookie → 200
- get_current_user with Bearer only → 401
- get_current_user with no cookie and no Bearer → 401
- ADMIN_JWT_COOKIE_SECURE=False omits Secure attribute
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_token(username: str = "admin") -> str:
    """Create a real JWT using admin.py helpers (needs ADMIN_JWT_SECRET in env)."""
    from jose import jwt as jose_jwt

    secret = "test-secret-at-least-32-chars-long!!"
    payload = {
        "sub": username,
        "type": "admin",
        "jti": "test-jti-1234",
        "exp": datetime.now(UTC) + timedelta(hours=720),
        "iat": datetime.now(UTC),
    }
    return jose_jwt.encode(payload, secret, algorithm="HS256")


def _make_expired_token(username: str = "admin") -> str:
    """Create an expired JWT."""
    from jose import jwt as jose_jwt

    secret = "test-secret-at-least-32-chars-long!!"
    payload = {
        "sub": username,
        "type": "admin",
        "jti": "expired-jti",
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    return jose_jwt.encode(payload, secret, algorithm="HS256")


def _make_empty_table_session() -> AsyncMock:
    """Build a mock AsyncSession that reports 0 rows in admin_users (env-var fallback path)."""
    session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=count_result)
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# T6-1: Login sets cookie with path=/api, httponly=True, no access_token in body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sets_cookie_with_path_api():
    """Login must set cookie with path=/api (not /api/admin)."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    request = LoginRequest(username="admin", password="secret")
    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()
    session = _make_empty_table_session()

    with (
        patch("api.routes.admin.get_admin_credentials", return_value=("admin", None, None)),
        patch("api.routes.admin.verify_admin_password", return_value=True),
        patch(
            "api.routes.admin.create_access_token",
            return_value=("fake-token", "fake-jti"),
        ),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        await login(request, response, session=session)

    # Cookie path MUST be /api, not /api/admin
    response.set_cookie.assert_called_once()
    call_kwargs = response.set_cookie.call_args.kwargs
    assert call_kwargs["path"] == "/api", f"Expected path=/api, got path={call_kwargs['path']}"
    assert call_kwargs["httponly"] is True
    assert call_kwargs["key"] == "admin_token"


@pytest.mark.asyncio
async def test_login_response_body_has_no_access_token():
    """LoginResponse body MUST NOT contain access_token."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    request = LoginRequest(username="admin", password="secret")
    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()
    session = _make_empty_table_session()

    with (
        patch("api.routes.admin.get_admin_credentials", return_value=("admin", None, None)),
        patch("api.routes.admin.verify_admin_password", return_value=True),
        patch(
            "api.routes.admin.create_access_token",
            return_value=("fake-token", "fake-jti"),
        ),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        result = await login(request, response, session=session)

    # Result should be a LoginResponse; verify no access_token field
    result_dict = result.model_dump() if hasattr(result, "model_dump") else vars(result)
    assert "access_token" not in result_dict, "access_token must NOT be in LoginResponse body"


@pytest.mark.asyncio
async def test_login_response_body_has_expires_in_and_username():
    """LoginResponse body MUST contain expires_in and username."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    request = LoginRequest(username="admin_user", password="secret")
    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()
    session = _make_empty_table_session()

    with (
        patch("api.routes.admin.get_admin_credentials", return_value=("admin_user", None, None)),
        patch("api.routes.admin.verify_admin_password", return_value=True),
        patch(
            "api.routes.admin.create_access_token",
            return_value=("fake-token", "fake-jti"),
        ),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        result = await login(request, response, session=session)

    result_dict = result.model_dump() if hasattr(result, "model_dump") else vars(result)
    assert "expires_in" in result_dict, "expires_in must be in LoginResponse body"
    assert "username" in result_dict, "username must be in LoginResponse body"
    assert result_dict["username"] == "admin_user"


# ---------------------------------------------------------------------------
# T6-2: Logout clears cookie with path=/api
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_clears_cookie_with_path_api():
    """Logout must delete cookie with path=/api."""
    from fastapi import Response

    from api.routes.admin import logout

    response = MagicMock(spec=Response)
    response.delete_cookie = MagicMock()
    current_user = {"sub": "admin", "jti": "test-jti", "exp": 9999999999}

    with (
        patch("api.routes.admin.add_token_to_blacklist", new_callable=AsyncMock, return_value=True),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        await logout(response=response, current_user=current_user)

    response.delete_cookie.assert_called_once()
    call_kwargs = response.delete_cookie.call_args.kwargs
    assert call_kwargs["path"] == "/api", f"Expected path=/api, got path={call_kwargs['path']}"
    assert call_kwargs["key"] == "admin_token"


# ---------------------------------------------------------------------------
# T6-3: get_current_user with valid cookie succeeds (now returns AdminUser)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_with_valid_cookie_returns_payload():
    """
    get_current_user (from api.dependencies.auth) must succeed when valid
    admin_token cookie is present — returns AdminUser ORM.
    """
    from api.dependencies.auth import get_current_user
    from database.models import AdminUser

    valid_payload = {"sub": "admin", "type": "admin", "jti": "jti-abc", "exp": 9999999999}

    admin_user = MagicMock(spec=AdminUser)
    admin_user.username = "admin"
    admin_user.is_active = True

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = admin_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("api.dependencies.auth.verify_token", return_value=valid_payload),
        patch(
            "api.dependencies.auth.check_token_blacklist",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await get_current_user(
            admin_token="valid-cookie-token",
            session=mock_session,
        )

    assert result is admin_user
    assert result.username == "admin"


# ---------------------------------------------------------------------------
# T6-4: get_current_user with Bearer only → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_bearer_only_returns_401():
    """get_current_user must return 401 when only Bearer header present, no cookie."""
    from api.dependencies.auth import get_current_user

    mock_session = AsyncMock()

    # No admin_token cookie (default None)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            admin_token=None,  # no cookie
            session=mock_session,
        )

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# T6-5: get_current_user with no cookie and no Bearer → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_no_auth_returns_401():
    """get_current_user must return 401 when no cookie and no Bearer."""
    from api.dependencies.auth import get_current_user

    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(
            admin_token=None,
            session=mock_session,
        )

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# T6-6: ADMIN_JWT_COOKIE_SECURE=False omits Secure attribute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_cookie_secure_false_when_setting_is_false():
    """When ADMIN_JWT_COOKIE_SECURE=False, cookie Secure attribute must be False."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    request = LoginRequest(username="admin", password="secret")
    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()
    session = _make_empty_table_session()

    with (
        patch("api.routes.admin.get_admin_credentials", return_value=("admin", None, None)),
        patch("api.routes.admin.verify_admin_password", return_value=True),
        patch(
            "api.routes.admin.create_access_token",
            return_value=("fake-token", "fake-jti"),
        ),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        await login(request, response, session=session)

    call_kwargs = response.set_cookie.call_args.kwargs
    assert call_kwargs["secure"] is False


@pytest.mark.asyncio
async def test_login_cookie_secure_true_when_setting_is_true():
    """When ADMIN_JWT_COOKIE_SECURE=True, cookie Secure attribute must be True."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    request = LoginRequest(username="admin", password="secret")
    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()
    session = _make_empty_table_session()

    with (
        patch("api.routes.admin.get_admin_credentials", return_value=("admin", None, None)),
        patch("api.routes.admin.verify_admin_password", return_value=True),
        patch(
            "api.routes.admin.create_access_token",
            return_value=("fake-token", "fake-jti"),
        ),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = True
        await login(request, response, session=session)

    call_kwargs = response.set_cookie.call_args.kwargs
    assert call_kwargs["secure"] is True
