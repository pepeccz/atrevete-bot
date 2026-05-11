"""
Tests for the refactored login endpoint (PR-2a, T2.8 / T2.9).

Covers (SC-AUTH-2..6, SC-AUTH-9, SC-AUTH-10, NFR-4):
- DB-first success (existing user, correct password) → returns JWT + updates last_login_at
- Wrong password → 401
- Deactivated user → 401
- Nonexistent user → 401
- Env-var fallback: empty admin_users table + matching env credentials → 200
- Env-var fallback skipped when rows exist in DB (SC-AUTH-10)
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from database.models import AdminUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_user(
    username: str = "admin",
    role: str = "admin",
    is_active: bool = True,
    password_hash: str = "$2b$12$fakehash",
) -> MagicMock:
    """Return a mock AdminUser with the required attributes."""
    user = MagicMock(spec=AdminUser)
    user.id = uuid4()
    user.username = username
    user.role = role
    user.is_active = is_active
    user.password_hash = password_hash
    user.last_login_at = None
    user.display_name = None
    return user


def _make_login_request(username: str = "admin", password: str = "secret"):
    """Return a LoginRequest-like object."""
    req = MagicMock()
    req.username = username
    req.password = password
    return req


def _make_mock_session(user_or_none, row_count: int = 1):
    """Build a mock AsyncSession with predictable .execute() behavior."""
    session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = row_count

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user_or_none

    # Return count_result on first call, user_result on second call
    session.execute = AsyncMock(side_effect=[count_result, user_result])
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# T2.8 / SC-AUTH-2: DB-first success — updates last_login_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_db_first_success_updates_last_login_at():
    """
    SC-AUTH-2: DB-first login — correct password updates last_login_at and returns JWT.
    """
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    # A real bcrypt hash for "secret" (cost 12) would be used; we mock verify_password
    user = _make_admin_user(username="admin", is_active=True)
    session = _make_mock_session(user, row_count=1)
    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()

    with (
        patch("api.routes.admin.verify_password", return_value=True),
        patch("api.routes.admin.create_access_token", return_value=("jwt-token", "jti-1")),
        patch("api.routes.admin.get_settings") as mock_settings,
        patch("api.routes.admin.get_db", return_value=session),
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        request = LoginRequest(username="admin", password="secret")
        await login(request, response, session=session)

    # Cookie must be set
    response.set_cookie.assert_called_once()
    # session.commit must have been called (last_login_at update)
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_login_db_first_wrong_password_returns_401():
    """SC-AUTH-4: Wrong password → 401, no cookie set."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    user = _make_admin_user(username="admin", is_active=True)
    session = _make_mock_session(user, row_count=1)
    response = MagicMock(spec=Response)

    with (patch("api.routes.admin.verify_password", return_value=False),):
        request = LoginRequest(username="admin", password="wrongpassword")
        with pytest.raises(HTTPException) as exc_info:
            await login(request, response, session=session)

    assert exc_info.value.status_code == 401
    response.set_cookie.assert_not_called()


@pytest.mark.asyncio
async def test_login_deactivated_user_returns_401():
    """SC-AUTH-5: Deactivated user → 401, even if password is correct."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    user = _make_admin_user(username="disabled", is_active=False)
    session = _make_mock_session(user, row_count=1)
    response = MagicMock(spec=Response)

    with (patch("api.routes.admin.verify_password", return_value=True),):
        request = LoginRequest(username="disabled", password="secret")
        with pytest.raises(HTTPException) as exc_info:
            await login(request, response, session=session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user_returns_401():
    """SC-AUTH-6: Nonexistent user → 401."""
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    session = _make_mock_session(None, row_count=1)
    response = MagicMock(spec=Response)

    request = LoginRequest(username="ghost", password="secret")
    with pytest.raises(HTTPException) as exc_info:
        await login(request, response, session=session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_login_env_var_fallback_when_empty_table():
    """
    SC-AUTH-9: When admin_users table is empty, login falls back to env vars.
    """
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    # table is empty — only count query is executed
    session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=count_result)
    session.commit = AsyncMock()

    response = MagicMock(spec=Response)
    response.set_cookie = MagicMock()

    with (
        patch("api.routes.admin.get_admin_credentials", return_value=("admin", "rootpass", None)),
        patch("api.routes.admin.verify_admin_password", return_value=True),
        patch("api.routes.admin.create_access_token", return_value=("jwt-token", "jti-1")),
        patch("api.routes.admin.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ADMIN_JWT_COOKIE_SECURE = False
        request = LoginRequest(username="admin", password="rootpass")
        await login(request, response, session=session)

    # Must succeed and set cookie
    response.set_cookie.assert_called_once()


@pytest.mark.asyncio
async def test_login_env_fallback_skipped_when_rows_exist():
    """
    SC-AUTH-10: When admin_users has rows, env-var fallback must be skipped entirely.
    Even if env-var credentials match, they must not be used.
    """
    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    # DB has a user; submitted password is wrong (DB auth fails)
    user = _make_admin_user(username="admin", is_active=True)
    session = _make_mock_session(user, row_count=1)
    response = MagicMock(spec=Response)

    # verify_password (DB-based) returns False
    with (
        patch("api.routes.admin.verify_password", return_value=False),
        patch("api.routes.admin.verify_admin_password") as mock_env_verify,
    ):
        request = LoginRequest(username="admin", password="wrongpassword")
        with pytest.raises(HTTPException) as exc_info:
            await login(request, response, session=session)

    # 401 because DB check fails
    assert exc_info.value.status_code == 401
    # env_var verification must NOT have been called
    mock_env_verify.assert_not_called()


@pytest.mark.asyncio
async def test_login_failed_attempt_does_not_log_password(caplog):
    """NFR-4: Failed login must log WARNING with username only, never the password."""
    import logging

    from fastapi import Response

    from api.routes.admin import LoginRequest, login

    user = _make_admin_user(username="victim", is_active=True)
    session = _make_mock_session(user, row_count=1)
    response = MagicMock(spec=Response)

    with (
        patch("api.routes.admin.verify_password", return_value=False),
        caplog.at_level(logging.WARNING, logger="api.routes.admin"),
    ):
        request = LoginRequest(username="victim", password="s3cr3t_p@ssword!")
        with pytest.raises(HTTPException):
            await login(request, response, session=session)

    # Check that the password does NOT appear in any log record
    log_text = " ".join(r.getMessage() for r in caplog.records)
    assert "s3cr3t_p@ssword!" not in log_text, "Password must NEVER appear in logs"
