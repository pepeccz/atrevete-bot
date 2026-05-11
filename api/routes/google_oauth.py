"""
Google OAuth2 Admin Endpoints

Provides REST endpoints for connecting the salon's Google account to the
admin panel, enabling OAuth2-based Google Calendar integration.

Endpoints:
    GET    /api/admin/google/status                       — connection status
    GET    /api/admin/google/auth-url                     — generate OAuth2 URL + CSRF state
    GET    /api/admin/google/callback                     — exchange code for tokens (browser redirect)
    GET    /api/admin/google/calendars                    — list accessible calendars
    POST   /api/admin/google/calendars                    — create a new secondary calendar
    PATCH  /api/admin/google/calendars/{calendar_id}      — update calendar name/description
    DELETE /api/admin/google/calendars/{calendar_id}      — delete calendar (safety check: no stylists)
    DELETE /api/admin/google/disconnect                   — remove tokens from DB

All endpoints (except /callback) are protected by the same JWT auth used by
the existing admin routes.  The /callback endpoint is intentionally public
because it receives the browser redirect from Google — the CSRF state stored in
Redis is the security mechanism instead.
"""

import json
import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from agent.services.google_oauth_service import (
    GoogleOAuthCSRFError,
    GoogleOAuthError,
    GoogleOAuthNotConfiguredError,
    GoogleOAuthService,
    GoogleOAuthTokenRevokedError,
    PrimaryCalendarError,
)

# Re-use the auth dependency from admin router to keep the same auth mechanism.
# Import it lazily-ish at module level (same file pattern as admin.py does for other imports).
from api.dependencies.auth import require_permission
from database.connection import get_async_session
from database.models import AdminUser, Stylist
from shared.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/google", tags=["google-oauth"])

# Module-level singleton — GoogleOAuthService is stateless (all state in DB/Redis)
_oauth_service = GoogleOAuthService()

# Redis key prefix for CSRF state tokens
_CSRF_KEY_PREFIX = "google_oauth_state:"
# CSRF state TTL: 10 minutes
_CSRF_TTL_SECONDS = 600


# =============================================================================
# Pydantic Schemas — Calendar CRUD
# =============================================================================


class CreateCalendarRequest(BaseModel):
    """Request body for POST /calendars."""

    summary: str = Field(
        ..., min_length=1, max_length=200, description="Display name of the calendar"
    )
    description: str = Field(default="", description="Optional calendar description")
    timeZone: str = Field(default="Europe/Madrid", description="IANA time zone string")


class UpdateCalendarRequest(BaseModel):
    """Request body for PATCH /calendars/{calendar_id}. At least one field must be provided."""

    summary: str | None = Field(default=None, max_length=200, description="New display name")
    description: str | None = Field(default=None, description="New description")


class CalendarResponse(BaseModel):
    """Response schema for a Google Calendar resource."""

    id: str
    summary: str
    description: str
    timeZone: str
    primary: bool
    accessRole: str = ""


# =============================================================================
# Helpers
# =============================================================================


async def _store_csrf_state(state: str, code_verifier: str) -> None:
    """Store a CSRF state token and PKCE code_verifier in Redis with a 10-minute TTL."""
    from shared.redis_client import get_redis_client

    redis = get_redis_client()
    value = json.dumps({"valid": True, "code_verifier": code_verifier})
    await redis.setex(f"{_CSRF_KEY_PREFIX}{state}", _CSRF_TTL_SECONDS, value)
    logger.debug("Stored CSRF state + code_verifier in Redis (key=%s...)", state[:8])


async def _consume_csrf_state(state: str) -> tuple[bool, str | None]:
    """
    Validate and consume a CSRF state token from Redis (one-time use).

    Returns:
        Tuple of (is_valid, code_verifier).
        - is_valid: True if the state was valid and has been consumed.
        - code_verifier: The PKCE code verifier, or None if not found/expired.
    """
    from shared.redis_client import get_redis_client

    redis = get_redis_client()
    key = f"{_CSRF_KEY_PREFIX}{state}"
    value = await redis.get(key)
    if value is None:
        return False, None
    await redis.delete(key)
    try:
        data = json.loads(value)
        return True, data.get("code_verifier")
    except (json.JSONDecodeError, TypeError):
        return True, None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/status")
async def google_connection_status(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict[str, Any]:
    """
    Return the current Google OAuth2 connection status.

    Response:
        connected (bool): Whether an active OAuth2 credential exists.
        email (str | None): Connected Google account email.
        connected_at (str | None): ISO 8601 timestamp when connected.
        token_healthy (bool): False if tokens are expired or revoked.
        scopes (list[str]): Granted OAuth2 scopes.
    """
    async with get_async_session() as session:
        return await _oauth_service.get_status(session)


@router.get("/auth-url")
async def generate_auth_url(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict[str, str]:
    """
    Generate a Google OAuth2 authorization URL.

    The returned ``state`` token MUST be stored by the frontend (e.g., in
    sessionStorage) and compared against the state returned by the callback.
    The server also stores the state in Redis for its own CSRF validation.

    Response:
        url (str): Google OAuth2 authorization URL to redirect the user to.
        state (str): CSRF state token — store in frontend sessionStorage.
    """
    settings = get_settings()
    if not settings.google_oauth_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Google OAuth2 is not configured. "
                "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in environment."
            ),
        )

    # Generate a cryptographically random state token
    state = secrets.token_urlsafe(32)
    auth_url, state, code_verifier = _oauth_service.generate_auth_url(state=state)

    # Persist state + code_verifier in Redis for server-side CSRF validation
    await _store_csrf_state(state, code_verifier)

    logger.info("Generated OAuth2 auth URL (state=%s...)", state[:8])
    return {"url": auth_url, "state": state}


@router.get("/callback")
async def google_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """
    Handle Google OAuth2 redirect callback.

    This endpoint is intentionally NOT JWT-protected because the browser
    redirects here directly from Google.  CSRF protection is provided by the
    ``state`` token validated against Redis.

    On success:  redirects to ADMIN_PANEL_URL/settings/google-calendar?connected=true
    On error:    redirects to ADMIN_PANEL_URL/settings/google-calendar?error=<reason>
    """
    settings = get_settings()
    base_redirect = f"{settings.ADMIN_PANEL_URL}/settings/google-calendar"

    # --- Google returned an error (user denied access, etc.) ---
    if error:
        logger.warning("Google OAuth2 callback returned error: %s", error)
        return RedirectResponse(
            url=f"{base_redirect}?error={error}",
            status_code=302,
        )

    # --- Missing required params ---
    if not code or not state:
        logger.warning(
            "OAuth2 callback missing required params: code=%s, state=%s",
            bool(code),
            bool(state),
        )
        return RedirectResponse(
            url=f"{base_redirect}?error=missing_params",
            status_code=302,
        )

    # --- CSRF validation (consume state from Redis) ---
    state_valid, code_verifier = await _consume_csrf_state(state)
    if not state_valid:
        logger.warning("OAuth2 callback CSRF state invalid or expired (state=%s...)", state[:8])
        return RedirectResponse(
            url=f"{base_redirect}?error=invalid_state",
            status_code=302,
        )

    # --- Exchange authorization code for tokens ---
    try:
        async with get_async_session() as session:
            # Pass state as both state and expected_state — Redis validation above
            # already confirmed the state is genuine; the service does an internal
            # equality check which will trivially pass (state == state).
            result = await _oauth_service.exchange_code(
                code=code,
                state=state,
                expected_state=state,
                session=session,
                code_verifier=code_verifier,
            )
        logger.info("Google OAuth2 connection successful for email=%s", result.get("email"))
        return RedirectResponse(
            url=f"{base_redirect}?connected=true",
            status_code=302,
        )

    except GoogleOAuthCSRFError as exc:
        # Shouldn't happen (we already validated in Redis), but handle defensively
        logger.error("OAuth2 CSRF error during code exchange: %s", exc)
        return RedirectResponse(
            url=f"{base_redirect}?error=csrf_error",
            status_code=302,
        )

    except GoogleOAuthError as exc:
        logger.error("OAuth2 code exchange failed: %s", exc)
        return RedirectResponse(
            url=f"{base_redirect}?error=exchange_failed",
            status_code=302,
        )

    except Exception as exc:
        logger.error("Unexpected error during OAuth2 callback: %s", exc, exc_info=True)
        return RedirectResponse(
            url=f"{base_redirect}?error=internal_error",
            status_code=302,
        )


@router.get("/calendars")
async def list_google_calendars(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict[str, list[dict]]:
    """
    List Google Calendars accessible from the connected account.

    Only returns calendars where the connected account has owner or writer
    access (i.e., can create and edit events).

    Response:
        calendars (list): Each item has id, summary, description, timeZone, primary,
                          access_role, background_color.
    """
    try:
        async with get_async_session() as session:
            raw_calendars = await _oauth_service.list_calendars(session)

        # Normalise field names to snake_case for the API response; pass through
        # extended fields returned after Phase 1 service update.
        calendars = [
            {
                "id": cal.get("id", ""),
                "summary": cal.get("summary", ""),
                "description": cal.get("description", ""),
                "timeZone": cal.get("timeZone", ""),
                "primary": cal.get("primary", False),
                "access_role": cal.get("accessRole", ""),
                "background_color": cal.get("backgroundColor") or None,
            }
            for cal in raw_calendars
        ]
        return {"calendars": calendars}

    except GoogleOAuthNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No Google account connected. "
                "Connect a Google account from the admin panel first."
            ),
        )

    except GoogleOAuthTokenRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Google OAuth2 refresh token was revoked. "
                "Reconnect the Google account from the admin panel."
            ),
        )

    except GoogleOAuthError as exc:
        logger.error("Error listing Google calendars: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve calendars from Google: {exc}",
        )


@router.post("/calendars", status_code=status.HTTP_201_CREATED)
async def create_google_calendar(
    body: CreateCalendarRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> CalendarResponse:
    """
    Create a new secondary Google Calendar owned by the connected account.

    The calendar appears in the list immediately — no page refresh required.

    Request body:
        summary (str, required): Display name (1-200 chars).
        description (str, optional): Calendar description.
        timeZone (str, optional): IANA time zone (default: Europe/Madrid).

    Response:
        201 Created — CalendarResponse with the new calendar's details.
        400 Bad Request — summary is empty.
        401 Unauthorized — no OAuth credentials stored / token revoked.
        502 Bad Gateway — Google Calendar API failure.
    """
    if not body.summary.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre del calendario es obligatorio.",
        )

    try:
        async with get_async_session() as session:
            calendar = await _oauth_service.create_calendar(
                session=session,
                summary=body.summary.strip(),
                description=body.description or None,
                time_zone=body.timeZone or None,
            )

        logger.info(
            "Admin user=%s created Google Calendar id=%s",
            current_user.username,
            calendar.get("id"),
        )
        return CalendarResponse(
            id=calendar.get("id", ""),
            summary=calendar.get("summary", ""),
            description=calendar.get("description", ""),
            timeZone=calendar.get("timeZone", ""),
            primary=calendar.get("primary", False),
            accessRole="owner",
        )

    except GoogleOAuthNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "No Google account connected. "
                "Connect a Google account from the admin panel first."
            ),
        )

    except GoogleOAuthTokenRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Google OAuth2 refresh token was revoked. "
                "Reconnect the Google account from the admin panel."
            ),
        )

    except GoogleOAuthError as exc:
        logger.error("Error creating Google Calendar: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo crear el calendario en Google: {exc}",
        )


@router.patch("/calendars/{calendar_id}")
async def update_google_calendar(
    calendar_id: str,
    body: UpdateCalendarRequest,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> CalendarResponse:
    """
    Partially update a Google Calendar's name and/or description.

    Only provided fields are changed (PATCH semantics — uses calendars().patch()).

    Path parameters:
        calendar_id: The calendar's Google ID (FastAPI handles URL decoding).

    Request body:
        summary (str | None): New display name.
        description (str | None): New description.
        At least one must be provided.

    Response:
        200 OK — CalendarResponse with updated calendar details.
        400 Bad Request — both summary and description are None (empty body).
        404 Not Found — calendar_id does not exist in Google.
        502 Bad Gateway — Google Calendar API failure.
    """
    if body.summary is None and body.description is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se debe proporcionar al menos summary o description para actualizar.",
        )

    try:
        async with get_async_session() as session:
            calendar = await _oauth_service.update_calendar(
                session=session,
                calendar_id=calendar_id,
                summary=body.summary,
                description=body.description,
            )

        logger.info(
            "Admin user=%s updated Google Calendar id=%s",
            current_user.username,
            calendar_id,
        )
        return CalendarResponse(
            id=calendar.get("id", ""),
            summary=calendar.get("summary", ""),
            description=calendar.get("description", ""),
            timeZone=calendar.get("timeZone", ""),
            primary=calendar.get("primary", False),
        )

    except GoogleOAuthNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "No Google account connected. "
                "Connect a Google account from the admin panel first."
            ),
        )

    except GoogleOAuthTokenRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Google OAuth2 refresh token was revoked. "
                "Reconnect the Google account from the admin panel."
            ),
        )

    except GoogleOAuthError as exc:
        error_msg = str(exc)
        # Detect 404 from the wrapped exception message (GoogleCalendarError wraps HttpError)
        if "404" in error_msg or "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Calendario no encontrado en Google: {calendar_id}",
            )
        logger.error("Error updating Google Calendar %s: %s", calendar_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo actualizar el calendario en Google: {exc}",
        )


@router.delete("/calendars/{calendar_id}")
async def delete_google_calendar(
    calendar_id: str,
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict[str, Any]:
    """
    Delete a Google Calendar by ID.

    Safety check: if any stylist has this calendar assigned as their
    google_calendar_id, the deletion is blocked (409 Conflict) to prevent
    data loss and booking failures.

    Path parameters:
        calendar_id: The calendar's Google ID (FastAPI handles URL decoding).

    Response:
        200 OK — calendar deleted (or was already deleted — idempotent).
        403 Forbidden — calendar is the Google account's primary calendar.
        404 Not Found — not returned (404 from Google is treated as idempotent 200).
        409 Conflict — one or more stylists are using this calendar.
        502 Bad Gateway — Google Calendar API failure.
    """
    # Safety check: ensure no stylist has this calendar assigned
    async with get_async_session() as session:
        result = await session.execute(
            select(Stylist).where(
                Stylist.google_calendar_id == calendar_id,
                Stylist.is_active.is_(True),
            )
        )
        assigned_stylists = result.scalars().all()

    if assigned_stylists:
        stylist_names = [s.name for s in assigned_stylists]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "No se puede eliminar el calendario porque está asignado a "
                    f"{len(stylist_names)} estilista(s). "
                    "Reasigna su calendario antes de continuar."
                ),
                "stylist_names": stylist_names,
            },
        )

    # Proceed with deletion
    try:
        async with get_async_session() as session:
            await _oauth_service.delete_calendar(session=session, calendar_id=calendar_id)

        logger.info(
            "Admin user=%s deleted Google Calendar id=%s",
            current_user.username,
            calendar_id,
        )
        return {"deleted": True, "calendar_id": calendar_id}

    except PrimaryCalendarError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No se puede eliminar el calendario principal.",
        )

    except GoogleOAuthNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "No Google account connected. "
                "Connect a Google account from the admin panel first."
            ),
        )

    except GoogleOAuthTokenRevokedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Google OAuth2 refresh token was revoked. "
                "Reconnect the Google account from the admin panel."
            ),
        )

    except GoogleOAuthError as exc:
        logger.error("Error deleting Google Calendar %s: %s", calendar_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo eliminar el calendario de Google: {exc}",
        )


@router.delete("/disconnect")
async def disconnect_google_account(
    current_user: Annotated[AdminUser, Depends(require_permission("system:settings"))],
) -> dict[str, bool]:
    """
    Disconnect the Google account by deactivating and clearing all credentials.

    Does NOT revoke the token at Google's servers — the admin must do that from
    their Google Account security settings if desired.

    Response:
        disconnected (bool): Always True on success.
    """
    async with get_async_session() as session:
        await _oauth_service.disconnect(session)

    logger.info("Google account disconnected by admin user=%s", current_user.username)
    return {"disconnected": True}
