"""
FastAPI authentication dependencies.

Centralises get_current_user (returns AdminUser ORM) and require_permission
factory so that all routes consume a single, testable auth surface.

Design rationale:
- get_current_user reads role fresh from DB on every request (FR-AUTH-3 /
  SC-AUTH-8) — the JWT payload sub-claim is used only to look up the DB row.
- require_permission wraps get_current_user to add RBAC gating in one line.
- get_current_token_payload provides raw JWT payload (jti/exp) for logout only.

Backwards-compat:
- Existing JWTs with sub=username continue to work (no JWT format change,
  FR-AUTH-6 / NFR-3).
- Cookie name 'admin_token' and JWT algorithm HS256 match the existing admin.py
  constants so the transition is seamless.

Note on circular imports:
  admin.py contains the JWT helpers (get_jwt_secret, check_token_blacklist,
  verify_token). Rather than importing from admin.py here (which creates a cycle
  because admin.py imports AdminUser from database.models and we need those same
  helpers), we duplicate the minimal JWT decode + blacklist check here.
  Once admin.py is split into a proper auth service this duplication goes away.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_db
from database.models import AdminUser
from shared.config import get_settings
from shared.permissions import has_permission

logger = logging.getLogger(__name__)

# JWT constants — must stay in sync with api/routes/admin.py
_JWT_ALGORITHM = "HS256"
_JWT_COOKIE_NAME = "admin_token"


def _get_jwt_secret() -> str:
    """Return ADMIN_JWT_SECRET from Pydantic Settings."""
    secret = get_settings().ADMIN_JWT_SECRET
    if not secret:
        raise RuntimeError(
            "ADMIN_JWT_SECRET must be set in environment variables. "
            "Generate a secure secret with: openssl rand -hex 32"
        )
    return secret


def verify_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token string.

    Raises HTTPException 401 on any decode failure or wrong token type.
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
        if payload.get("type") != "admin":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc


async def check_token_blacklist(jti: str) -> bool:
    """Return True if the JTI has been blacklisted (revoked via logout)."""
    try:
        from shared.redis_client import get_redis_client

        redis_client = await get_redis_client()
        if redis_client is None:
            return False
        result = await redis_client.get(f"token_blacklist:{jti}")
        return result is not None
    except Exception as exc:  # noqa: BLE001
        logger.error("Error checking token blacklist: %s", exc)
        return False


async def get_current_user(
    admin_token: Annotated[str | None, Cookie()] = None,
    session: AsyncSession = Depends(get_db),
) -> AdminUser:
    """
    FastAPI dependency: decode JWT cookie and return AdminUser from DB.

    - Reads role fresh from DB on every request (FR-AUTH-3, SC-AUTH-8).
    - Raises 401 if token is missing, invalid, revoked, or user is inactive.
    - Never trusts role from JWT payload (NFR-2 / FR-AUTH-3).
    """
    if not admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload: dict[str, Any] = verify_token(admin_token)

    jti = payload.get("jti")
    if jti and await check_token_blacklist(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    username: str | None = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
        )

    result = await session.execute(select(AdminUser).where(AdminUser.username == username))
    user: AdminUser | None = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


async def get_current_token_payload(
    admin_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, Any]:
    """
    FastAPI dependency: return raw JWT payload dict.

    Used exclusively by the logout endpoint which needs jti + exp to blacklist
    the token.  Does NOT perform a DB lookup — use get_current_user for that.
    """
    if not admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload: dict[str, Any] = verify_token(admin_token)

    jti = payload.get("jti")
    if jti and await check_token_blacklist(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    return payload


def require_permission(action: str) -> Callable[..., Awaitable[AdminUser]]:
    """
    Dependency factory: asserts the current user holds `action`.

    Usage::

        @router.get("/sensitive")
        async def sensitive(
            current_user: AdminUser = Depends(require_permission("users:manage")),
        ): ...

    - Returns the AdminUser on success.
    - Raises HTTP 403 when the user's role lacks the permission (FR-PERM-3,
      SC-PERM-2).
    - Raises HTTP 401 when there is no valid token (via get_current_user,
      SC-PERM-4).
    """

    async def _checker(
        current_user: AdminUser = Depends(get_current_user),
    ) -> AdminUser:
        if not has_permission(current_user.role, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: missing permission '{action}'",
            )
        return current_user

    _checker.__name__ = f"require_permission_{action.replace(':', '_')}"
    return _checker
