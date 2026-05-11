"""
Unit tests for /auth/me UserResponse shape (FR-AUTH-7).

Asserts that the UserResponse Pydantic model in api/routes/admin.py
exposes id, username, role, display_name — and NEVER password_hash.

FIX-W2: Fixes warning from PR-2a verify report where UserResponse only
had {username, role}.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from database.models import AdminUser


def _make_admin_user(
    username: str = "admin",
    role: str = "admin",
    display_name: str | None = "Admin User",
) -> AdminUser:
    user = MagicMock(spec=AdminUser)
    user.id = uuid4()
    user.username = username
    user.role = role
    user.is_active = True
    user.display_name = display_name
    user.last_login_at = None
    user.password_hash = "$2b$12$fakehash"
    return user


def test_user_response_includes_id_and_display_name():
    """
    UserResponse in admin.py must include id, username, role, display_name.
    FR-AUTH-7: GET /api/admin/auth/me MUST return {id, username, role, display_name}.
    """
    from api.routes.admin import UserResponse

    uid = uuid4()
    response = UserResponse(
        id=str(uid),
        username="testadmin",
        role="admin",
        display_name="Test Admin",
    )
    assert response.id == str(uid)
    assert response.username == "testadmin"
    assert response.role == "admin"
    assert response.display_name == "Test Admin"


def test_user_response_does_not_include_password_hash():
    """UserResponse in admin.py must NOT expose password_hash (NFR-2)."""
    from api.routes.admin import UserResponse

    data = UserResponse(
        id=str(uuid4()),
        username="testadmin",
        role="admin",
        display_name=None,
    ).model_dump()

    assert "password_hash" not in data


def test_user_response_display_name_can_be_none():
    """UserResponse must accept display_name=None (optional field)."""
    from api.routes.admin import UserResponse

    response = UserResponse(
        id=str(uuid4()),
        username="minimal",
        role="stylist",
        display_name=None,
    )
    assert response.display_name is None


@pytest.mark.asyncio
async def test_get_me_endpoint_returns_all_four_fields():
    """
    GET /auth/me endpoint must return {id, username, role, display_name}.
    Functional test calling the endpoint directly with mocked auth.
    """
    from api.routes.admin import get_me

    user_id = uuid4()
    mock_user = _make_admin_user(
        username="pepe",
        role="admin",
        display_name="Pepe Admin",
    )
    mock_user.id = user_id

    response = await get_me(current_user=mock_user)
    data = response.model_dump()

    assert data["id"] == str(user_id)
    assert data["username"] == "pepe"
    assert data["role"] == "admin"
    assert data["display_name"] == "Pepe Admin"
    assert "password_hash" not in data
