"""
Integration tests for stylist calendar conflict handling.

This module tests the complete flow of stylist calendar conflict resolution:
- End-to-end API calls with conflict scenarios
- Database constraint verification
- Race condition simulation

These tests require a database connection and test the actual endpoints
with mocked authentication.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from api.main import app
from database.models import Stylist, ServiceCategory


# ============================================================================
# Test Fixtures and Setup
# ============================================================================


@pytest.fixture
def client():
    """Provide a TestClient for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Provide authentication headers for admin endpoints."""
    # This is a simplified auth - in reality would need valid JWT
    return {"Authorization": "Bearer test_token"}


@pytest.fixture
def mock_current_user():
    """Mock the get_current_user dependency."""
    with patch("api.routes.admin.get_current_user") as mock:
        mock.return_value = {"sub": "admin", "jti": str(uuid4()), "exp": 9999999999}
        yield mock


# ============================================================================
# Test Create Stylist Endpoint
# ============================================================================


class TestCreateStylistIntegration:
    """Integration tests for create stylist with calendar conflict handling."""

    @pytest.mark.asyncio
    async def test_create_stylist_with_free_calendar_succeeds(self, mock_current_user):
        """GIVEN free calendar, WHEN creating stylist, THEN returns 201."""
        from api.routes.admin import create_stylist, CreateStylistRequest

        with patch("api.routes.admin._check_calendar_conflict") as mock_check:
            mock_check.return_value = (False, [])

            with patch("api.routes.admin.get_async_session") as mock_session_factory:
                mock_session = AsyncMock()

                # Create a properly configured mock stylist
                mock_stylist = MagicMock(spec=Stylist)
                mock_stylist.id = uuid4()
                mock_stylist.name = "Test Stylist"
                mock_stylist.category = ServiceCategory.HAIRDRESSING
                mock_stylist.google_calendar_id = "free@calendar.com"
                mock_stylist.is_active = True
                mock_stylist.color = None
                mock_stylist.created_at = datetime.now(timezone.utc)
                mock_stylist.updated_at = datetime.now(timezone.utc)

                mock_session.add = MagicMock()
                mock_session.commit = AsyncMock()
                mock_session.refresh = AsyncMock()
                mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch("api.routes.admin.publish_cache_invalidation"):
                    request = CreateStylistRequest(
                        name="Test Stylist",
                        category="HAIRDRESSING",
                        google_calendar_id="free@calendar.com",
                        is_active=True,
                    )
                    mock_user = {"sub": "admin"}

                    response = await create_stylist(request, mock_user)

                    assert response["name"] == "Test Stylist"
                    assert response["google_calendar_id"] == "free@calendar.com"

    @pytest.mark.asyncio
    async def test_create_stylist_with_occupied_calendar_returns_409(self, mock_current_user):
        """GIVEN occupied calendar, WHEN creating stylist, THEN returns 409 with details."""
        from api.routes.admin import create_stylist, CreateStylistRequest

        with patch("api.routes.admin._check_calendar_conflict") as mock_check:
            mock_check.return_value = (True, ["Maria"])

            request = CreateStylistRequest(
                name="Test Stylist",
                category="HAIRDRESSING",
                google_calendar_id="maria@calendar.com",
                is_active=True,
            )
            mock_user = {"sub": "admin"}

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await create_stylist(request, mock_user)

            assert exc_info.value.status_code == 409
            assert "Maria" in exc_info.value.detail["message"]
            assert exc_info.value.detail["stylist_names"] == ["Maria"]


# ============================================================================
# Test Update Stylist Endpoint
# ============================================================================


class TestUpdateStylistIntegration:
    """Integration tests for update stylist with calendar conflict handling."""

    @pytest.mark.asyncio
    async def test_update_same_calendar_succeeds(self, mock_current_user):
        """GIVEN stylist updating with same calendar, WHEN updating, THEN succeeds."""
        from api.routes.admin import update_stylist, UpdateStylistRequest

        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.name = "Ana"
        mock_stylist.category = ServiceCategory.HAIRDRESSING
        mock_stylist.google_calendar_id = "ana@calendar.com"
        mock_stylist.is_active = True
        mock_stylist.color = None
        mock_stylist.created_at = datetime.now(timezone.utc)
        mock_stylist.updated_at = datetime.now(timezone.utc)

        with patch("api.routes.admin.get_async_session") as mock_session_factory:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_stylist
            mock_session.execute.return_value = mock_result
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("api.routes.admin._check_calendar_conflict") as mock_check:
                mock_check.return_value = (False, [])  # No conflict with same calendar

                with patch("api.routes.admin.publish_cache_invalidation"):
                    request = UpdateStylistRequest(
                        google_calendar_id="ana@calendar.com"  # Same calendar
                    )
                    mock_user = {"sub": "admin"}

                    response = await update_stylist(stylist_id, request, mock_user)

                    assert response["google_calendar_id"] == "ana@calendar.com"

    @pytest.mark.asyncio
    async def test_update_to_occupied_calendar_returns_409(self, mock_current_user):
        """GIVEN update to another's calendar, WHEN updating, THEN returns 409."""
        from api.routes.admin import update_stylist, UpdateStylistRequest

        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.name = "Ana"
        mock_stylist.category = ServiceCategory.HAIRDRESSING
        mock_stylist.google_calendar_id = "ana@calendar.com"
        mock_stylist.is_active = True

        with patch("api.routes.admin.get_async_session") as mock_session_factory:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_stylist
            mock_session.execute.return_value = mock_result
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("api.routes.admin._check_calendar_conflict") as mock_check:
                mock_check.return_value = (True, ["Maria"])

                request = UpdateStylistRequest(
                    google_calendar_id="maria@calendar.com"
                )
                mock_user = {"sub": "admin"}

                from fastapi import HTTPException
                with pytest.raises(HTTPException) as exc_info:
                    await update_stylist(stylist_id, request, mock_user)

                assert exc_info.value.status_code == 409
                assert "Maria" in exc_info.value.detail["message"]


# ============================================================================
# Test Assign Calendar Endpoint
# ============================================================================


class TestAssignCalendarIntegration:
    """Integration tests for assign calendar endpoint with conflict handling."""

    @pytest.mark.asyncio
    async def test_assign_free_calendar_succeeds(self, mock_current_user):
        """GIVEN free calendar, WHEN assigning to stylist, THEN succeeds."""
        from api.routes.admin import assign_stylist_calendar, AssignCalendarRequest

        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.google_calendar_id = "old@calendar.com"

        with patch("api.routes.admin.get_async_session") as mock_session_factory:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_stylist
            mock_session.execute.return_value = mock_result
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("api.routes.admin._check_calendar_conflict") as mock_check:
                mock_check.return_value = (False, [])

                with patch("api.routes.admin.publish_cache_invalidation"):
                    request = AssignCalendarRequest(calendar_id="new@calendar.com")
                    mock_user = {"sub": "admin"}

                    response = await assign_stylist_calendar(stylist_id, request, mock_user)

                    assert response["calendar_id"] == "new@calendar.com"
                    assert response["updated"] is True

    @pytest.mark.asyncio
    async def test_assign_occupied_calendar_returns_409(self, mock_current_user):
        """GIVEN occupied calendar, WHEN assigning, THEN returns 409."""
        from api.routes.admin import assign_stylist_calendar, AssignCalendarRequest

        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.google_calendar_id = "old@calendar.com"

        with patch("api.routes.admin.get_async_session") as mock_session_factory:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_stylist
            mock_session.execute.return_value = mock_result
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("api.routes.admin._check_calendar_conflict") as mock_check:
                mock_check.return_value = (True, ["Maria"])

                request = AssignCalendarRequest(calendar_id="maria@calendar.com")
                mock_user = {"sub": "admin"}

                from fastapi import HTTPException
                with pytest.raises(HTTPException) as exc_info:
                    await assign_stylist_calendar(stylist_id, request, mock_user)

                assert exc_info.value.status_code == 409
                assert "Maria" in exc_info.value.detail["message"]


# ============================================================================
# Test Race Condition Handling
# ============================================================================


class TestRaceConditionHandling:
    """Tests for race condition handling via IntegrityError remapping."""

    @pytest.mark.asyncio
    async def test_race_condition_on_create_remaps_to_409(self, mock_current_user):
        """GIVEN race condition on create, WHEN IntegrityError occurs, THEN returns 409."""
        from api.routes.admin import create_stylist, CreateStylistRequest

        with patch("api.routes.admin._check_calendar_conflict") as mock_check:
            # Pre-validation passes
            mock_check.return_value = (False, [])

            with patch("api.routes.admin.get_async_session") as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.add = MagicMock()

                # Simulate commit failure with unique constraint violation
                error = IntegrityError(
                    "duplicate key value violates unique constraint \"stylists_google_calendar_id_key\"",
                    params=None,
                    orig=Exception("stylists_google_calendar_id_key"),
                )
                mock_session.commit = AsyncMock(side_effect=error)
                mock_session.rollback = AsyncMock()
                mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch("api.routes.admin._is_unique_constraint_violation") as mock_is_unique:
                    mock_is_unique.return_value = True

                    # After rollback, re-check finds the conflict
                    with patch("api.routes.admin._check_calendar_conflict") as mock_recheck:
                        mock_recheck.return_value = (True, ["Maria"])

                        request = CreateStylistRequest(
                            name="Test Stylist",
                            category="HAIRDRESSING",
                            google_calendar_id="conflict@calendar.com",
                            is_active=True,
                        )
                        mock_user = {"sub": "admin"}

                        from fastapi import HTTPException
                        with pytest.raises(HTTPException) as exc_info:
                            await create_stylist(request, mock_user)

                        assert exc_info.value.status_code == 409
                        mock_session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_constraint_integrity_error_re_raised(self, mock_current_user):
        """GIVEN non-constraint IntegrityError, WHEN raised, THEN re-raises original."""
        from api.routes.admin import create_stylist, CreateStylistRequest

        with patch("api.routes.admin._check_calendar_conflict") as mock_check:
            mock_check.return_value = (False, [])

            with patch("api.routes.admin.get_async_session") as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.add = MagicMock()

                # Some other integrity error (not unique constraint)
                error = IntegrityError(
                    "foreign key constraint violation",
                    params=None,
                    orig=Exception("fk_constraint"),
                )
                mock_session.commit = AsyncMock(side_effect=error)
                mock_session.rollback = AsyncMock()
                mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch("api.routes.admin._is_unique_constraint_violation") as mock_is_unique:
                    mock_is_unique.return_value = False

                    request = CreateStylistRequest(
                        name="Test Stylist",
                        category="HAIRDRESSING",
                        google_calendar_id="valid@calendar.com",
                        is_active=True,
                    )
                    mock_user = {"sub": "admin"}

                    with pytest.raises(IntegrityError):
                        await create_stylist(request, mock_user)


# ============================================================================
# Test Database Constraint Verification
# ============================================================================


class TestDatabaseConstraintIntegrity:
    """Tests to verify the database schema maintains the unique constraint."""

    def test_unique_constraint_on_google_calendar_id(self):
        """Verify that the database schema has unique constraint on google_calendar_id."""
        from database.models import Stylist
        from sqlalchemy import inspect

        # Get the table
        table = Stylist.__table__

        # Check that google_calendar_id column has unique=True
        calendar_col = table.c.google_calendar_id
        assert calendar_col.unique is True, "google_calendar_id should have unique constraint"
        assert calendar_col.nullable is False, "google_calendar_id should not be nullable"
        assert calendar_col.index is True, "google_calendar_id should be indexed"

    def test_model_requires_calendar_id(self):
        """Verify Stylist model requires google_calendar_id."""
        from database.models import Stylist, ServiceCategory

        # The model should enforce non-null calendar_id at the application level too
        # This is validated through the Pydantic request schemas
        from api.routes.admin import CreateStylistRequest

        # Verify the request model requires google_calendar_id
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateStylistRequest(
                name="Test",
                google_calendar_id=""  # Empty should fail min_length
            )
