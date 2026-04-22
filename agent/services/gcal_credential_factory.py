"""
Google Calendar credential factory.

Single entry point for ALL Google Calendar authentication.

Resolution order:
1. OAuth2 tokens from DB (via GoogleOAuthService) — preferred when configured.
2. Service account file (GOOGLE_SERVICE_ACCOUNT_JSON) — legacy / fallback.
3. Raise GCalAuthError if neither is available.

Backward compatibility:
- Pass ``session=None`` to skip the OAuth2 attempt and go straight to service account.
  Existing callers (gcal_push_service, calendar_tools, gcal_sync_worker) that do not
  have an AsyncSession can call ``get_google_credentials(session=None)`` safely.

Usage:
    from agent.services.gcal_credential_factory import get_google_credentials

    # With DB session (prefers OAuth2, falls back to service account)
    credentials = await get_google_credentials(session)
    service = build("calendar", "v3", credentials=credentials)

    # Without session (always service account — no DB lookup)
    credentials = await get_google_credentials()
    service = build("calendar", "v3", credentials=credentials)
"""

import logging
import os
from typing import Union

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from sqlalchemy.ext.asyncio import AsyncSession

from agent.services.google_oauth_service import (
    GoogleOAuthError,
    GoogleOAuthNotConfiguredError,
    GoogleOAuthService,
    GoogleOAuthTokenRevokedError,
)
from shared.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Module-level singleton — stateless, safe to reuse across calls.
_oauth_service = GoogleOAuthService()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def get_google_credentials(
    session: AsyncSession | None = None,
) -> Union[Credentials, "service_account.Credentials"]:
    """
    Resolve Google Calendar credentials using a two-step fallback strategy.

    Resolution order:
    1. **OAuth2 from DB** — attempted when ``session`` is provided AND
       ``settings.google_oauth_configured`` is True (i.e., GOOGLE_OAUTH_CLIENT_ID
       and GOOGLE_OAUTH_CLIENT_SECRET are set).
    2. **Service account file** — attempted when GOOGLE_SERVICE_ACCOUNT_JSON points
       to an existing file. This is the legacy authentication path.
    3. **GCalAuthError** — raised if neither of the above succeeds.

    Args:
        session: Optional AsyncSession for DB-based OAuth2 credential lookup.
                 Pass ``None`` to skip OAuth2 entirely (e.g., from sync callers
                 or workers that manage their own session lifecycle separately).

    Returns:
        ``google.oauth2.credentials.Credentials`` (OAuth2) or
        ``google.oauth2.service_account.Credentials`` (service account).

    Raises:
        GCalAuthError: If no valid credentials are available from any source.

    Examples:
        # Standard usage — let factory decide
        async with get_async_session() as session:
            creds = await get_google_credentials(session)
            service = build("calendar", "v3", credentials=creds)

        # Legacy usage — no session available
        creds = await get_google_credentials()
        service = build("calendar", "v3", credentials=creds)
    """
    settings = get_settings()

    # -----------------------------------------------------------------------
    # Attempt 1: OAuth2 tokens from DB
    # -----------------------------------------------------------------------
    if session is not None and settings.google_oauth_configured:
        try:
            creds = await _oauth_service.get_credentials(session)
            logger.debug("GCal credentials resolved via OAuth2 (DB tokens)")
            return creds
        except GoogleOAuthNotConfiguredError:
            # No active row in google_oauth_credentials — expected during migration.
            logger.debug(
                "OAuth2 not configured in DB (no active row), " "falling back to service account"
            )
        except GoogleOAuthTokenRevokedError:
            # Token revoked by user — fall back so GCal operations don't break.
            logger.warning(
                "OAuth2 refresh token was revoked by the admin's Google account. "
                "Falling back to service account. "
                "Reconnect via the admin panel to restore OAuth2 auth."
            )
        except GoogleOAuthError as exc:
            # Other OAuth2 failure (network, API, encryption issue, etc.)
            logger.warning(
                "OAuth2 credential resolution failed (%s), " "falling back to service account",
                exc,
            )
        except Exception as exc:  # noqa: BLE001 — intentional broad catch for fallback
            logger.warning(
                "Unexpected error during OAuth2 credential resolution (%s), "
                "falling back to service account",
                exc,
            )

    # -----------------------------------------------------------------------
    # Attempt 2: Service account file
    # -----------------------------------------------------------------------
    sa_path = settings.GOOGLE_SERVICE_ACCOUNT_JSON
    if sa_path and os.path.exists(sa_path):
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        logger.debug("GCal credentials resolved via service account file: %s", sa_path)
        return creds

    # -----------------------------------------------------------------------
    # No credentials available
    # -----------------------------------------------------------------------
    raise GCalAuthError(
        "No Google Calendar credentials available. "
        "Either connect a Google account from the admin panel (OAuth2) "
        "or provide a valid GOOGLE_SERVICE_ACCOUNT_JSON path."
    )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class GCalAuthError(Exception):
    """
    Raised when no valid Google Calendar credentials are available.

    This exception is raised by ``get_google_credentials()`` when both the
    OAuth2 DB path and the service account file path have failed or are
    unconfigured.
    """
