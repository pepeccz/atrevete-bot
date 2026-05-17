"""
Unit tests for Google Calendar CRUD — service layer + API endpoints.

Coverage (25 tests):

Service layer (10 tests — Phase 1):
  1. list_calendars returns extended fields (description, timeZone, primary)
  2. create_calendar — happy path
  3. create_calendar — Google API error raises GoogleCalendarError
  4. update_calendar — happy path (all fields)
  5. update_calendar — no-op (all params None → empty patch body)
  6. delete_calendar — happy path (returns None)
  7. delete_calendar — 403 → PrimaryCalendarError
  8. delete_calendar — 404 → idempotent (no error)
  9. delete_calendar — 500 → GoogleCalendarError
 10. delete_calendar — non-HttpError exception → GoogleCalendarError

API endpoints (15 tests — Phase 2):
POST /api/admin/google/calendars:
 11. success → 201 + CalendarResponse
 12. empty summary → 400
 13. no credentials (NotConfigured) → 401
 14. Google API failure → 502

PATCH /api/admin/google/calendars/{calendar_id}:
 15. success → 200 + CalendarResponse
 16. empty body (both None) → 400
 17. Google 404 → 404
 18. Google API failure → 502

DELETE /api/admin/google/calendars/{calendar_id}:
 19. success → 200
 20. stylist assigned → 409 with stylist names
 21. primary calendar (PrimaryCalendarError) → 403
 22. already deleted (idempotent via service 404 path) → 200
 23. Google API failure → 502
 24. Pydantic schemas — CreateCalendarRequest field defaults
 25. Pydantic schemas — UpdateCalendarRequest both-None is allowed at schema level

Test naming: test_<scenario_description>
Async tests use pytest-asyncio with asyncio_mode=auto (project-wide setting).

Note: Docker-only packages (google_auth_oauthlib, googleapiclient) are already
      stubbed by tests/conftest.py. HttpError stub is a real class that accepts
      `resp` and `content` constructor arguments.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.services.google_oauth_service as _oauth_module
from agent.services.google_oauth_service import (
    GoogleCalendarError,
    GoogleOAuthService,
    PrimaryCalendarError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    admin_jwt_secret: str = "test-secret-min-16ch",
    client_id: str = "test-client-id",
    client_secret: str = "test-client-secret",
    redirect_uri: str = "http://localhost/callback",
) -> MagicMock:
    s = MagicMock()
    s.ADMIN_JWT_SECRET = admin_jwt_secret
    s.GOOGLE_OAUTH_CLIENT_ID = client_id
    s.GOOGLE_OAUTH_CLIENT_SECRET = client_secret
    s.GOOGLE_OAUTH_REDIRECT_URI = redirect_uri
    s.google_oauth_configured = bool(client_id and client_secret)
    return s


def _make_http_error(status: int, reason: str = "Error") -> Exception:
    """Build a stub HttpError with a resp that has a .status attribute."""
    from googleapiclient.errors import HttpError  # type: ignore[import]

    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=b"")


# ===========================================================================
# Task 1.1 — list_calendars returns extended fields
# ===========================================================================


class TestListCalendarsExtendedFields:
    """list_calendars() must include description, timeZone, and primary."""

    async def test_list_calendars_returns_extended_fields(self):
        """
        list_calendars() must include description, timeZone, and primary
        in every returned dict alongside the existing id/summary/accessRole/
        backgroundColor fields.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        # Simulate calendarList().list() response with extended fields
        raw_item = {
            "id": "cal-123@group.calendar.google.com",
            "summary": "Estilista María",
            "accessRole": "owner",
            "backgroundColor": "#0F9D58",
            "description": "Calendario de la estilista María",
            "timeZone": "Europe/Madrid",
            "primary": False,
        }
        mock_service = MagicMock()
        mock_service.calendarList().list().execute.return_value = {"items": [raw_item]}

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            calendars = await service.list_calendars(session=AsyncMock())

        assert len(calendars) == 1
        cal = calendars[0]
        assert cal["id"] == "cal-123@group.calendar.google.com"
        assert cal["summary"] == "Estilista María"
        assert cal["description"] == "Calendario de la estilista María"
        assert cal["timeZone"] == "Europe/Madrid"
        assert cal["primary"] is False
        assert cal["accessRole"] == "owner"
        assert cal["backgroundColor"] == "#0F9D58"


# ===========================================================================
# Task 1.2 — create_calendar
# ===========================================================================


class TestCreateCalendar:
    """Tests for GoogleOAuthService.create_calendar()."""

    async def test_create_calendar_success(self):
        """
        create_calendar() must call calendars().insert() with the correct body
        and return a dict with id, summary, description, timeZone, primary=False.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        api_response = {
            "id": "new-cal@group.calendar.google.com",
            "summary": "Calendario de María",
            "description": "Un nuevo calendario",
            "timeZone": "Europe/Madrid",
        }
        mock_service = MagicMock()
        mock_service.calendars().insert().execute.return_value = api_response

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            result = await service.create_calendar(
                session=AsyncMock(),
                summary="Calendario de María",
                description="Un nuevo calendario",
                time_zone="Europe/Madrid",
            )

        assert result["id"] == "new-cal@group.calendar.google.com"
        assert result["summary"] == "Calendario de María"
        assert result["description"] == "Un nuevo calendario"
        assert result["timeZone"] == "Europe/Madrid"
        assert result["primary"] is False

        # Verify insert() was called with the right body
        insert_call_args = mock_service.calendars().insert.call_args
        assert insert_call_args is not None
        body_arg = insert_call_args.kwargs.get("body") or insert_call_args.args[0]
        assert body_arg["summary"] == "Calendario de María"

    async def test_create_calendar_api_error_raises_google_calendar_error(self):
        """
        When the Google API call raises any exception, create_calendar()
        must wrap it in a GoogleCalendarError.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        mock_service = MagicMock()
        mock_service.calendars().insert().execute.side_effect = RuntimeError(
            "API quota exceeded"
        )

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            with pytest.raises(GoogleCalendarError, match="Failed to create calendar"):
                await service.create_calendar(
                    session=AsyncMock(),
                    summary="Falla",
                )


# ===========================================================================
# Task 1.3 — update_calendar
# ===========================================================================


class TestUpdateCalendar:
    """Tests for GoogleOAuthService.update_calendar()."""

    async def test_update_calendar_success(self):
        """
        update_calendar() must call calendars().patch() with the correct calendarId
        and body, and return the updated calendar dict.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        calendar_id = "existing-cal@group.calendar.google.com"
        api_response = {
            "id": calendar_id,
            "summary": "Nuevo Nombre",
            "description": "Nueva descripción",
            "timeZone": "Europe/London",
            "primary": False,
        }
        mock_service = MagicMock()
        mock_service.calendars().patch().execute.return_value = api_response

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            result = await service.update_calendar(
                session=AsyncMock(),
                calendar_id=calendar_id,
                summary="Nuevo Nombre",
                description="Nueva descripción",
                time_zone="Europe/London",
            )

        assert result["id"] == calendar_id
        assert result["summary"] == "Nuevo Nombre"
        assert result["description"] == "Nueva descripción"
        assert result["timeZone"] == "Europe/London"
        assert result["primary"] is False

        # Verify patch() was called with correct calendarId
        patch_call_args = mock_service.calendars().patch.call_args
        assert patch_call_args is not None
        assert patch_call_args.kwargs.get("calendarId") == calendar_id

    async def test_update_calendar_noop_empty_body(self):
        """
        When all optional params are None, update_calendar() sends an empty
        body to the patch() call (no-op update). The method must still succeed
        and return the calendar dict from the API response.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        calendar_id = "existing-cal@group.calendar.google.com"
        api_response = {
            "id": calendar_id,
            "summary": "Unchanged Name",
            "description": "",
            "timeZone": "Europe/Madrid",
            "primary": False,
        }
        mock_service = MagicMock()
        mock_service.calendars().patch().execute.return_value = api_response

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            result = await service.update_calendar(
                session=AsyncMock(),
                calendar_id=calendar_id,
                # All optional fields are None → empty body
            )

        # Empty body means nothing was changed — but we still get the calendar back
        assert result["id"] == calendar_id
        assert result["summary"] == "Unchanged Name"

        # Verify patch() was called with empty body
        patch_call_args = mock_service.calendars().patch.call_args
        assert patch_call_args.kwargs.get("body") == {}


# ===========================================================================
# Task 1.4 — delete_calendar
# ===========================================================================


class TestDeleteCalendar:
    """Tests for GoogleOAuthService.delete_calendar()."""

    async def test_delete_calendar_success(self):
        """
        delete_calendar() must call calendars().delete() and return None on success.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        mock_service = MagicMock()
        mock_service.calendars().delete().execute.return_value = None

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            result = await service.delete_calendar(
                session=AsyncMock(),
                calendar_id="some-cal@group.calendar.google.com",
            )

        assert result is None

    async def test_delete_calendar_primary_raises_primary_calendar_error(self):
        """
        When Google returns HTTP 403, delete_calendar() must raise PrimaryCalendarError.
        This protects the user from accidentally deleting the primary calendar.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        mock_service = MagicMock()
        mock_service.calendars().delete().execute.side_effect = _make_http_error(403)

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            with pytest.raises(PrimaryCalendarError):
                await service.delete_calendar(
                    session=AsyncMock(),
                    calendar_id="primary@example.com",
                )

    async def test_delete_calendar_not_found_is_idempotent(self):
        """
        When Google returns HTTP 404, delete_calendar() must NOT raise and must
        return None (treating already-deleted as a success — idempotent delete).
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        mock_service = MagicMock()
        mock_service.calendars().delete().execute.side_effect = _make_http_error(404)

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            # Must not raise
            result = await service.delete_calendar(
                session=AsyncMock(),
                calendar_id="already-gone@group.calendar.google.com",
            )

        assert result is None

    async def test_delete_calendar_server_error_raises_google_calendar_error(self):
        """
        When Google returns HTTP 500, delete_calendar() must raise GoogleCalendarError
        (not PrimaryCalendarError — that is exclusively for 403).
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        mock_service = MagicMock()
        mock_service.calendars().delete().execute.side_effect = _make_http_error(
            500, "Internal Server Error"
        )

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            with pytest.raises(GoogleCalendarError) as exc_info:
                await service.delete_calendar(
                    session=AsyncMock(),
                    calendar_id="some-cal@group.calendar.google.com",
                )

        # Must NOT be the more specific subclass
        assert not isinstance(exc_info.value, PrimaryCalendarError)

    async def test_delete_calendar_non_http_error_raises_google_calendar_error(self):
        """
        When a non-HttpError exception is raised (e.g. network failure),
        delete_calendar() must also wrap it in a GoogleCalendarError.
        """
        fake_settings = _make_settings()
        mock_creds = MagicMock(name="Credentials")

        mock_service = MagicMock()
        mock_service.calendars().delete().execute.side_effect = ConnectionError(
            "Network unreachable"
        )

        mock_build = MagicMock(return_value=mock_service)

        with (
            patch.object(_oauth_module, "get_settings", return_value=fake_settings),
            patch.object(_oauth_module, "build", mock_build),
        ):
            service = GoogleOAuthService()
            service.get_credentials = AsyncMock(return_value=mock_creds)
            with pytest.raises(GoogleCalendarError, match="Failed to delete calendar"):
                await service.delete_calendar(
                    session=AsyncMock(),
                    calendar_id="some-cal@group.calendar.google.com",
                )


# ===========================================================================
# Phase 2 — API Endpoint Tests
# ===========================================================================
#
# Strategy: import the endpoint functions directly and call them, injecting
# mocked dependencies (current_user, session, service).  This avoids spinning
# up a full FastAPI TestClient / ASGI stack, which requires a running DB and
# Redis — consistent with the rest of the unit test suite in this project.
#
# Each endpoint function is an async def; we await it directly after patching
# _oauth_service on the google_oauth module and patching get_async_session so
# it returns a no-op async context manager.
# ===========================================================================


from fastapi import HTTPException  # type: ignore[import]

import api.routes.google_oauth as _route_module
from agent.services.google_oauth_service import (
    GoogleOAuthNotConfiguredError,
)
from api.routes.google_oauth import (
    CalendarResponse,
    CreateCalendarRequest,
    UpdateCalendarRequest,
    create_google_calendar,
    delete_google_calendar,
    update_google_calendar,
)

# ---------------------------------------------------------------------------
# Helpers for API tests
# ---------------------------------------------------------------------------


def _fake_user() -> dict:
    """Minimal JWT payload — just needs 'sub'."""
    return {"sub": "admin-test-user"}


def _make_async_session_ctx(session: AsyncMock) -> MagicMock:
    """Return an async context manager that yields the given session mock."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ===========================================================================
# Task 2.3 — POST /calendars
# ===========================================================================


class TestCreateCalendarEndpoint:
    """Tests for POST /api/admin/google/calendars."""

    async def test_post_calendars_success_returns_201_response(self):
        """
        Happy path: service.create_calendar() succeeds → endpoint returns
        CalendarResponse with the data from the service.
        """
        fake_calendar = {
            "id": "new-cal@group.calendar.google.com",
            "summary": "Calendario de María",
            "description": "Descripción opcional",
            "timeZone": "Europe/Madrid",
            "primary": False,
        }
        mock_service = AsyncMock()
        mock_service.create_calendar = AsyncMock(return_value=fake_calendar)

        mock_session = AsyncMock()
        mock_ctx = _make_async_session_ctx(mock_session)

        body = CreateCalendarRequest(
            summary="Calendario de María",
            description="Descripción opcional",
            timeZone="Europe/Madrid",
        )

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            result = await create_google_calendar(body=body, current_user=_fake_user())

        assert isinstance(result, CalendarResponse)
        assert result.id == "new-cal@group.calendar.google.com"
        assert result.summary == "Calendario de María"
        assert result.description == "Descripción opcional"
        assert result.primary is False

    async def test_post_calendars_empty_summary_raises_400(self):
        """
        When the request body has a whitespace-only summary, the endpoint
        must raise HTTPException 400.  (Pydantic min_length=1 catches truly
        empty strings; this test exercises the .strip() guard for spaces.)
        """
        body = CreateCalendarRequest(summary="   ")  # passes Pydantic, caught by endpoint

        with pytest.raises(HTTPException) as exc_info:
            await create_google_calendar(body=body, current_user=_fake_user())

        assert exc_info.value.status_code == 400

    async def test_post_calendars_no_credentials_raises_401(self):
        """
        When the service raises GoogleOAuthNotConfiguredError (no account connected),
        the endpoint must return 401 Unauthorized.
        """
        mock_service = AsyncMock()
        mock_service.create_calendar = AsyncMock(
            side_effect=GoogleOAuthNotConfiguredError("no credentials")
        )

        mock_session = AsyncMock()
        mock_ctx = _make_async_session_ctx(mock_session)

        body = CreateCalendarRequest(summary="Nuevo Cal")

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await create_google_calendar(body=body, current_user=_fake_user())

        assert exc_info.value.status_code == 401

    async def test_post_calendars_google_api_failure_raises_502(self):
        """
        When the service raises GoogleCalendarError (Google API failure),
        the endpoint must return 502 Bad Gateway.
        """
        mock_service = AsyncMock()
        mock_service.create_calendar = AsyncMock(
            side_effect=GoogleCalendarError("calendar API unavailable")
        )

        mock_session = AsyncMock()
        mock_ctx = _make_async_session_ctx(mock_session)

        body = CreateCalendarRequest(summary="Nuevo Cal")

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await create_google_calendar(body=body, current_user=_fake_user())

        assert exc_info.value.status_code == 502


# ===========================================================================
# Task 2.4 — PATCH /calendars/{calendar_id}
# ===========================================================================


class TestUpdateCalendarEndpoint:
    """Tests for PATCH /api/admin/google/calendars/{calendar_id}."""

    async def test_patch_calendars_success_returns_200_response(self):
        """
        Happy path: service.update_calendar() succeeds → endpoint returns
        CalendarResponse with the updated calendar data.
        """
        cal_id = "existing-cal@group.calendar.google.com"
        fake_calendar = {
            "id": cal_id,
            "summary": "Nuevo Nombre",
            "description": "Nueva descripción",
            "timeZone": "Europe/Madrid",
            "primary": False,
        }
        mock_service = AsyncMock()
        mock_service.update_calendar = AsyncMock(return_value=fake_calendar)

        mock_session = AsyncMock()
        mock_ctx = _make_async_session_ctx(mock_session)

        body = UpdateCalendarRequest(summary="Nuevo Nombre", description="Nueva descripción")

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            result = await update_google_calendar(
                calendar_id=cal_id, body=body, current_user=_fake_user()
            )

        assert isinstance(result, CalendarResponse)
        assert result.id == cal_id
        assert result.summary == "Nuevo Nombre"

    async def test_patch_calendars_empty_body_raises_400(self):
        """
        When both summary and description are None, the endpoint must raise
        HTTPException 400 before calling the service.
        """
        body = UpdateCalendarRequest()  # Both None by default

        with pytest.raises(HTTPException) as exc_info:
            await update_google_calendar(
                calendar_id="some-cal@group.calendar.google.com",
                body=body,
                current_user=_fake_user(),
            )

        assert exc_info.value.status_code == 400

    async def test_patch_calendars_not_found_raises_404(self):
        """
        When the service raises GoogleCalendarError containing '404' in the
        message (wrapped HttpError), the endpoint must return 404 Not Found.
        """
        mock_service = AsyncMock()
        mock_service.update_calendar = AsyncMock(
            side_effect=GoogleCalendarError("Failed to update calendar '404' not found")
        )

        mock_session = AsyncMock()
        mock_ctx = _make_async_session_ctx(mock_session)

        body = UpdateCalendarRequest(summary="Nueva Nombre")

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_google_calendar(
                    calendar_id="ghost-cal@group.calendar.google.com",
                    body=body,
                    current_user=_fake_user(),
                )

        assert exc_info.value.status_code == 404

    async def test_patch_calendars_google_api_failure_raises_502(self):
        """
        When the service raises a generic GoogleCalendarError (no 404 in message),
        the endpoint must return 502 Bad Gateway.
        """
        mock_service = AsyncMock()
        mock_service.update_calendar = AsyncMock(
            side_effect=GoogleCalendarError("Internal server error from Google API")
        )

        mock_session = AsyncMock()
        mock_ctx = _make_async_session_ctx(mock_session)

        body = UpdateCalendarRequest(summary="Nombre")

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_google_calendar(
                    calendar_id="some-cal@group.calendar.google.com",
                    body=body,
                    current_user=_fake_user(),
                )

        assert exc_info.value.status_code == 502


# ===========================================================================
# Task 2.5 — DELETE /calendars/{calendar_id}
# ===========================================================================


class TestDeleteCalendarEndpoint:
    """Tests for DELETE /api/admin/google/calendars/{calendar_id}."""

    async def test_delete_calendars_success_returns_200(self):
        """
        Happy path: no stylists assigned, service.delete_calendar() succeeds →
        endpoint returns 200 with {deleted: True, calendar_id: ...}.
        """
        cal_id = "deletable-cal@group.calendar.google.com"
        mock_service = AsyncMock()
        mock_service.delete_calendar = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        # DB query returns no stylists
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = _make_async_session_ctx(mock_session)

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            result = await delete_google_calendar(
                calendar_id=cal_id, current_user=_fake_user()
            )

        assert result["deleted"] is True
        assert result["calendar_id"] == cal_id

    async def test_delete_calendars_stylist_assigned_raises_409(self):
        """
        When a stylist has google_calendar_id matching the calendar being deleted,
        the endpoint must raise 409 Conflict and include the stylist name(s) in
        the error detail.
        """
        cal_id = "stylist-cal@group.calendar.google.com"

        # Build a mock Stylist ORM object
        mock_stylist = MagicMock()
        mock_stylist.name = "María García"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = _make_async_session_ctx(mock_session)

        with patch.object(_route_module, "get_async_session", return_value=mock_ctx):
            with pytest.raises(HTTPException) as exc_info:
                await delete_google_calendar(
                    calendar_id=cal_id, current_user=_fake_user()
                )

        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert "stylist_names" in detail
        assert "María García" in detail["stylist_names"]

    async def test_delete_calendars_primary_raises_403(self):
        """
        When service.delete_calendar() raises PrimaryCalendarError (Google 403),
        the endpoint must return 403 Forbidden with an informative Spanish message.
        """
        cal_id = "primary@gmail.com"
        mock_service = AsyncMock()
        mock_service.delete_calendar = AsyncMock(side_effect=PrimaryCalendarError("primary"))

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = _make_async_session_ctx(mock_session)

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_google_calendar(
                    calendar_id=cal_id, current_user=_fake_user()
                )

        assert exc_info.value.status_code == 403
        assert "principal" in exc_info.value.detail

    async def test_delete_calendars_already_deleted_is_idempotent_200(self):
        """
        When Google returns 404 (already deleted), delete_calendar() in the service
        swallows the error and returns None.  The endpoint must therefore also
        return 200 — idempotent delete semantics.
        """
        cal_id = "already-gone-cal@group.calendar.google.com"
        mock_service = AsyncMock()
        # Service treats 404 as idempotent — returns None without raising
        mock_service.delete_calendar = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = _make_async_session_ctx(mock_session)

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            result = await delete_google_calendar(
                calendar_id=cal_id, current_user=_fake_user()
            )

        assert result["deleted"] is True

    async def test_delete_calendars_google_api_failure_raises_502(self):
        """
        When service.delete_calendar() raises a generic GoogleCalendarError
        (e.g. 500 from Google), the endpoint must return 502 Bad Gateway.
        """
        cal_id = "error-cal@group.calendar.google.com"
        mock_service = AsyncMock()
        mock_service.delete_calendar = AsyncMock(
            side_effect=GoogleCalendarError("Google returned 500")
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = _make_async_session_ctx(mock_session)

        with (
            patch.object(_route_module, "_oauth_service", mock_service),
            patch.object(_route_module, "get_async_session", return_value=mock_ctx),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await delete_google_calendar(
                    calendar_id=cal_id, current_user=_fake_user()
                )

        assert exc_info.value.status_code == 502


# ===========================================================================
# Task 2.1 — Pydantic Schema Validation
# ===========================================================================


class TestCalendarSchemas:
    """Validate Pydantic schema behaviour for calendar CRUD requests."""

    def test_create_calendar_request_defaults(self):
        """
        CreateCalendarRequest: description defaults to "" and timeZone defaults
        to "Europe/Madrid" when not provided.
        """
        req = CreateCalendarRequest(summary="Mi Calendario")
        assert req.summary == "Mi Calendario"
        assert req.description == ""
        assert req.timeZone == "Europe/Madrid"

    def test_update_calendar_request_both_none_at_schema_level(self):
        """
        UpdateCalendarRequest allows both fields to be None at the schema level
        (the 400 guard is in the endpoint, not in Pydantic).  This ensures the
        schema does NOT raise a validation error for an empty body.
        """
        req = UpdateCalendarRequest()
        assert req.summary is None
        assert req.description is None
