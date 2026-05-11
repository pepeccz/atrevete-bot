"""
User CRUD endpoints — api/routes/users.py

Provides admin-facing user management under /api/admin/users.
All endpoints are gated by require_permission("users:manage") (FR-USERS-1, SC-USERS-4).

Endpoint catalogue:
  GET    /                        — list users (paginated)
  GET    /{user_id}               — get one user (404 if missing)
  POST   /                        — create user (201; hashes plain password)
  PATCH  /{user_id}               — update role/display_name/is_active
  POST   /{user_id}/password-reset — reset a user's password (204)

Self-deactivation guard (design §6.2, R8):
  PATCH with is_active=False on the caller's own user_id raises HTTP 400.

No hard-delete endpoint (FR-USERS-4).
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import require_permission
from api.models.users import (
    PasswordResetRequest,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from database.connection import get_db
from database.models import AdminUser
from shared.security import hash_password

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# GET / — list users
# ---------------------------------------------------------------------------


@router.get("/", response_model=UserListResponse)
async def list_users(
    current_user: Annotated[AdminUser, Depends(require_permission("users:manage"))],
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> UserListResponse:
    """
    List all admin/stylist users, paginated.

    Permission: users:manage (admin only).
    Returns UserListResponse { items, total, limit, offset } — never exposes password_hash.
    """
    count_result = await session.execute(select(func.count(AdminUser.id)))
    total: int = count_result.scalar_one()

    list_result = await session.execute(
        select(AdminUser).order_by(AdminUser.username).limit(limit).offset(offset)
    )
    users = list_result.scalars().all()
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /{user_id} — get one user
# ---------------------------------------------------------------------------


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: Annotated[AdminUser, Depends(require_permission("users:manage"))],
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Get a single user by UUID.

    Returns 404 if the user does not exist.
    Permission: users:manage (admin only).
    """
    result = await session.execute(select(AdminUser).where(AdminUser.id == user_id))
    user: AdminUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# POST / — create user
# ---------------------------------------------------------------------------


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("users:manage"))],
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Create a new admin/stylist user.

    - Validates username uniqueness (409 if taken).
    - Hashes the plain-text password with bcrypt cost ≥ 12 (FR-USERS-2, SC-HASH-1).
    - Plain-text password is never stored or logged.
    - Returns 201 with the new UserResponse.

    Permission: users:manage (admin only).
    """
    # Uniqueness check
    existing = await session.execute(select(AdminUser).where(AdminUser.username == body.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{body.username}' is already taken",
        )

    new_user = AdminUser(
        id=uuid4(),
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
        is_active=True,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    logger.info("Admin user created: username=%s role=%s", new_user.username, new_user.role)
    return UserResponse.model_validate(new_user)


# ---------------------------------------------------------------------------
# PATCH /{user_id} — update user
# ---------------------------------------------------------------------------


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    body: UserUpdateRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("users:manage"))],
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Update a user's role, is_active, or display_name.

    - Only supplied fields are mutated (PATCH semantics).
    - Self-deactivation guard: raises 400 when caller tries to set their own is_active=False.
    - Does NOT touch password_hash; use /password-reset for that.
    - Returns 404 if the user does not exist.

    Permission: users:manage (admin only).
    """
    result = await session.execute(select(AdminUser).where(AdminUser.id == user_id))
    user: AdminUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Self-deactivation guard (design §6.2, R8)
    if body.is_active is False and user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate own account",
        )

    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.display_name is not None:
        user.display_name = body.display_name

    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# POST /{user_id}/password-reset — reset password
# ---------------------------------------------------------------------------


@router.post(
    "/{user_id}/password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def reset_password(
    user_id: UUID,
    body: PasswordResetRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("users:manage"))],
    session: AsyncSession = Depends(get_db),
) -> None:
    """
    Reset another user's password (admin-managed reset, not self-service).

    - Hashes the new plain-text password with bcrypt cost ≥ 12.
    - Returns 204 on success; 404 if the user does not exist.
    - Plain-text password is never stored or logged.

    Permission: users:manage (admin only).
    """
    result = await session.execute(select(AdminUser).where(AdminUser.id == user_id))
    user: AdminUser | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(body.new_password)
    await session.commit()

    logger.info("Password reset for user_id=%s by admin=%s", user_id, current_user.username)
