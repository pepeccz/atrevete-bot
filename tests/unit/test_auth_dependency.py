"""
Tests for api/dependencies/auth.py — get_current_user + require_permission factory.

Coverage:
- get_current_user returns AdminUser ORM (not dict) — SC-AUTH-1, SC-AUTH-7, SC-AUTH-8
- get_current_user raises 401 on missing token — SC-PERM-4
- get_current_user raises 401 on invalid/expired JWT
- get_current_user raises 401 for inactive user — SC-AUTH-7
- get_current_user reads role fresh from DB on every request — SC-AUTH-8
- require_permission allows access for admin — SC-PERM-1
- require_permission raises 403 for stylist on admin-only action — SC-PERM-2
- require_permission raises 401 when no JWT (via underlying get_current_user) — SC-PERM-4
- get_current_token_payload exposes jti/exp for logout
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
) -> AdminUser:
    """Return a mock AdminUser with AdminUser type (no DB needed)."""
    user = MagicMock(spec=AdminUser)
    user.id = uuid4()
    user.username = username
    user.role = role
    user.is_active = is_active
    user.display_name = None
    user.last_login_at = None
    user.password_hash = "$2b$12$fakehash"
    return user


def _make_valid_payload(username: str = "admin", jti: str = "test-jti") -> dict:
    """Return a JWT-like payload dict (as returned by jose.jwt.decode)."""
    return {
        "sub": username,
        "type": "admin",
        "jti": jti,
        "exp": 9999999999,
        "iat": 1000000000,
    }


# ---------------------------------------------------------------------------
# T2.1: get_current_user returns AdminUser ORM (not dict)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_returns_admin_user_orm():
    """
    get_current_user must return an AdminUser ORM instance, never a dict.
    Role must come from the DB row (SC-AUTH-8), not from the JWT payload.
    """
    from api.dependencies.auth import get_current_user

    admin_user = _make_admin_user(username="admin", role="admin")
    payload = _make_valid_payload(username="admin")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = admin_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("api.dependencies.auth.verify_token", return_value=payload),
        patch(
            "api.dependencies.auth.check_token_blacklist",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await get_current_user(
            admin_token="valid-token",
            session=mock_session,
        )

    # Must be an AdminUser ORM instance, not a dict
    assert isinstance(result, AdminUser), f"Expected AdminUser, got {type(result)}"
    assert result.username == "admin"
    assert result.role == "admin"


@pytest.mark.asyncio
async def test_get_current_user_raises_401_when_no_token():
    """get_current_user must raise 401 when no cookie token is provided."""
    from api.dependencies.auth import get_current_user

    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(admin_token=None, session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_raises_401_for_invalid_jwt():
    """get_current_user must raise 401 when the JWT is invalid."""
    from api.dependencies.auth import get_current_user

    mock_session = AsyncMock()

    with (
        patch(
            "api.dependencies.auth.verify_token",
            side_effect=HTTPException(status_code=401, detail="Invalid token"),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(admin_token="bad-token", session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_raises_401_for_inactive_user():
    """
    get_current_user must raise 401 when user.is_active is False (SC-AUTH-7).
    Even a valid, non-expired JWT must be rejected.
    """
    from api.dependencies.auth import get_current_user

    inactive_user = _make_admin_user(username="disabled", is_active=False)
    payload = _make_valid_payload(username="disabled")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = inactive_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("api.dependencies.auth.verify_token", return_value=payload),
        patch(
            "api.dependencies.auth.check_token_blacklist",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(admin_token="valid-token", session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_raises_401_for_nonexistent_user():
    """get_current_user must raise 401 when username from JWT doesn't exist in DB."""
    from api.dependencies.auth import get_current_user

    payload = _make_valid_payload(username="ghost")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("api.dependencies.auth.verify_token", return_value=payload),
        patch(
            "api.dependencies.auth.check_token_blacklist",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(admin_token="valid-token", session=mock_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_reads_role_fresh_from_db():
    """
    Role must come from the DB row, not the JWT payload (SC-AUTH-8, FR-AUTH-3).
    Even if JWT was issued when user was 'admin', current 'stylist' role from DB must be used.
    """
    from api.dependencies.auth import get_current_user

    # DB has this user as stylist now (role changed after token was issued)
    stylist_user = _make_admin_user(username="maria", role="stylist")
    # JWT payload doesn't encode role — but even if it did, DB wins
    payload = _make_valid_payload(username="maria")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = stylist_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("api.dependencies.auth.verify_token", return_value=payload),
        patch(
            "api.dependencies.auth.check_token_blacklist",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await get_current_user(admin_token="valid-token", session=mock_session)

    # Role from DB, not from any JWT claim
    assert result.role == "stylist"


@pytest.mark.asyncio
async def test_get_current_user_raises_401_for_revoked_token():
    """get_current_user must raise 401 when token JTI is blacklisted."""
    from api.dependencies.auth import get_current_user

    payload = _make_valid_payload(username="admin", jti="revoked-jti")

    mock_session = AsyncMock()

    with (
        patch("api.dependencies.auth.verify_token", return_value=payload),
        patch(
            "api.dependencies.auth.check_token_blacklist", new_callable=AsyncMock, return_value=True
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(admin_token="revoked-token", session=mock_session)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# T2.3: require_permission factory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_permission_allows_admin():
    """require_permission('users:manage') must return user when role is admin (SC-PERM-1)."""
    from api.dependencies.auth import require_permission

    admin_user = _make_admin_user(role="admin")
    checker = require_permission("users:manage")

    with patch(
        "api.dependencies.auth.get_current_user", new_callable=AsyncMock, return_value=admin_user
    ):
        result = await checker(current_user=admin_user)

    assert result is admin_user


@pytest.mark.asyncio
async def test_require_permission_raises_403_for_stylist():
    """require_permission('users:manage') must raise 403 for stylist role (SC-PERM-2)."""
    from api.dependencies.auth import require_permission

    stylist_user = _make_admin_user(role="stylist")
    checker = require_permission("users:manage")

    with pytest.raises(HTTPException) as exc_info:
        await checker(current_user=stylist_user)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_permission_allows_shared_permission_for_stylist():
    """require_permission for a shared permission must pass for stylist (SC-PERM-3)."""
    from api.dependencies.auth import require_permission

    stylist_user = _make_admin_user(role="stylist")
    checker = require_permission("appointments:read")

    result = await checker(current_user=stylist_user)
    assert result is stylist_user


@pytest.mark.asyncio
async def test_require_permission_unknown_role_raises_403():
    """require_permission for an unknown role must raise 403 (unknown role → no permissions)."""
    from api.dependencies.auth import require_permission

    unknown_user = _make_admin_user(role="unknown_role")
    checker = require_permission("appointments:read")

    with pytest.raises(HTTPException) as exc_info:
        await checker(current_user=unknown_user)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# T2.3: get_current_token_payload exposed for logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_token_payload_returns_dict_with_jti():
    """get_current_token_payload must return raw JWT payload dict (for logout JTI use)."""
    from api.dependencies.auth import get_current_token_payload

    payload = _make_valid_payload(username="admin", jti="logout-jti")

    with (
        patch("api.dependencies.auth.verify_token", return_value=payload),
        patch(
            "api.dependencies.auth.check_token_blacklist",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await get_current_token_payload(admin_token="valid-token")

    assert isinstance(result, dict)
    assert result["jti"] == "logout-jti"
    assert result["sub"] == "admin"
