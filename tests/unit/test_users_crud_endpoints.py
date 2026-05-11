"""
TDD tests for api/routes/users.py — User CRUD endpoints.

Coverage:
- GET /api/admin/users → list users (paginated)
- GET /api/admin/users/{user_id} → get one user (404 if missing)
- POST /api/admin/users → create user (201, hashed pw, uniqueness)
- PATCH /api/admin/users/{user_id} → update role/is_active/display_name
- POST /api/admin/users/{user_id}/password-reset → reset password (204)
- Self-deactivation guard: PATCH with is_active=False on own user → 400
- Stylist → 403 on all endpoints (FR-USERS-5, SC-USERS-4)
- UserResponse shape: 8 fields present, password_hash NEVER exposed
- 404 on non-existent user_id for GET, PATCH, password-reset
- 422 on validation errors (bad body)

Strict TDD — RED phase written BEFORE implementation files exist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.models import AdminUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WIRED = False  # guard so we only wire the router once per process


def _make_admin_user(
    username: str = "admin",
    role: str = "admin",
    is_active: bool = True,
    user_id: UUID | None = None,
    display_name: str | None = None,
) -> AdminUser:
    user = MagicMock(spec=AdminUser)
    user.id = user_id or uuid4()
    user.username = username
    user.role = role
    user.is_active = is_active
    user.display_name = display_name
    user.last_login_at = None
    user.password_hash = "$2b$12$fakehash"
    user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    user.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return user


def _make_test_app(current_user: AdminUser) -> FastAPI:
    """
    Build a minimal FastAPI app with the users router wired and auth mocked.

    Auth is bypassed: all Depends(require_permission("users:manage")) calls
    immediately return `current_user` without touching JWT/DB.

    We override get_current_user at the dependency level so require_permission
    (which wraps get_current_user) sees our mock user directly.
    """
    from api.dependencies.auth import get_current_user
    from api.routes import users as users_module

    test_app = FastAPI()

    # Override get_current_user so all auth/permission checks receive our user
    test_app.dependency_overrides[get_current_user] = lambda: current_user

    test_app.include_router(users_module.router, prefix="/api/admin/users", tags=["users"])
    return test_app


# ---------------------------------------------------------------------------
# UserResponse shape tests (T2.9 / FIX-W2)
# ---------------------------------------------------------------------------


def test_user_response_has_all_required_fields():
    """UserResponse must expose exactly 8 fields; password_hash must NOT be present."""
    from api.models.users import UserResponse

    uid = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    response = UserResponse(
        id=uid,
        username="testuser",
        role="admin",
        is_active=True,
        display_name="Test User",
        last_login_at=now,
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump()
    required_fields = {
        "id",
        "username",
        "role",
        "is_active",
        "display_name",
        "last_login_at",
        "created_at",
        "updated_at",
    }
    assert required_fields.issubset(data.keys()), f"Missing fields: {required_fields - data.keys()}"
    assert "password_hash" not in data, "password_hash MUST NOT be in UserResponse"


def test_user_response_field_types():
    """UserResponse fields must have correct types."""
    from api.models.users import UserResponse

    uid = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    response = UserResponse(
        id=uid,
        username="testuser",
        role="admin",
        is_active=True,
        display_name=None,
        last_login_at=None,
        created_at=now,
        updated_at=now,
    )

    assert isinstance(response.id, UUID)
    assert isinstance(response.username, str)
    assert isinstance(response.role, str)
    assert isinstance(response.is_active, bool)
    assert response.display_name is None
    assert response.last_login_at is None
    assert isinstance(response.created_at, datetime)
    assert isinstance(response.updated_at, datetime)


def test_user_create_request_validates_username_length():
    """UserCreateRequest must reject usernames shorter than 3 chars."""
    from pydantic import ValidationError

    from api.models.users import UserCreateRequest

    with pytest.raises(ValidationError):
        UserCreateRequest(username="ab", password="validpass1", role="admin")


def test_user_create_request_validates_password_length():
    """UserCreateRequest must reject passwords shorter than 8 chars."""
    from pydantic import ValidationError

    from api.models.users import UserCreateRequest

    with pytest.raises(ValidationError):
        UserCreateRequest(username="validuser", password="short", role="admin")


def test_user_create_request_valid():
    """UserCreateRequest must accept valid payload."""
    from api.models.users import UserCreateRequest

    req = UserCreateRequest(
        username="newuser",
        password="securepassword",
        role="stylist",
        display_name="New User",
    )
    assert req.username == "newuser"
    assert req.role == "stylist"


def test_user_update_request_all_optional():
    """UserUpdateRequest must accept empty body (all fields optional — PATCH semantics)."""
    from api.models.users import UserUpdateRequest

    req = UserUpdateRequest()
    assert req.role is None
    assert req.is_active is None
    assert req.display_name is None


def test_password_reset_request_validates_min_length():
    """PasswordResetRequest must reject passwords shorter than 8 chars."""
    from pydantic import ValidationError

    from api.models.users import PasswordResetRequest

    with pytest.raises(ValidationError):
        PasswordResetRequest(new_password="short")


# ---------------------------------------------------------------------------
# GET /api/admin/users — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_returns_list():
    """GET /api/admin/users must return a list of UserResponse objects."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    u1 = _make_admin_user(username="alice", role="admin")
    u2 = _make_admin_user(username="bob", role="stylist")

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [u1, u2]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.users.get_async_session", return_value=mock_session):
        from database.connection import get_async_session

        app.dependency_overrides[get_async_session] = lambda: mock_session

        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/api/admin/users")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_list_users_pagination_params():
    """GET /api/admin/users must accept limit and offset query params."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/api/admin/users?limit=10&offset=5")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/admin/users/{user_id} — get one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_returns_user_response():
    """GET /api/admin/users/{id} must return 200 with UserResponse."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    target_id = uuid4()
    target_user = _make_admin_user(username="target", user_id=target_id)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = target_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.get(f"/api/admin/users/{target_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "target"
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_get_user_returns_404_if_not_found():
    """GET /api/admin/users/{id} must return 404 when user doesn't exist."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    missing_id = uuid4()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.get(f"/api/admin/users/{missing_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/admin/users — create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_returns_201():
    """POST /api/admin/users must return 201 with the new UserResponse."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    new_user_id = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)

    mock_session = AsyncMock()
    # username-uniqueness check returns None (username not taken)
    unique_result = MagicMock()
    unique_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=unique_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    # On refresh, populate the fields that model_validate needs
    def _populate_on_refresh(user_obj: AdminUser) -> None:
        user_obj.id = new_user_id
        user_obj.created_at = now
        user_obj.updated_at = now
        user_obj.last_login_at = None
        user_obj.is_active = True
        user_obj.display_name = "New User"
        user_obj.username = "newuser"
        user_obj.role = "stylist"

    mock_session.refresh = AsyncMock(side_effect=_populate_on_refresh)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    payload = {
        "username": "newuser",
        "password": "securepassword",
        "role": "stylist",
        "display_name": "New User",
    }

    with patch("api.routes.users.hash_password", return_value="$2b$12$hashedfake"):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post("/api/admin/users", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "newuser"
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_create_user_conflicts_on_duplicate_username():
    """POST /api/admin/users must return 409 when username is already taken."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    existing_user = _make_admin_user(username="existinguser")

    mock_session = AsyncMock()
    # username-uniqueness check returns an existing user
    unique_result = MagicMock()
    unique_result.scalar_one_or_none.return_value = existing_user
    mock_session.execute = AsyncMock(return_value=unique_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    payload = {
        "username": "existinguser",
        "password": "securepassword",
        "role": "admin",
    }

    client = TestClient(app, raise_server_exceptions=True)
    response = client.post("/api/admin/users", json=payload)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_user_invalid_body_returns_422():
    """POST /api/admin/users with missing required fields must return 422."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    from database.connection import get_async_session

    mock_session = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.post("/api/admin/users", json={"username": "x"})  # missing password + role
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/admin/users/{user_id} — update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_user_updates_role():
    """PATCH /api/admin/users/{id} must update role and return updated UserResponse."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    target_id = uuid4()
    target_user = _make_admin_user(username="target", role="stylist", user_id=target_id)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = target_user
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.patch(f"/api/admin/users/{target_id}", json={"role": "admin"})
    assert response.status_code == 200
    assert "password_hash" not in response.json()


@pytest.mark.asyncio
async def test_patch_user_returns_404_if_not_found():
    """PATCH /api/admin/users/{id} must return 404 when user doesn't exist."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    missing_id = uuid4()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.patch(f"/api/admin/users/{missing_id}", json={"role": "admin"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_self_deactivation_guard_returns_400():
    """
    PATCH /api/admin/users/{id} with is_active=False on own user must return 400.
    Self-deactivation guard (design §6.2, R8).
    """
    admin_id = uuid4()
    admin_user = _make_admin_user(user_id=admin_id)
    app = _make_test_app(admin_user)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = admin_user
    mock_session.execute = AsyncMock(return_value=mock_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.patch(f"/api/admin/users/{admin_id}", json={"is_active": False})
    assert response.status_code == 400
    assert "deactivate" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_self_deactivation_guard_does_not_trigger_for_other_user():
    """
    PATCH with is_active=False on a DIFFERENT user must NOT trigger the self-deactivation guard.
    """
    admin_id = uuid4()
    target_id = uuid4()  # different ID
    admin_user = _make_admin_user(user_id=admin_id)
    app = _make_test_app(admin_user)

    target_user = _make_admin_user(username="other", user_id=target_id)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = target_user
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.patch(f"/api/admin/users/{target_id}", json={"is_active": False})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/admin/users/{user_id}/password-reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_password_reset_returns_204():
    """POST /api/admin/users/{id}/password-reset must return 204 on success."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    target_id = uuid4()
    target_user = _make_admin_user(username="target", user_id=target_id)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = target_user
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    with patch("api.routes.users.hash_password", return_value="$2b$12$newhashedfake"):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post(
            f"/api/admin/users/{target_id}/password-reset",
            json={"new_password": "newsecurepassword"},
        )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_password_reset_returns_404_if_user_not_found():
    """POST /api/admin/users/{id}/password-reset must return 404 when user doesn't exist."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    missing_id = uuid4()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    from database.connection import get_async_session

    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.post(
        f"/api/admin/users/{missing_id}/password-reset",
        json={"new_password": "newsecurepassword"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_password_reset_invalid_body_returns_422():
    """POST password-reset with password too short must return 422."""
    admin_user = _make_admin_user()
    app = _make_test_app(admin_user)

    target_id = uuid4()

    from database.connection import get_async_session

    mock_session = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_session

    client = TestClient(app, raise_server_exceptions=True)
    response = client.post(
        f"/api/admin/users/{target_id}/password-reset",
        json={"new_password": "short"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Stylist → 403 on all endpoints (FR-USERS-5, SC-USERS-4)
# ---------------------------------------------------------------------------


def test_stylist_gets_403_on_list():
    """
    Stylist role hitting GET /api/admin/users must receive 403 (SC-USERS-4).

    We override get_current_user to return a stylist user so that
    require_permission("users:manage") evaluates the real permission check
    and raises 403 for the stylist role.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.dependencies.auth import get_current_user
    from api.routes import users as users_module

    stylist_user = _make_admin_user(role="stylist")

    test_app = FastAPI()

    # Override get_current_user so require_permission sees the stylist user
    test_app.dependency_overrides[get_current_user] = lambda: stylist_user
    test_app.include_router(users_module.router, prefix="/api/admin/users", tags=["users"])

    client = TestClient(test_app, raise_server_exceptions=True)
    response = client.get("/api/admin/users")
    assert response.status_code == 403
