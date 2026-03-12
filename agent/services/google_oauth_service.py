"""
Google OAuth2 service for admin panel calendar integration.

Handles the full OAuth2 lifecycle:
- Authorization URL generation with CSRF state
- Code → token exchange
- Automatic token refresh (with asyncio.Lock for concurrent safety)
- Calendar discovery (calendarList.list)
- Connection status
- Disconnect (token deletion)

Usage:
    from agent.services.google_oauth_service import GoogleOAuthService

    service = GoogleOAuthService()

    # Generate auth URL
    auth_url, state = service.generate_auth_url()

    # Exchange code after redirect
    result = await service.exchange_code(code, state, expected_state, session)

    # Get usable credentials (with auto-refresh)
    creds = await service.get_credentials(session)

    # List connected calendars
    calendars = await service.list_calendars(session)
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import GoogleOAuthCredential
from shared.config import get_settings
from shared.encryption import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]

# Buffer: refresh if the token expires within 5 minutes
_TOKEN_EXPIRY_BUFFER = timedelta(minutes=5)

# Module-level lock: prevents concurrent refresh races for the same credential.
# One asyncio.Lock is sufficient because all coroutines in this process share the
# same event loop and a single active credential row exists.
_refresh_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class GoogleOAuthError(Exception):
    """Base Google OAuth2 error."""


class GoogleOAuthNotConfiguredError(GoogleOAuthError):
    """No active OAuth2 credentials found in the database."""


class GoogleOAuthTokenRevokedError(GoogleOAuthError):
    """The refresh token was revoked by the user from Google account settings."""


class GoogleOAuthCSRFError(GoogleOAuthError):
    """CSRF state mismatch — possible replay or session fixation attack."""


# Calendar CRUD exceptions (aliases kept under GoogleCalendarError namespace)
GoogleCalendarError = GoogleOAuthError


class PrimaryCalendarError(GoogleCalendarError):
    """Raised when attempting to delete a primary calendar (Google returns 403)."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GoogleOAuthService:
    """Manages Google OAuth2 credentials for the salon's Google Calendar integration."""

    def __init__(self) -> None:
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_flow(self) -> Flow:
        """
        Build a google_auth_oauthlib.flow.Flow from app settings.

        Uses Flow.from_client_config() so we never need the secrets file on
        disk — everything comes from environment variables.
        """
        client_config = {
            "web": {
                "client_id": self.settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": self.settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.settings.GOOGLE_OAUTH_REDIRECT_URI],
            }
        }
        flow = Flow.from_client_config(client_config, scopes=SCOPES)
        flow.redirect_uri = self.settings.GOOGLE_OAUTH_REDIRECT_URI
        return flow

    # ------------------------------------------------------------------
    # OAuth2 Flow
    # ------------------------------------------------------------------

    def generate_auth_url(self, state: Optional[str] = None) -> tuple[str, str, str]:
        """
        Generate the Google OAuth2 authorization URL with PKCE.

        A cryptographically random state token is generated here and MUST be
        stored by the caller (e.g., in the server-side session) and compared
        against the state returned by Google's redirect.

        PKCE (Proof Key for Code Exchange) is enabled by default via
        autogenerate_code_verifier=True in Flow. The generated code_verifier
        MUST be stored alongside the state and reused during code exchange.

        Args:
            state: Optional pre-computed state. If omitted, a random one is
                   generated using secrets.token_urlsafe(32).

        Returns:
            Tuple of (auth_url, state, code_verifier).
        """
        if state is None:
            state = secrets.token_urlsafe(32)

        flow = self._build_flow()
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",      # Force refresh token even if previously granted
            include_granted_scopes=False,
            state=state,
        )
        code_verifier = flow.code_verifier
        if code_verifier is None:
            raise GoogleOAuthError("PKCE code_verifier was not generated by Flow")
        logger.debug("Generated Google OAuth2 authorization URL (state=%s...)", state[:8])
        return auth_url, state, code_verifier

    async def exchange_code(
        self,
        code: str,
        state: str,
        expected_state: str,
        session: AsyncSession,
        code_verifier: Optional[str] = None,
    ) -> dict:
        """
        Exchange an authorization code for tokens and persist them in the DB.

        Steps:
        1. Validate CSRF state.
        2. Exchange code via Flow.fetch_token().
        3. Retrieve the connected email via Google's userinfo endpoint.
        4. Encrypt the access and refresh tokens.
        5. Deactivate any existing active credential.
        6. Insert the new GoogleOAuthCredential row.
        7. Return ``{"email": str, "calendars": list}``.

        Args:
            code: The authorization code from Google's redirect.
            state: The state value returned by Google's redirect.
            expected_state: The state value stored server-side before redirect.
            session: Active async database session.
            code_verifier: The PKCE code verifier generated during auth URL creation.
                           If None, falls back to autogenerate_code_verifier=True
                           (for backward compatibility with old states).

        Returns:
            Dict with keys ``email`` (str) and ``calendars`` (list of dicts).

        Raises:
            GoogleOAuthCSRFError: If ``state != expected_state``.
            GoogleOAuthError: If the token exchange or DB operation fails.
        """
        # 1. CSRF validation
        if state != expected_state:
            raise GoogleOAuthCSRFError(
                "OAuth2 state mismatch — possible CSRF attack. Aborting."
            )

        # 2. Exchange code for tokens (sync — run in thread pool)
        loop = asyncio.get_event_loop()
        try:
            if code_verifier:
                flow = self._build_flow()
                flow.code_verifier = code_verifier
            else:
                flow = self._build_flow()

            def _fetch_token() -> None:
                flow.fetch_token(code=code)

            await loop.run_in_executor(None, _fetch_token)
        except Exception as exc:
            logger.error("OAuth2 code exchange failed: %s", exc)
            raise GoogleOAuthError(f"Token exchange failed: {exc}") from exc

        google_creds: Credentials = flow.credentials

        # 3. Retrieve user email via userinfo endpoint
        email = await self._get_user_email(google_creds.token)

        # 4. Encrypt tokens
        encrypted_access = encrypt_token(google_creds.token)
        encrypted_refresh = encrypt_token(google_creds.refresh_token or "")

        token_expiry: Optional[datetime] = google_creds.expiry
        if token_expiry is not None and token_expiry.tzinfo is None:
            # google-auth returns naive UTC datetimes — make them tz-aware
            token_expiry = token_expiry.replace(tzinfo=timezone.utc)

        scopes = list(google_creds.scopes) if google_creds.scopes else SCOPES

        # 5. Deactivate any existing active credentials
        await session.execute(
            update(GoogleOAuthCredential)
            .where(GoogleOAuthCredential.is_active.is_(True))
            .values(is_active=False)
        )

        # 6. Insert new active credential
        now_utc = datetime.now(timezone.utc)
        new_cred = GoogleOAuthCredential(
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            token_expiry=token_expiry,
            connected_email=email,
            calendar_scopes=scopes,
            is_active=True,
            connected_at=now_utc,
            last_refresh_at=None,
        )
        session.add(new_cred)
        await session.commit()
        await session.refresh(new_cred)

        logger.info("Google OAuth2 credentials stored for email=%s", email)

        # 7. Return summary (calendars discovery)
        calendars = await self.list_calendars(session)
        return {"email": email, "calendars": calendars}

    # ------------------------------------------------------------------
    # Token Management
    # ------------------------------------------------------------------

    async def get_credentials(self, session: AsyncSession) -> Credentials:
        """
        Return valid Google OAuth2 credentials, refreshing if needed.

        Fetches the active credential row from the DB and delegates to
        ``refresh_if_needed()``.

        Args:
            session: Active async database session.

        Returns:
            A ``google.oauth2.credentials.Credentials`` object guaranteed to
            be valid for at least 5 minutes.

        Raises:
            GoogleOAuthNotConfiguredError: If no active credential row exists.
            GoogleOAuthTokenRevokedError: If the refresh token was revoked.
        """
        result = await session.execute(
            select(GoogleOAuthCredential).where(
                GoogleOAuthCredential.is_active.is_(True)
            )
        )
        cred_row = result.scalar_one_or_none()
        if cred_row is None:
            raise GoogleOAuthNotConfiguredError(
                "No active Google OAuth2 credentials found. "
                "Connect a Google account from the admin panel."
            )

        return await self.refresh_if_needed(cred_row, session)

    async def refresh_if_needed(
        self,
        cred_row: GoogleOAuthCredential,
        session: AsyncSession,
    ) -> Credentials:
        """
        Refresh the access token if it is expired or expiring within 5 minutes.

        Uses ``_refresh_lock`` (module-level asyncio.Lock) to prevent multiple
        concurrent refresh calls for the same credential.

        Args:
            cred_row: The ORM row from ``google_oauth_credentials``.
            session: Active async database session (used to persist refreshed tokens).

        Returns:
            Updated ``google.oauth2.credentials.Credentials``.

        Raises:
            GoogleOAuthTokenRevokedError: If ``invalid_grant`` is detected.
            GoogleOAuthError: For other refresh failures.
        """
        access_token = decrypt_token(cred_row.encrypted_access_token)
        refresh_token_str = decrypt_token(cred_row.encrypted_refresh_token)
        expiry = cred_row.token_expiry

        # Determine whether a refresh is required
        needs_refresh = False
        if expiry is None:
            needs_refresh = True  # Unknown expiry — refresh to be safe
        else:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            needs_refresh = datetime.now(timezone.utc) >= (expiry - _TOKEN_EXPIRY_BUFFER)

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token_str,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=self.settings.GOOGLE_OAUTH_CLIENT_SECRET,
            scopes=cred_row.calendar_scopes or SCOPES,
        )

        if not needs_refresh:
            logger.debug("OAuth2 access token still valid, skipping refresh")
            return creds

        async with _refresh_lock:
            # Re-check expiry after acquiring the lock — another coroutine may have
            # already refreshed while we were waiting.
            result = await session.execute(
                select(GoogleOAuthCredential).where(
                    GoogleOAuthCredential.id == cred_row.id
                )
            )
            fresh_row = result.scalar_one_or_none()
            if fresh_row is not None and fresh_row.token_expiry is not None:
                fresh_expiry = fresh_row.token_expiry
                if fresh_expiry.tzinfo is None:
                    fresh_expiry = fresh_expiry.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < (fresh_expiry - _TOKEN_EXPIRY_BUFFER):
                    # Another coroutine already refreshed — use its tokens
                    logger.debug("Token was refreshed concurrently, using fresh token")
                    fresh_access = decrypt_token(fresh_row.encrypted_access_token)
                    creds = Credentials(
                        token=fresh_access,
                        refresh_token=decrypt_token(fresh_row.encrypted_refresh_token),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=self.settings.GOOGLE_OAUTH_CLIENT_ID,
                        client_secret=self.settings.GOOGLE_OAUTH_CLIENT_SECRET,
                        scopes=fresh_row.calendar_scopes or SCOPES,
                    )
                    return creds

            logger.info("Refreshing Google OAuth2 access token")
            loop = asyncio.get_event_loop()
            try:
                def _do_refresh() -> None:
                    creds.refresh(Request())

                await loop.run_in_executor(None, _do_refresh)
            except RefreshError as exc:
                if "invalid_grant" in str(exc).lower():
                    logger.error(
                        "Google OAuth2 refresh token revoked (invalid_grant). "
                        "Admin must reconnect their Google account."
                    )
                    raise GoogleOAuthTokenRevokedError(
                        "Refresh token was revoked. Reconnect the Google account from the admin panel."
                    ) from exc
                logger.error("Google OAuth2 token refresh failed: %s", exc)
                raise GoogleOAuthError(f"Token refresh failed: {exc}") from exc
            except Exception as exc:
                logger.error("Unexpected error during token refresh: %s", exc)
                raise GoogleOAuthError(f"Token refresh failed: {exc}") from exc

            # Persist updated tokens
            new_expiry = creds.expiry
            if new_expiry is not None and new_expiry.tzinfo is None:
                new_expiry = new_expiry.replace(tzinfo=timezone.utc)

            await session.execute(
                update(GoogleOAuthCredential)
                .where(GoogleOAuthCredential.id == cred_row.id)
                .values(
                    encrypted_access_token=encrypt_token(creds.token),
                    token_expiry=new_expiry,
                    last_refresh_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            logger.debug("Persisted refreshed OAuth2 access token")

        return creds

    # ------------------------------------------------------------------
    # Calendar Discovery
    # ------------------------------------------------------------------

    async def list_calendars(self, session: AsyncSession) -> list[dict]:
        """
        List calendars accessible from the connected Google account.

        Only returns calendars where the connected account has ``owner`` or
        ``writer`` access (i.e., can create/edit events).

        Args:
            session: Active async database session.

        Returns:
            List of dicts, each with keys:
            ``id``, ``summary``, ``accessRole``, ``backgroundColor``,
            ``description``, ``timeZone``, ``primary``.
        """
        creds = await self.get_credentials(session)

        loop = asyncio.get_event_loop()

        def _list_cals() -> list[dict]:
            service = build("calendar", "v3", credentials=creds)
            response = service.calendarList().list().execute()
            items = response.get("items", [])
            allowed_roles = {"owner", "writer"}
            return [
                {
                    "id": item.get("id", ""),
                    "summary": item.get("summary", ""),
                    "accessRole": item.get("accessRole", ""),
                    "backgroundColor": item.get("backgroundColor", ""),
                    "description": item.get("description", ""),
                    "timeZone": item.get("timeZone", ""),
                    "primary": item.get("primary", False),
                }
                for item in items
                if item.get("accessRole") in allowed_roles
            ]

        calendars = await loop.run_in_executor(None, _list_cals)
        logger.debug("Listed %d calendars from connected Google account", len(calendars))
        return calendars

    # ------------------------------------------------------------------
    # Calendar CRUD
    # ------------------------------------------------------------------

    async def create_calendar(
        self,
        session: AsyncSession,
        summary: str,
        description: Optional[str] = None,
        time_zone: Optional[str] = None,
    ) -> dict:
        """
        Create a new secondary Google Calendar owned by the connected account.

        Uses ``calendars().insert()`` (creates the actual calendar resource,
        not merely a calendarList subscription).

        Args:
            session: Active async database session.
            summary: Display name for the new calendar (required).
            description: Optional description text.
            time_zone: Optional IANA time zone string (e.g. "Europe/Madrid").

        Returns:
            Dict with keys: ``id``, ``summary``, ``description``, ``timeZone``,
            ``primary`` (always False for new secondary calendars).

        Raises:
            GoogleCalendarError: If the Google Calendar API call fails.
        """
        creds = await self.get_credentials(session)
        loop = asyncio.get_event_loop()

        body: dict = {"summary": summary}
        if description is not None:
            body["description"] = description
        if time_zone is not None:
            body["timeZone"] = time_zone

        def _create() -> dict:
            service = build("calendar", "v3", credentials=creds)
            result = service.calendars().insert(body=body).execute()
            return {
                "id": result.get("id", ""),
                "summary": result.get("summary", ""),
                "description": result.get("description", ""),
                "timeZone": result.get("timeZone", ""),
                "primary": False,
            }

        try:
            calendar = await loop.run_in_executor(None, _create)
        except Exception as exc:
            logger.error("Failed to create Google Calendar: %s", exc)
            raise GoogleCalendarError(f"Failed to create calendar: {exc}") from exc

        logger.info("Created Google Calendar id=%s summary=%r", calendar["id"], calendar["summary"])
        return calendar

    async def update_calendar(
        self,
        session: AsyncSession,
        calendar_id: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        time_zone: Optional[str] = None,
    ) -> dict:
        """
        Partially update a Google Calendar's metadata.

        Uses ``calendars().patch()`` so only the provided fields are changed.
        Fields that are None are omitted from the request body — Google will
        leave those fields unchanged.

        Args:
            session: Active async database session.
            calendar_id: The calendar's Google ID (e.g. the email-like string).
            summary: New display name, or None to leave unchanged.
            description: New description, or None to leave unchanged.
            time_zone: New IANA time zone string, or None to leave unchanged.

        Returns:
            Dict with keys: ``id``, ``summary``, ``description``, ``timeZone``,
            ``primary``.

        Raises:
            GoogleCalendarError: If the Google Calendar API call fails.
        """
        creds = await self.get_credentials(session)
        loop = asyncio.get_event_loop()

        body: dict = {}
        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if time_zone is not None:
            body["timeZone"] = time_zone

        def _update() -> dict:
            service = build("calendar", "v3", credentials=creds)
            result = service.calendars().patch(calendarId=calendar_id, body=body).execute()
            return {
                "id": result.get("id", ""),
                "summary": result.get("summary", ""),
                "description": result.get("description", ""),
                "timeZone": result.get("timeZone", ""),
                "primary": result.get("primary", False),
            }

        try:
            calendar = await loop.run_in_executor(None, _update)
        except Exception as exc:
            logger.error("Failed to update Google Calendar %s: %s", calendar_id, exc)
            raise GoogleCalendarError(f"Failed to update calendar {calendar_id!r}: {exc}") from exc

        logger.info("Updated Google Calendar id=%s", calendar_id)
        return calendar

    async def delete_calendar(self, session: AsyncSession, calendar_id: str) -> None:
        """
        Delete a Google Calendar.

        Behaviour on special HTTP responses:
        - **403**: The calendar is primary (Google does not allow deletion).
          Raises ``PrimaryCalendarError`` (a ``GoogleCalendarError`` subclass).
        - **404**: The calendar was already deleted — treated as idempotent (no error).
        - **Other error**: Raises ``GoogleCalendarError``.

        Args:
            session: Active async database session.
            calendar_id: The calendar's Google ID.

        Returns:
            None on success (including the 404 idempotent case).

        Raises:
            PrimaryCalendarError: If Google returns 403 (cannot delete primary).
            GoogleCalendarError: For any other API failure.
        """
        from googleapiclient.errors import HttpError  # type: ignore[import]

        creds = await self.get_credentials(session)
        loop = asyncio.get_event_loop()

        def _delete() -> None:
            service = build("calendar", "v3", credentials=creds)
            service.calendars().delete(calendarId=calendar_id).execute()

        try:
            await loop.run_in_executor(None, _delete)
        except HttpError as exc:
            status = exc.resp.status if exc.resp else 0
            if status == 403:
                logger.warning(
                    "Cannot delete primary Google Calendar id=%s (403 Forbidden)", calendar_id
                )
                raise PrimaryCalendarError(
                    f"Cannot delete primary calendar {calendar_id!r}: Google returned 403"
                ) from exc
            if status == 404:
                # Already deleted — treat as idempotent success
                logger.debug(
                    "Google Calendar id=%s already deleted (404) — treating as success",
                    calendar_id,
                )
                return
            logger.error("Failed to delete Google Calendar %s: %s", calendar_id, exc)
            raise GoogleCalendarError(f"Failed to delete calendar {calendar_id!r}: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error deleting Google Calendar %s: %s", calendar_id, exc)
            raise GoogleCalendarError(f"Failed to delete calendar {calendar_id!r}: {exc}") from exc

        logger.info("Deleted Google Calendar id=%s", calendar_id)

    # ------------------------------------------------------------------
    # Status & Disconnect
    # ------------------------------------------------------------------

    async def get_status(self, session: AsyncSession) -> dict:
        """
        Return the current Google OAuth2 connection status.

        Never exposes token values.

        Args:
            session: Active async database session.

        Returns:
            Dict with keys:
            - ``connected`` (bool)
            - ``email`` (str | None)
            - ``connected_at`` (ISO 8601 str | None)
            - ``token_healthy`` (bool) — False if tokens are expired/revoked
            - ``scopes`` (list[str])
        """
        result = await session.execute(
            select(GoogleOAuthCredential).where(
                GoogleOAuthCredential.is_active.is_(True)
            )
        )
        cred_row = result.scalar_one_or_none()

        if cred_row is None:
            return {
                "connected": False,
                "email": None,
                "connected_at": None,
                "token_healthy": False,
                "scopes": [],
            }

        # Check token health without actually refreshing
        token_healthy = True
        try:
            await self.get_credentials(session)
        except (GoogleOAuthTokenRevokedError, GoogleOAuthError):
            token_healthy = False

        connected_at = cred_row.connected_at
        if connected_at is not None and connected_at.tzinfo is None:
            connected_at = connected_at.replace(tzinfo=timezone.utc)

        return {
            "connected": True,
            "email": cred_row.connected_email,
            "connected_at": connected_at.isoformat() if connected_at else None,
            "token_healthy": token_healthy,
            "scopes": cred_row.calendar_scopes or [],
        }

    async def disconnect(self, session: AsyncSession) -> None:
        """
        Disconnect the Google account by deactivating and clearing all credentials.

        Marks all credential rows as inactive and clears their token fields.
        Does NOT revoke the token at Google's servers (the admin must do that
        from their Google account security settings if desired).

        Args:
            session: Active async database session.
        """
        await session.execute(
            update(GoogleOAuthCredential)
            .where(GoogleOAuthCredential.is_active.is_(True))
            .values(
                is_active=False,
                encrypted_access_token="",
                encrypted_refresh_token="",
            )
        )
        await session.commit()
        logger.info("Disconnected Google OAuth2 — all credentials deactivated")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_user_email(self, access_token: str) -> str:
        """
        Retrieve the Google account email associated with an access token.

        Calls Google's userinfo endpoint (v1, no extra scope required for calendar).

        Args:
            access_token: A freshly obtained OAuth2 access token.

        Returns:
            The Google account email address.

        Raises:
            GoogleOAuthError: If the userinfo call fails or the response is invalid.
        """
        url = "https://www.googleapis.com/oauth2/v1/userinfo"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                data = resp.json()
                email = data.get("email")
                if not email:
                    raise GoogleOAuthError(
                        "userinfo endpoint did not return an email address. "
                        f"Response: {data}"
                    )
                return email
        except httpx.HTTPError as exc:
            raise GoogleOAuthError(
                f"Failed to retrieve user email from Google userinfo endpoint: {exc}"
            ) from exc
