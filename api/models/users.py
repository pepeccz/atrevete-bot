"""
Pydantic schemas for User CRUD endpoints.

These are the request/response models for api/routes/users.py. They enforce
field validation, prevent password_hash exposure, and document the API contract.

FR-USERS-2: Passwords are hashed before persistence — plain text never stored.
NFR-2: password_hash is NEVER exposed in any response model.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    """Request body for POST /api/admin/users (create a new admin/stylist user)."""

    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8)
    role: str = Field(pattern="^(admin|stylist)$")
    display_name: str | None = Field(default=None)


class UserUpdateRequest(BaseModel):
    """
    Request body for PATCH /api/admin/users/{user_id}.

    All fields are optional — PATCH semantics (only supplied fields are mutated).
    """

    role: str | None = Field(default=None, pattern="^(admin|stylist)$")
    is_active: bool | None = None
    display_name: str | None = None


class UserResponse(BaseModel):
    """
    Response shape for a single admin/stylist user.

    Exposes: id, username, role, is_active, display_name, last_login_at,
             created_at, updated_at.

    password_hash is NEVER included (FR-USERS-3, NFR-2).
    """

    id: UUID
    username: str
    role: str
    is_active: bool
    display_name: str | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Paginated list of users."""

    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class PasswordResetRequest(BaseModel):
    """Request body for POST /api/admin/users/{user_id}/password-reset."""

    new_password: str = Field(min_length=8)
